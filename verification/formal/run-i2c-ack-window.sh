#!/usr/bin/env bash
#
# Cold-start runner for the formal property `i2c_ack_window`
# (spec/verification-plan.md section 2.2 follow-on, issue #259, part of #243)
# on the shipped core rtl/protocol_core.v running the committed corrected
# controller-write images firmware/build/i2c_{fast,std}.hex.
#
#   ./verification/formal/run-i2c-ack-window.sh [artifacts-dir]
#
# Requirements on $PATH: yosys (write_aiger), yosys-abc, iverilog + vvp
# (the counterexample replay), python3 and git (the original-schedule
# mutants read the pre-#258 text from git history). No PDK, netlist, klt or
# z3 dependency (see "Engines" below for why z3 is not used here).
#
# What is run, per speed grade (Fast = i2c_fast, Standard = i2c_std), per
# address-outcome leg (ADDR_OUTCOME 1 = peripheral ACKs the address, 0 =
# NACKs it; see i2c_ack_window.sv for why the case split and why it is
# exhaustive):
#
#   prove   ABC `bmc3` on the actual core + committed image to DEPTH =
#           TOTAL-CYCLES + 300 frames (EDGE model: one frame per clock). The
#           image ends in HALT, which holds until reset, so the whole
#           reachable behaviour of the harness model is inside the bound
#           (stated as an argument, not as an unbounded proof; see the
#           record). Required: "No output asserted in DEPTH frames".
#   pdr     ABC `scorr; pdr -a` for PDR_TIME s: an attempt at an UNBOUNDED
#           proof, reported honestly (it has not converged in the time
#           budget on this design; the verdict does not affect the exit
#           code and is never claimed as a proof unless it says so).
#   covers  one ABC bmc3 run per cover (each cover compiled as assert(!c));
#           every cover must be reached on at least one leg.
#   mutants every firmware mutant (images from i2c_ack_images.py, assembled
#           with the repository assembler and hashed) must produce an
#           ASSERTION counterexample from ABC whose assertion label is the
#           expected one, and the witness is REPLAYED in Icarus on the RTL
#           (event simulation of the same harness, no solver): the same
#           assertion must fail at the corresponding cycle, and a VCD is
#           kept. A run with no verdict, a solver crash, a missing log or a
#           survived mutant is a FAILURE, never a rejection; stale logs and
#           traces are deleted first.
#
# Engines: ABC bmc3 is the checker. yosys-smtbmc + z3 is NOT used for these
# properties: measured on this harness, z3 needs about a minute for a
# counterexample at step ~1350 (Fast address slot) and does not finish the
# Fast data slot (step ~2500) in 8 minutes, against well under a second for
# bmc3 at the same depth. The independent second check is therefore the
# witness replay in an event simulator, which executes the RTL rather than
# a SAT encoding of it.
#
# Exit 0 = every expectation met; 1 = something was violated or a tool
# failed (do not mint a record from such a run).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

ART_DIR="${1:-$REPO_ROOT/.loom/formal-scratch/i2c-ack-window}"
mkdir -p "$ART_DIR"
ART_DIR="$(cd "$ART_DIR" && pwd)"

CORE="${CORE:-$REPO_ROOT/rtl/protocol_core.v}"
MONITOR="$SCRIPT_DIR/i2c_ack_window.sv"
HARNESS="$SCRIPT_DIR/formal_top_i2c_ack.v"
IMAGES="$SCRIPT_DIR/i2c_ack_images.py"
GRADES="${GRADES:-i2c_fast i2c_std}"
BMC_TIME="${BMC_TIME:-1800}"
PDR_TIME="${PDR_TIME:-60}"
POST_HALT="${POST_HALT:-300}"

fail=0
RESULTS="$ART_DIR/results.tsv"
: > "$RESULTS"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: $1 not found on PATH" >&2; exit 1; }; }
need yosys
need yosys-abc
need iverilog
need vvp
need python3
need git

echo "== toolchain =="
{
  yosys -V
  echo "yosys-abc: $(yosys-abc -c "version" 2>&1 | grep -m1 'Berkeley')"
  iverilog -V 2>/dev/null | head -1
  python3 --version
  git --version
  uname -srvm
} | tee "$ART_DIR/toolchain.txt"

echo
echo "== input hashes (monitor, harness, DUT, image generator, runner, committed firmware) =="
{
  sha256sum "$MONITOR" "$HARNESS" "$CORE" "$IMAGES" "$SCRIPT_DIR/run-i2c-ack-window.sh"
  for g in $GRADES; do
    sha256sum "$REPO_ROOT/firmware/asm/$g.asm" "$REPO_ROOT/firmware/build/$g.hex" "$REPO_ROOT/firmware/build/$g.cycles.txt"
  done
} | sed "s#$REPO_ROOT/##" | tee "$ART_DIR/hashes.txt"

cat > "$ART_DIR/replay_tb.v" <<'TB'
`timescale 1ns/1ps
// Replay testbench: drives formal_top_i2c_ack with the (ack_raw, ui_in) of an
// ABC counterexample, one word per clock; assertion failures are printed by
// Icarus as "ERROR: <file>:<line>" with the failing time.
module replay_tb;
  reg clk = 1'b0;
  reg [7:0] ui_in = 8'h00;
  reg ack_raw = 1'b0;
  reg [8:0] stim [0:`NFRAMES-1];
  integer cyc = 0;
  formal_top_i2c_ack dut (.clk(clk), .ui_in(ui_in), .ack_raw(ack_raw));
  initial begin
    $readmemh(`STIM, stim);
    {ack_raw, ui_in} = stim[0];
    $dumpfile(`VCD);
    $dumpvars(0, replay_tb);
  end
  always #5 clk = ~clk;
  always @(negedge clk) begin
    cyc <= cyc + 1;
    if (cyc + 1 >= `NFRAMES) $finish;
    {ack_raw, ui_in} <= stim[cyc + 1];
  end
endmodule
TB

OPT_SEQ="opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean"

# elab <rom.v> <out-prefix> <outcome 0|1> <cover-id|0> <smt2 0|1> <dflags>
# cover-id 0: real assertions only (covers removed). cover-id N: cover N
# compiled as assert(!c) (COVERABC). The AIGER export removes $cover cells;
# the smt2 export (mutants, assert build only) keeps the design as is.
elab () {
  local rom="$1" out="$2" outcome="$3" cov="$4" smt="$5" dflags="$6" defs smtcmd=""
  defs="$dflags -D ADDR_OUTCOME=$outcome"
  [ "$cov" != 0 ] && defs="$defs -D COVERABC -D COVER_SEL=$cov"
  [ "$smt" = 1 ] && smtcmd="write_smt2 -wires $out.smt2;"
  rm -f "$out.smt2" "$out.aig" "$out.ywb"
  # shellcheck disable=SC2086
  yosys -ql "$out.yosys.log" -p "read_verilog -formal -sv $CORE; read_verilog -formal -sv -nomem2reg $defs $rom $MONITOR $HARNESS; hierarchy -top formal_top_i2c_ack; proc; flatten; memory_map; $OPT_SEQ; async2sync; dffunmap; setundef -anyseq; $smtcmd chformal -remove -cover; techmap; opt_clean; aigmap; opt_clean; write_aiger -zinit -ywmap $out.ywb $out.aig" 2>"$out.yosys.stderr" \
    && [ -s "$out.aig" ] && { [ "$smt" != 1 ] || [ -s "$out.smt2" ]; }
}

# label <ywb> <output-index>: the assertion's label (a1_..., or the cover
# name for a compiled cover, or h_... for a harness assertion).
label () {
  python3 -I -c '
import json, re, sys
d = json.load(open(sys.argv[1]))
n = d["asserts"][int(sys.argv[2])]
last = n[-1].lstrip("\\")
m = re.search(r"([A-Za-z0-9_]+\.s?v):(\d+)", last)
if not m:
    print(last); sys.exit()
src = open(sys.argv[3]).read().splitlines()
if m.group(1) == "i2c_ack_window.sv":
    c = re.search(r"// cover: (\w+)", src[int(m.group(2)) - 1])
    print("cover:" + c.group(1) if c else "monitor:" + m.group(2))
else:
    print("harness:" + m.group(2))' "$1" "$2" "$MONITOR" 2>/dev/null || echo "?"
}

# bmc <aig> <depth> <log>: first assertion counterexample, if any. Echoes
# "CEX <frame> <output>", "CLEAN <frames>" or "TOOLFAIL".
bmc () {
  local aig="$1" depth="$2" log="$3" hit
  rm -f "$log"
  rm -f "${aig%.aig}.aiw"
  yosys-abc -c "read_aiger $aig; bmc3 -F $depth -T $BMC_TIME; write_cex -a ${aig%.aig}.aiw" >"$log" 2>&1
  hit="$(grep -oE 'Output [0-9]+ of miter .* was asserted in frame [0-9]+' "$log" | head -1)"
  if [ -n "$hit" ]; then
    echo "CEX ${hit##* } $(echo "$hit" | sed -E 's/^Output ([0-9]+) .*/\1/')"
  elif grep -q "No output asserted in $depth frames" "$log"; then
    echo "CLEAN $depth"
  else
    echo "TOOLFAIL"
  fi
}

rec () { printf '%s\n' "$*" | tr ' ' '\t' >> "$RESULTS"; }

# replay <prefix> <rom.v> <outcome> <dflags> <abc-frame> <want-label>:
# replay the ABC witness (<prefix>.aiw) on the RTL harness in Icarus. The
# assertion that fails first must be one of <want-labels>, at simulation
# posedge f-1 for ABC frame f: Yosys evaluates an assertion written in a
# clocked block one step after the event it checks, so the model reports
# the failure at frame f and the event simulation, which checks at the
# edge itself, at posedge f-1 with the same input word index. Every replay
# is held to exactly this offset.
replay () {
  local pre="$1" rom="$2" outcome="$3" dflags="$4" frame="$5" want="$6" sel="${7:-0}" n line t sf lab w ln ok=0
  rm -f "$pre-replay.hex" "$pre-replay.vvp" "$pre-replay.log" "$pre-cex.vcd"
  n="$(python3 -I "$IMAGES" stim "$pre.aiw" "$pre.ywb" "$pre-replay.hex")" || { echo "stimulus extraction failed"; return 1; }
  # shellcheck disable=SC2086
  iverilog -g2012 -o "$pre-replay.vvp" -DNFRAMES=$((frame + 2)) -DSTIM="\"$pre-replay.hex\"" -DVCD="\"$pre-cex.vcd\"" \
    $dflags -D ADDR_OUTCOME="$outcome" -D COVERABC -D COVER_SEL="$sel" "$ART_DIR/replay_tb.v" "$CORE" "$rom" "$MONITOR" "$HARNESS" >"$pre-replay.log" 2>&1 || { echo "iverilog compile failed"; return 1; }
  vvp "$pre-replay.vvp" >>"$pre-replay.log" 2>&1
  line="$(grep -m1 -E '^ERROR: .*:[0-9]+:' "$pre-replay.log")"
  [ -n "$line" ] || { echo "replay: no assertion failure"; return 1; }
  t="$(grep -m1 -A1 -E '^ERROR: ' "$pre-replay.log" | grep -oE 'Time: +[0-9]+' | grep -oE '[0-9]+$')"
  sf=$(( (t / 1000 - 5) / 10 ))
  ln="$(echo "$line" | sed -E 's/^ERROR: .*:([0-9]+):.*/\1/')"
  lab="$(sed -n "${ln}p" "$MONITOR" | sed -E 's/^([A-Za-z0-9_]+):.*/\1/')"
  case "$lab" in *COVER*) lab="cover:$(sed -n "${ln}p" "$MONITOR" | sed -E 's#.*// cover: ##')" ;; esac
  echo "sim posedge $sf $lab"
  for w in $want; do [ "$lab" = "$w" ] && ok=1; done
  [ "$sf" = $((frame - 1)) ] && [ "$ok" = 1 ]
}

COVER_NAMES=""
for g in $GRADES; do
  GD="$ART_DIR/$g"
  rm -rf "$GD/images"
  mkdir -p "$GD/images"
  echo
  echo "================ $g ================"
  if ! python3 -I "$IMAGES" gen "$g" "$GD/images"; then
    echo "ERROR: $g image generation failed" >&2; fail=1; continue
  fi
  DFLAGS="$(python3 -I "$IMAGES" params "$g")"
  DEPTH=$(( $(python3 -I "$IMAGES" field "$GD/images/manifest.json" - TOTAL_CYCLES) + POST_HALT ))
  echo "monitor flags: $DFLAGS ; depth $DEPTH frames (TOTAL-CYCLES + $POST_HALT post-HALT idle frames)"
  python3 -I "$IMAGES" table "$GD/images/manifest.json"
  GOLD="$GD/images/golden.rom.v"

  for outcome in 1 0; do
    LD="$GD/leg$outcome"
    mkdir -p "$LD"
    nm=$([ "$outcome" = 1 ] && echo ACK || echo NACK)
    echo "-- [$g address $nm leg] prove (real core, committed image, ABC bmc3 to $DEPTH frames) --"
    if elab "$GOLD" "$LD/golden" "$outcome" 0 0 "$DFLAGS"; then
      r="$(bmc "$LD/golden.aig" "$DEPTH" "$LD/golden-bmc.log")"
      case "$r" in
        CLEAN*) echo "$g $nm: no assertion fails in $DEPTH frames"; rec prove "$g" "$nm" CLEAN "$DEPTH" "$(sha256sum "$LD/golden.aig" | cut -c1-16)" ;;
        CEX*)   echo "$g $nm: ASSERTION FAILS on the committed image: $r ($(label "$LD/golden.ywb" "${r##* }"))" >&2; fail=1; rec prove "$g" "$nm" CEX "$r" ;;
        *)      echo "$g $nm: TOOL FAILURE in the prove leg (no verdict); see $LD/golden-bmc.log" >&2; fail=1; rec prove "$g" "$nm" TOOLFAIL ;;
      esac
      # Unbounded attempt (informational).
      rm -f "$LD/golden-pdr.log"
      yosys-abc -c "read_aiger $LD/golden.aig; scorr; pdr -a -T $PDR_TIME" >"$LD/golden-pdr.log" 2>&1
      pl="$(grep -E 'Properties: +All = ' "$LD/golden-pdr.log" | tail -1)"
      echo "$g $nm: pdr ($PDR_TIME s, informational; NOT the guarantee): ${pl:-no verdict}"
      rec pdr "$g" "$nm" "${pl:-noverdict}"
    else
      echo "ERROR: $g $nm elaboration failed" >&2; fail=1
    fi

    echo "-- [$g address $nm leg] covers --"
    cmax="$(grep -cE '^ *`COVER\(' "$MONITOR")"
    for c in $(seq 1 "$cmax"); do
      cname="$(grep -E "^ *\`COVER\($c," "$MONITOR" | sed -E 's#.*// cover: ##')"
      if ! elab "$GOLD" "$LD/cover$c" "$outcome" "$c" 0 "$DFLAGS"; then
        echo "ERROR: $g $nm cover $c elaboration failed" >&2; fail=1; continue
      fi
      r="$(bmc "$LD/cover$c.aig" "$DEPTH" "$LD/cover$c-bmc.log")"
      case "$r" in
        CEX*) lab="$(label "$LD/cover$c.ywb" "${r##* }")"
              if [ "$lab" = "cover:$cname" ]; then
                cf="$(echo "$r" | cut -d' ' -f2)"
                rr="$(replay "$LD/cover$c" "$GOLD" "$outcome" "$DFLAGS" "$cf" "cover:$cname" "$c")"; rok=$?
                if [ "$rok" = 0 ]; then
                  echo "  cover $cname: reached at frame $cf (Icarus replay: $rr)"; rec cover "$g" "$nm" "$cname" REACHED "$cf" "replay:$rr"
                else
                  echo "  cover $cname: ABC reached it at frame $cf but the RTL replay did not reproduce it ($rr)" >&2; fail=1; rec cover "$g" "$nm" "$cname" REPLAYFAIL "$cf" "replay:$rr"
                fi
              else
                echo "  cover $cname: a real assertion ($lab) failed first: $r" >&2; fail=1; rec cover "$g" "$nm" "$cname" ASSERTFAIL "$lab"
              fi ;;
        CLEAN*) echo "  cover $cname: unreachable on this leg"; rec cover "$g" "$nm" "$cname" UNREACHED ;;
        *) echo "  cover $cname: TOOL FAILURE (no verdict)" >&2; fail=1; rec cover "$g" "$nm" "$cname" TOOLFAIL ;;
      esac
    done
  done

  echo "-- [$g] mutants (firmware images; ABC assertion counterexample + Icarus replay) --"
  for m in $(python3 -I "$IMAGES" list "$GD/images/manifest.json"); do
    expect="$(python3 -I "$IMAGES" field "$GD/images/manifest.json" "$m" expect)"
    legs="$(python3 -I "$IMAGES" field "$GD/images/manifest.json" "$m" legs)"
    hh="$(python3 -I "$IMAGES" field "$GD/images/manifest.json" "$m" hex_sha256 | cut -c1-16)"
    first=1
    for outcome in $legs; do
      nm=$([ "$outcome" = 1 ] && echo ACK || echo NACK)
      MD="$GD/mutants/leg$outcome"; mkdir -p "$MD"
      pre="$MD/$m"
      if ! elab "$GD/images/$m.rom.v" "$pre" "$outcome" 0 0 "$DFLAGS"; then
        echo "$g $m [$nm]: TOOL FAILURE (elaboration)" >&2; fail=1; rec mutant "$g" "$m" "$nm" TOOLFAIL; continue
      fi
      r="$(bmc "$pre.aig" "$DEPTH" "$pre-bmc.log")"
      case "$r" in
        CEX*)
          frame="$(echo "$r" | cut -d' ' -f2)"; lab="$(label "$pre.ywb" "${r##* }")"
          ok=0; for e in $expect; do [ "$lab" = "$e" ] && ok=1; done
          if [ "$ok" != 1 ]; then
            echo "$g $m [$nm]: rejected at frame $frame by $lab, NOT the expected assertion ($expect)" >&2; fail=1
            rec mutant "$g" "$m" "$nm" WRONGASSERT "$frame" "$lab"; continue
          fi
          rr="$(replay "$pre" "$GD/images/$m.rom.v" "$outcome" "$DFLAGS" "$frame" "$expect")"; rok=$?
          if [ "$rok" = 0 ]; then
            echo "$g $m [$nm] (hex $hh): REJECTED -- ABC frame $frame $lab; Icarus replay: $rr; VCD $(basename "$pre-cex.vcd")"
            rec mutant "$g" "$m" "$nm" REJECTED "$frame" "$lab" "replay:$rr" "hex:$hh"
          else
            echo "$g $m [$nm]: ABC counterexample NOT reproduced by the RTL replay ($rr) -- tool problem, not evidence" >&2; fail=1
            rec mutant "$g" "$m" "$nm" REPLAYFAIL "$frame" "$lab" "replay:$rr"
          fi
          first=0 ;;
        CLEAN*) echo "$g $m [$nm]: SURVIVED $DEPTH frames -- the checker missed this fault" >&2; fail=1; rec mutant "$g" "$m" "$nm" SURVIVED ;;
        *) echo "$g $m [$nm]: TOOL FAILURE (no verdict; this is NOT a rejection); see $pre-bmc.log" >&2; fail=1; rec mutant "$g" "$m" "$nm" TOOLFAIL ;;
      esac
    done
  done
done

echo
echo "== cover union over the address-outcome legs =="
python3 -I - "$RESULTS" <<'PY' || fail=1
import sys, collections
reach = collections.defaultdict(set); allc = collections.defaultdict(set)
for line in open(sys.argv[1]):
    f = line.rstrip("\n").split("\t")
    if f[0] == "cover":
        _, g, leg, name, st = f[:5]
        allc[g].add(name)
        if st == "REACHED":
            reach[g].add(name)
ok = True
for g in sorted(allc):
    miss = sorted(allc[g] - reach[g])
    print(f"{g}: {len(reach[g])}/{len(allc[g])} covers reached on some leg" + (f"; UNREACHED: {miss}" if miss else ""))
    ok = ok and not miss
sys.exit(0 if ok else 1)
PY

echo
if [ "$fail" -eq 0 ]; then
  echo "RESULT: all expectations met (no assertion fails on either committed image within the stated depth, every cover reached, every mutant rejected by ABC and reproduced by the Icarus replay)"
else
  echo "RESULT: FAILED -- do not mint a record from this run" >&2
fi
exit "$fail"
