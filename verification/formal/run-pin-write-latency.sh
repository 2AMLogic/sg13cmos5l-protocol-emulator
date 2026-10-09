#!/usr/bin/env bash
#
# Cold-start runner for the formal property `pin_write_latency`
# (spec/verification-plan.md section 2.2, issue #116) on the shipped core
# rtl/protocol_core.v.
#
# Cold start (a third party with a fresh clone needs exactly this):
#
#   ./verification/formal/run-pin-write-latency.sh [artifacts-dir]
#
# Requirements on $PATH: yosys (with write_smt2/write_aiger/clk2fflogic),
# yosys-smtbmc and yosys-abc (both ship with the Yosys distribution), z3,
# and python3 (mutant generation only). No PDK, netlist, simulator or klt
# dependency: this is a pure RTL-level formal check.
#
# Two clock models (see the monitor header in pin_write_latency.sv):
#   EDGE -- one solver step per clock cycle (async2sync/dffunmap).
#   FINE -- clk2fflogic: clk is a free input, every step is a time sample,
#           inputs may change between edges; adds F1 (outputs change only on
#           a rising clk edge).
#
# Engines, and why there are two:
#   - ABC (yosys-abc) `scorr; pdr -a` on an AIGER export is the PROOF engine:
#     signal correspondence (inductive latch-equivalence reduction) then
#     property-directed reachability. When it reports every property
#     proved, the result is UNBOUNDED -- for the harness model only (8-word
#     anyconst program table, mode_pin-low phase model, clock-synchronised
#     reset; see formal_top_pin_write.v), not for the physical chip.
#     Measured on this design: z3 via yosys-smtbmc cannot get past BMC step
#     7 in minutes on the positive model (the shadow-vs-core register-file
#     equivalence explodes), and plain `pdr` without `scorr` does not
#     converge within 300 s; `scorr` is what makes the proof close.
#   - A raw `bmc3` (no scorr) under a wall-time budget is recorded as an
#     informational, scorr-independent bounded cross-check (depth reached is
#     printed; it is NOT the guarantee).
#   - z3 via yosys-smtbmc runs the cover (non-vacuity) legs and replays every
#     mutant as a second, independent engine that must also produce an
#     assertion counterexample (and a VCD).
#
# Undefined constants: Yosys leaves 'x' constants in full-case/don't-care
# mux defaults; both exports replace them with `setundef -anyseq` (a free
# value every step). That over-approximates the design, so a proof stays
# sound; a spurious counterexample would show up on the positive model.
#
# Plus a clock-model-free structural check (leg [0/6]): every output bit is
# the Q of a rising-edge flop on `clk` with no logic in between.
#
# Exit codes: 0 = every expectation met (structural check passes on the core
# and rejects both registration-breaking mutants, both proofs closed, every
# cover reached, every mutant rejected on its required leg by BOTH engines);
# 1 = an expectation was violated (do not mint a record from such a run).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

ART_DIR="${1:-$REPO_ROOT/.loom/formal-scratch/pin-write-latency}"
mkdir -p "$ART_DIR"
ART_DIR="$(cd "$ART_DIR" && pwd)"

CORE="${CORE:-$REPO_ROOT/rtl/protocol_core.v}"
MONITOR="$SCRIPT_DIR/pin_write_latency.sv"
HARNESS="$SCRIPT_DIR/formal_top_pin_write.v"
MUTGEN="$SCRIPT_DIR/pin_write_mutants.py"

PDR_TIME="${PDR_TIME:-600}"            # s, per proof (measured: well under 1 s)
XBMC_TIME="${XBMC_TIME:-120}"          # s, per raw-bmc3 informational cross-check
COVER_DEPTH_EDGE="${COVER_DEPTH_EDGE:-16}"
COVER_DEPTH_FINE="${COVER_DEPTH_FINE:-30}"
MUT_DEPTH_EDGE="${MUT_DEPTH_EDGE:-24}"
MUT_DEPTH_FINE="${MUT_DEPTH_FINE:-48}"
Z3_TIMEOUT="${Z3_TIMEOUT:-600}"        # s, per z3 leg

fail=0

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: $1 not found on PATH" >&2; exit 1; }; }
need yosys
need yosys-smtbmc
need yosys-abc
need z3
need python3

echo "== toolchain =="
{
  yosys -V
  z3 --version
  echo "yosys-abc: $(yosys-abc -c "version" 2>&1 | grep -m1 'Berkeley')"
  echo "yosys-smtbmc: $(command -v yosys-smtbmc) (ships with the Yosys distribution above; no version flag)"
  python3 --version
  uname -srvm
} | tee "$ART_DIR/toolchain.txt"

echo
echo "== input hashes (monitor of record, harness, DUT, mutant generator, runner) =="
sha256sum "$MONITOR" "$HARNESS" "$CORE" "$MUTGEN" "$SCRIPT_DIR/run-pin-write-latency.sh" \
  | sed "s#$REPO_ROOT/##" | tee "$ART_DIR/hashes.txt"

OPT_SEQ="opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean"

# elab <core.v> <edge|fine> <out-prefix>
# Writes <prefix>.smt2 (covers kept; for z3), and <prefix>.aig/.ywb (covers
# removed; for ABC), both from the same netlist after setundef. The core is
# read WITHOUT -nomem2reg (its async-reset register array is otherwise
# rejected), the monitor/harness WITH it (as in run-no-data-dependent-
# latency.sh); the explicit opt sub-pass sequence is the same one that
# runner documents.
elab () {
  local core="$1" model="$2" out="$3" defs="" clocking
  if [ "$model" = fine ]; then
    defs="-D FINE"
    clocking="clk2fflogic"
  else
    clocking="async2sync; dffunmap"
  fi
  rm -f "$out.smt2" "$out.aig" "$out.ywb"
  yosys -ql "$out.yosys.log" -p "read_verilog -formal -sv $core; read_verilog -formal -sv -nomem2reg $defs $MONITOR $HARNESS; hierarchy -top formal_top_pin_write; proc; flatten; $OPT_SEQ; $clocking; setundef -anyseq; write_smt2 -wires $out.smt2; chformal -remove -cover; techmap; opt_clean; aigmap; opt_clean; write_aiger -zinit -ywmap $out.ywb $out.aig" 2>"$out.yosys.stderr" \
    && [ -s "$out.smt2" ] && [ -s "$out.aig" ]
  # Expected stderr: the mem2reg note for the core's register array, and the
  # AIGER backend's notice that top-level inputs (clk in FINE, ui_in, uio_in,
  # and DR 0012's pm_crc / serial_loaded) become free AIGER inputs. Anything else is shown.
  grep -v -E "Replacing memory .regs with list of registers|Treating (undriven bit|a total of [0-9]+ undriven bits) .*like .anyseq" \
    "$out.yosys.stderr" >&2 || true
}

# assert_name <prefix.ywb> <output-index>: the source location of AIGER bad-state N.
assert_name () {
  python3 -I -c '
import json, re, sys
d = json.load(open(sys.argv[1]))
n = d["asserts"][int(sys.argv[2])][0]
m = re.search(r"([A-Za-z0-9_]+\.s?v):(\d+)", n)
print(f"{m.group(1)}:{m.group(2)}" if m else n)' "$1" "$2" 2>/dev/null || echo "?"
}

# prove <label> <prefix>: ABC scorr + pdr -a must prove every property.
prove () {
  local label="$1" p="$2" log="$2-proof.log"
  yosys-abc -c "read_aiger $p.aig; print_stats; scorr; print_stats; pdr -a -T $PDR_TIME" >"$log" 2>&1
  local line; line="$(grep -E 'Properties: +All = ' "$log" | tail -1)"
  if echo "$line" | grep -qE 'All = ([0-9]+)\. Proved = \1\. Disproved = 0\. Undecided = 0\.'; then
    echo "$label: PROVED (unbounded, harness model) -- $line"
  else
    echo "$label: NOT PROVED -- ${line:-no PDR verdict in log}" >&2
    tail -5 "$log" >&2
    fail=1
  fi
}

# xbmc <label> <prefix>: raw bmc3, no scorr, wall-time budget (informational).
xbmc () {
  local label="$1" p="$2" log="$2-xbmc.log"
  yosys-abc -c "read_aiger $p.aig; bmc3 -F 1000 -T $XBMC_TIME" >"$log" 2>&1
  local line; line="$(grep -E 'asserted|No output asserted' "$log" | tail -1)"
  if grep -q 'was asserted in frame' "$log"; then
    echo "$label: raw bmc3 found a counterexample (the property FAILS; record a finding, do NOT weaken the monitor): $line" >&2
    fail=1
  else
    echo "$label: raw bmc3 (informational, no scorr): ${line:-no verdict}"
  fi
}

# covers <label> <prefix> <depth>: z3 cover mode, every cover must be reached.
covers () {
  local label="$1" p="$2" depth="$3" log="$2-cover.log"
  if timeout "$Z3_TIMEOUT" yosys-smtbmc -s z3 -c -t "$depth" "$p.smt2" >"$log" 2>&1 \
     && grep -q 'Status: PASSED' "$log"; then
    echo "$label: all $(grep -c 'Reached cover statement' "$log") covers reached (max step $(grep -oE 'Reached cover statement in step [0-9]+' "$log" | grep -oE '[0-9]+$' | sort -n | tail -1))"
  else
    echo "$label: at least one cover UNREACHED (or solver failure) within $depth steps -- a pass may be vacuous" >&2
    grep -E 'Unreached|ERROR|Error' "$log" | head -5 >&2
    fail=1
  fi
}

# expect_cex <label> <prefix> <depth>: BOTH engines must produce a genuine
# assertion counterexample. Stale logs/traces are removed first, so a
# previous run cannot satisfy the check; a nonzero exit alone is not
# evidence (a crashed solver also exits nonzero).
expect_cex () {
  local label="$1" p="$2" depth="$3" alog="$2-abc-bmc.log" zlog="$2-z3-bmc.log" vcd="$2-cex.vcd"
  rm -f "$alog" "$zlog" "$vcd"
  yosys-abc -c "read_aiger $p.aig; bmc3 -F $depth" >"$alog" 2>&1
  local hit; hit="$(grep -oE 'Output [0-9]+ of miter .* was asserted in frame [0-9]+' "$alog" | head -1)"
  if [ -z "$hit" ]; then
    echo "$label: ABC found NO counterexample within $depth steps -- the checker missed this fault" >&2
    tail -3 "$alog" >&2
    fail=1
    return
  fi
  local idx frame; idx="$(echo "$hit" | sed -E 's/^Output ([0-9]+) .*/\1/')"; frame="${hit##* }"
  timeout "$Z3_TIMEOUT" yosys-smtbmc -s z3 -t "$depth" --dump-vcd "$vcd" "$p.smt2" >"$zlog" 2>&1
  if grep -q 'Assert failed in' "$zlog" && grep -q 'Status: FAILED' "$zlog" && [ -s "$vcd" ]; then
    local zstep; zstep="$(grep -oE 'Checking assertions in step [0-9]+' "$zlog" | tail -1 | grep -oE '[0-9]+$')"
    local zfirst; zfirst="$(grep -m1 'Assert failed in' "$zlog" | grep -oE '[A-Za-z0-9_]+\.s?v:[0-9]+' | head -1)"
    echo "$label: REJECTED -- ABC frame $frame ($(assert_name "$p.ywb" "$idx")); z3 step $zstep ($zfirst ...); VCD $(basename "$vcd")"
  else
    echo "$label: ABC counterexample NOT confirmed by z3 (no assertion failure / no trace) -- solver/tool problem, not evidence" >&2
    tail -3 "$zlog" >&2
    fail=1
  fi
}

# structural <core.v>: complementary, clock-model-free check that every bit
# of both output ports is the Q pin of a rising-edge flip-flop (async reset
# allowed) clocked by `clk`, with nothing between flop and port. This is
# what "registered output, not combinational passthrough" (DR 0001) means
# structurally; it says nothing about the flop's D input (the proofs do).
structural () {
  yosys -ql "$2" -p "read_verilog $1; hierarchy -top protocol_core; proc; opt_clean; simplemap; opt_clean -purge; select -set outq o:port_uo_out o:port_uio_out %u %ci1:+[Q] t:\$_DFF_P* t:\$_DFFE_P* %u %i; select -assert-count 16 @outq; select -assert-count 1 @outq %ci1:+[C] @outq %d; select -assert-count 1 @outq %ci1:+[C] @outq %d w:clk %i" 2>/dev/null
}

# ----------------------------------------------------------------- positive
echo
echo "== [0/6] structural: output ports are direct rising-edge flop outputs on clk =="
if structural "$CORE" "$ART_DIR/core-structural.log"; then
  echo "core: PASS (16/16 output bits are Q pins of rising-edge flops on clk, no logic in between)"
else
  echo "core: FAIL -- an output bit is not a direct rising-edge flop output; see core-structural.log" >&2
  fail=1
fi

echo "== [1/6] real core: elaboration (EDGE and FINE models) =="
elab "$CORE" edge "$ART_DIR/core-edge" || { echo "ERROR: EDGE elaboration failed" >&2; fail=1; }
elab "$CORE" fine "$ART_DIR/core-fine" || { echo "ERROR: FINE elaboration failed" >&2; fail=1; }
for p in core-edge core-fine; do
  [ -s "$ART_DIR/$p.aig" ] && echo "$p.aig header: $(head -c 64 "$ART_DIR/$p.aig" | head -1)"
done

echo "== [2/6] real core: proof (ABC scorr + pdr -a; expect every property PROVED) =="
prove "EDGE (A1/A2 once per cycle)" "$ART_DIR/core-edge"
prove "FINE (A1/A2 every sample + F1)" "$ART_DIR/core-fine"

echo "== [3/6] real core: scorr-independent bounded cross-check (informational, ${XBMC_TIME}s each) =="
xbmc "EDGE" "$ART_DIR/core-edge"
xbmc "FINE" "$ART_DIR/core-fine"

echo "== [4/6] real core: covers (non-vacuity, z3) =="
covers "EDGE covers" "$ART_DIR/core-edge" "$COVER_DEPTH_EDGE"
covers "FINE covers" "$ART_DIR/core-fine" "$COVER_DEPTH_FINE"

# ------------------------------------------------------------------ mutants
echo
echo "== [5/6] mutants of the real core (scratch copies; rtl/ is never edited) =="
MUT_DIR="$ART_DIR/mutants"
mkdir -p "$MUT_DIR"
if ! python3 -I "$MUTGEN" "$CORE" "$MUT_DIR" >"$MUT_DIR/generated.txt"; then
  echo "ERROR: mutant generation failed (an anchor no longer matches the core)" >&2
  fail=1
fi
# name:required-model -- the model on which the checker MUST reject it.
for spec in wrong_destination:edge wrong_value:edge readonly_port_writes:edge \
            wctl_writes_pin:edge rctl_wrong_value:edge pm_read_wrong_byte:edge \
            fetch_source_ignores_rom:edge run_does_not_leave_rom:edge \
            boot_status_bit1_wrong:edge rom_decode_split:edge \
            late_one_cycle:edge comb_early_visibility:edge \
            executes_in_priming_cycle:edge negedge_half_cycle_early:fine \
            load_phase_leak:edge; do
  m="${spec%%:*}"; model="${spec##*:}"; src="$MUT_DIR/protocol_core_$m.v"
  if [ ! -s "$src" ] || cmp -s "$CORE" "$src"; then
    echo "ERROR: mutant $m missing or identical to the core" >&2; fail=1; continue
  fi
  if ! elab "$src" "$model" "$MUT_DIR/$m-$model"; then
    echo "ERROR: mutant $m: elaboration failed" >&2; fail=1; continue
  fi
  if [ "$model" = fine ]; then depth="$MUT_DEPTH_FINE"; else depth="$MUT_DEPTH_EDGE"; fi
  expect_cex "$m [$model]" "$MUT_DIR/$m-$model" "$depth"
done

echo "-- structural check negative controls (must FAIL on the two mutants that break registration) --"
for m in comb_early_visibility negedge_half_cycle_early; do
  if structural "$MUT_DIR/protocol_core_$m.v" "$MUT_DIR/$m-structural.log"; then
    echo "structural check ACCEPTED mutant $m -- the check has no teeth" >&2; fail=1
  else
    echo "structural check rejects $m as required"
  fi
done

echo "== [6/6] observability control (informational): the half-cycle-early mutant on the EDGE model =="
# Expected to PASS on the edge model -- that is the point: a once-per-cycle
# model cannot distinguish a falling-edge output register from a rising-edge
# one, which is why the FINE model (and F1) exist. The outcome is recorded
# either way and does not affect the exit code.
if elab "$MUT_DIR/protocol_core_negedge_half_cycle_early.v" edge "$MUT_DIR/negedge_half_cycle_early-edge"; then
  yosys-abc -c "read_aiger $MUT_DIR/negedge_half_cycle_early-edge.aig; scorr; pdr -a -T $PDR_TIME" \
    >"$MUT_DIR/negedge_half_cycle_early-edge-proof.log" 2>&1
  echo "EDGE model on negedge_half_cycle_early: $(grep -E 'Properties: +All = ' "$MUT_DIR/negedge_half_cycle_early-edge-proof.log" | tail -1)"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "RESULT: all expectations met (EDGE+FINE proofs closed on the harness model, every cover reached, every mutant rejected by ABC and z3)"
else
  echo "RESULT: FAILED -- do not mint a record from this run" >&2
fi
exit "$fail"
