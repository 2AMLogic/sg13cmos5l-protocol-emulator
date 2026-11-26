#!/usr/bin/env bash
#
# Cold-start runner: serial-load shift-in and load-to-run handoff
# (issue #529 step 2, target-spec row 3, characterization row 3).
#
# Binds the shipped `rtl/protocol_program_memory.v` (unmodified) in two
# complementary models (`verification/formal/formal_top_load.v` +
# `verification/formal/serial_load_latency.sv`):
#
#   [1/7] Standalone loader (`formal_top_load_seq`, 5 assertions):
#         - Z3 BMC to depth $SEQ_BMC_DEPTH (default 60) + covers (5 monitor covers);
#         - ABC `scorr; pdr -a` unbounded proof (5/5 proved);
#         - `rIC3` (`multi-prop --no-parallel`) independent unbounded proof
#           (5/5 proved; required when `REQUIRE_RIC3=1` or `RIC3` is present).
#
#   [2/7] Integrated loader + 8-word aliased synchronous SRAM + shipped
#         `rtl/protocol_core.v` (`-D INTEGRATED_LOAD`, `formal_top_load`):
#         replaces `formal_top.v`'s constant-table / `free_serial_loaded`
#         abstraction with the real shift-in path and checks BOTH the
#         byte-identical `no_data_dependent_latency.sv` (8 assertions) AND
#         `serial_load_latency` (5 assertions: `run_phase`, `exec_phase`
#         +1-cycle priming, `serial_loaded`, `pm_crc`, and Wolper symbolic-slot
#         shifted-word fetch `instr_word == obs_word`):
#         - Z3 BMC to depth $INT_BMC_DEPTH (default 14) + all 14 covers to
#           depth $INT_COV_DEPTH (default 40);
#         - ABC `scorr; pdr -a` unbounded proof of all 13 assertions;
#         - `rIC3` (`ic3` on `-D INTEGRATED_LOAD -D CORE_PROP_ONLY`) independent
#           unbounded proof of all 8 `no_data_dependent_latency` assertions over
#           the real shift-in + 8-word SRAM + core transition system.
#
#   [3/7]..[5/7] Three scratch-copy loader mutants (`rtl/` is never edited):
#         - `exit`: load exit delayed while `serial_in` is high;
#         - `bit`:  intra-word shift/bit-counter stall when `serial_in` is high
#                   at `bit_cnt == 4'd7`;
#         - `addr`: commit write-address stalls when `load_word == 16'hA5A5`.
#         Every mutant must be disproved by Z3 BMC, by ABC PDR, and (when
#         present/required) by `rIC3`; a tool crash fails the gate.
#   [6/7] Integrated exit-stall mutant, checked with ABC and optionally rIC3.
#   [7/7] Replay 256 complete words followed by excess bits on the standalone
#         harness. Suppressing only the final SRAM write must fail serial_commit.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT" || exit 1

ART_ARG="${1:-$REPO_ROOT/.loom/formal-scratch/serial-load-shift-in}"
mkdir -p "$ART_ARG"
ART_DIR="$(cd "$ART_ARG" && pwd)"

SEQ_BMC_DEPTH="${SEQ_BMC_DEPTH:-60}"
INT_BMC_DEPTH="${INT_BMC_DEPTH:-14}"
INT_COV_DEPTH="${INT_COV_DEPTH:-40}"
PDR_TIME="${PDR_TIME:-300}"
MUT_PDR_TIME="${MUT_PDR_TIME:-30}"
RIC3_TIME="${RIC3_TIME:-300}"
RIC3_BIN="${RIC3:-ric3}"
REQUIRE_RIC3="${REQUIRE_RIC3:-0}"
export RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-2}"
fail=0

for t in yosys yosys-smtbmc yosys-abc z3; do
  command -v "$t" >/dev/null 2>&1 || { echo "ERROR: $t not found on PATH" >&2; exit 1; }
done

HAVE_RIC3=0
if command -v "$RIC3_BIN" >/dev/null 2>&1; then
  HAVE_RIC3=1
elif [ "$REQUIRE_RIC3" = "1" ]; then
  echo "ERROR: REQUIRE_RIC3=1, but rIC3 binary ($RIC3_BIN) was not found" >&2
  exit 1
fi

sanitize_log () {
  local f="$1"
  [ -f "$f" ] || return 0
  sed -i \
    -e "s|$ART_DIR/|<art>/|g" \
    -e "s|$REPO_ROOT/||g" \
    "$f"
}

echo "== toolchain =="
yosys -V
z3 --version
yosys-smtbmc --help 2>&1 | head -1
if [ "$HAVE_RIC3" -eq 1 ]; then "$RIC3_BIN" --version; fi

echo
echo "== input hashes (no_data_dependent_latency.sv stays byte-identical) =="
sha256sum \
  verification/formal/no_data_dependent_latency.sv \
  verification/formal/serial_load_latency.sv \
  verification/formal/formal_top_load.v \
  rtl/protocol_program_memory.v \
  rtl/protocol_core.v

elab_seq_smt2 () {
  local out="$1" mem_v="$2"
  yosys -ql "$out.log" -p "read_verilog -formal -sv $mem_v verification/formal/serial_load_latency.sv verification/formal/formal_top_load.v; hierarchy -top formal_top_load_seq; proc; flatten; opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean; async2sync; dffunmap; write_smt2 -wires $out"
  local rc=$?
  sanitize_log "$out.log"
  [ "$rc" -eq 0 ] && [ -s "$out" ]
}

elab_seq_aig () {
  local out="$1" mem_v="$2"
  yosys -ql "$out.yosys.log" -p "read_verilog -formal -sv $mem_v verification/formal/serial_load_latency.sv verification/formal/formal_top_load.v; hierarchy -top formal_top_load_seq; proc; flatten; opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean; async2sync; dffunmap; setundef -anyseq; chformal -remove -cover; techmap; opt_clean; aigmap; opt_clean; write_aiger -zinit -ywmap ${out%.aig}.ywb $out" 2>"$out.yosys.stderr"
  local rc=$?
  sanitize_log "$out.yosys.log"
  sanitize_log "$out.yosys.stderr"
  [ "$rc" -eq 0 ] && [ -s "$out" ]
}

elab_int_smt2 () {
  local out="$1" mem_v="$2"
  yosys -ql "$out.log" -p "read_verilog -formal -sv rtl/protocol_core.v $mem_v; read_verilog -formal -sv -nomem2reg -D INTEGRATED_LOAD verification/formal/no_data_dependent_latency.sv verification/formal/serial_load_latency.sv verification/formal/formal_top_load.v; hierarchy -top formal_top_load; proc; flatten; opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean; async2sync; dffunmap; write_smt2 -wires $out"
  local rc=$?
  sanitize_log "$out.log"
  [ "$rc" -eq 0 ] && [ -s "$out" ]
}

elab_int_aig () {
  local out="$1" mem_v="$2" extra_def="${3:-}"
  yosys -ql "$out.yosys.log" -p "read_verilog -formal -sv rtl/protocol_core.v $mem_v; read_verilog -formal -sv -nomem2reg -D INTEGRATED_LOAD $extra_def verification/formal/no_data_dependent_latency.sv verification/formal/serial_load_latency.sv verification/formal/formal_top_load.v; hierarchy -top formal_top_load; proc; flatten; opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean; async2sync; dffunmap; setundef -anyseq; chformal -remove -cover; techmap; opt_clean; aigmap; opt_clean; write_aiger -zinit -ywmap ${out%.aig}.ywb $out" 2>"$out.yosys.stderr"
  local rc=$?
  sanitize_log "$out.yosys.log"
  sanitize_log "$out.yosys.stderr"
  [ "$rc" -eq 0 ] && [ -s "$out" ]
}

pdr_summary () {
  local aig="$1" log="$2" tlim="${3:-$PDR_TIME}" line
  yosys-abc -c "read_aiger $aig; scorr; pdr -a -T $tlim" >"$log" 2>&1
  local rc=$?
  sanitize_log "$log"
  [ "$rc" -eq 0 ] || { echo "-1 0 0 0"; return; }
  line="$(grep -E 'Properties: +All = ' "$log" | tail -1)"
  [ -n "$line" ] || { echo "-1 0 0 0"; return; }
  echo "$line" | sed -E 's/.*All = ([0-9]+)\. Proved = ([0-9]+)\. Disproved = ([0-9]+)\. Undecided = ([0-9]+).*/\1 \2 \3 \4/'
}

pdr_expect_proved () {
  local label="$1" aig="$2" want_all="$3" all proved disproved undecided
  read -r all proved disproved undecided <<<"$(pdr_summary "$aig" "${aig%.aig}-pdr.log" "$PDR_TIME")"
  if [ "$all" -eq "$want_all" ] && [ "$proved" -eq "$want_all" ] && [ "$disproved" -eq 0 ] && [ "$undecided" -eq 0 ]; then
    echo "$label: ABC PDR PROVED all $all assertions UNBOUNDED"
  else
    echo "$label: ABC PDR did not prove all $want_all assertions (all=$all proved=$proved disproved=$disproved undecided=$undecided)" >&2
    fail=1
  fi
}

pdr_expect_disproved () {
  local label="$1" aig="$2" all proved disproved undecided
  read -r all proved disproved undecided <<<"$(pdr_summary "$aig" "${aig%.aig}-pdr.log" "$MUT_PDR_TIME")"
  if [ "$all" -lt 0 ]; then
    echo "$label: solver/tool failure in ABC PDR (not evidence of a counterexample)" >&2
    fail=1
  elif [ "$disproved" -ge 1 ]; then
    echo "$label: ABC PDR disproved $disproved of $all assertions as required"
  else
    echo "$label: ABC PDR disproved nothing (all=$all proved=$proved undecided=$undecided)" >&2
    fail=1
  fi
}

expect_cex () {
  local label="$1" smt2="$2" vcd="$3" depth="$4" log="${2%.smt2}-bmc.log"
  rm -f "$vcd" "$log"
  if yosys-smtbmc -s z3 -t "$depth" --dump-vcd "$vcd" "$smt2" >"$log" 2>&1; then
    sanitize_log "$log"
    echo "$label: NO counterexample -- property missed a data-dependent load stall" >&2
    fail=1
  else
    sanitize_log "$log"
    if grep -q 'Assert failed in' "$log" && grep -q 'BMC failed!' "$log" && [ -s "$vcd" ]; then
      echo "$label: Z3 BMC counterexample found as required"
    else
      echo "$label: solver/tool failure in Z3 BMC -- no assertion counterexample/VCD" >&2
      tail -5 "$log" >&2
      fail=1
    fi
  fi
}

ric3_expect_disproved () {
  local label="$1" aig="$2" log="${2%.aig}-ric3.log"
  rm -f "$log"
  "$RIC3_BIN" check --ui false "$aig" ic3 --time-limit "$RIC3_TIME" >"$log" 2>&1
  local rc=$?
  sanitize_log "$log"
  if [ "$rc" -ne 0 ]; then
    echo "$label: solver/tool failure in rIC3 (rc=$rc)" >&2
    fail=1
  elif grep -q '^SAT$' "$log" && grep -q 'IC3 found a counterexample at depth' "$log"; then
    echo "$label: rIC3 disproved mutant as required"
  else
    echo "$label: rIC3 failed to disprove mutant" >&2
    tail -5 "$log" >&2
    fail=1
  fi
}

echo
echo "== [1/7] standalone loader (formal_top_load_seq): BMC depth $SEQ_BMC_DEPTH + covers + ABC PDR + rIC3 =="
if elab_seq_smt2 "$ART_DIR/load-seq.smt2" rtl/protocol_program_memory.v; then
  sanitize_log "$ART_DIR/load-seq.smt2"
  if yosys-smtbmc -s z3 -t "$SEQ_BMC_DEPTH" "$ART_DIR/load-seq.smt2" >"$ART_DIR/load-seq-bmc.log" 2>&1; then
    sanitize_log "$ART_DIR/load-seq-bmc.log"
    echo "standalone loader BMC: PASS (depth $SEQ_BMC_DEPTH)"
  else
    sanitize_log "$ART_DIR/load-seq-bmc.log"
    echo "standalone loader BMC: FAILED" >&2
    tail -5 "$ART_DIR/load-seq-bmc.log" >&2
    fail=1
  fi
  if yosys-smtbmc -s z3 -c -t "$SEQ_BMC_DEPTH" "$ART_DIR/load-seq.smt2" >"$ART_DIR/load-seq-cover.log" 2>&1; then
    sanitize_log "$ART_DIR/load-seq-cover.log"
    echo "standalone loader covers: all reachable"
  else
    sanitize_log "$ART_DIR/load-seq-cover.log"
    echo "standalone loader covers: at least one cover unreachable" >&2
    tail -5 "$ART_DIR/load-seq-cover.log" >&2
    fail=1
  fi
else
  echo "standalone loader SMT2 elaboration failed" >&2
  fail=1
fi

if elab_seq_aig "$ART_DIR/load-seq.aig" rtl/protocol_program_memory.v; then
  pdr_expect_proved "standalone loader" "$ART_DIR/load-seq.aig" 5
  if [ "$HAVE_RIC3" -eq 1 ]; then
    "$RIC3_BIN" check --ui false "$ART_DIR/load-seq.aig" multi-prop --no-parallel --time-limit "$RIC3_TIME" >"$ART_DIR/load-seq-ric3.log" 2>&1
    rc=$?
    sanitize_log "$ART_DIR/load-seq-ric3.log"
    unsat_cnt="$(grep -c '^UNSAT$' "$ART_DIR/load-seq-ric3.log")"
    if [ "$rc" -eq 0 ] && [ "$unsat_cnt" -eq 5 ] && ! grep -qE '^(SAT|UNKNOWN)$' "$ART_DIR/load-seq-ric3.log"; then
      echo "standalone loader: rIC3 PROVED all 5 assertions UNBOUNDED"
    else
      echo "standalone loader: rIC3 did not prove all 5 assertions (rc=$rc unsat=$unsat_cnt)" >&2
      fail=1
    fi
  fi
else
  echo "standalone loader AIGER export failed" >&2
  fail=1
fi

echo
echo "== [2/7] integrated loader + 8-word SRAM + core (formal_top_load): BMC + 14 covers + ABC PDR (13/13) + rIC3 =="
if elab_int_smt2 "$ART_DIR/load-integrated.smt2" rtl/protocol_program_memory.v; then
  sanitize_log "$ART_DIR/load-integrated.smt2"
  if yosys-smtbmc -s z3 -t "$INT_BMC_DEPTH" "$ART_DIR/load-integrated.smt2" >"$ART_DIR/load-integrated-bmc.log" 2>&1; then
    sanitize_log "$ART_DIR/load-integrated-bmc.log"
    echo "integrated loader+core BMC: PASS (depth $INT_BMC_DEPTH)"
  else
    sanitize_log "$ART_DIR/load-integrated-bmc.log"
    echo "integrated loader+core BMC: FAILED" >&2
    tail -5 "$ART_DIR/load-integrated-bmc.log" >&2
    fail=1
  fi
  if yosys-smtbmc -s z3 -c -t "$INT_COV_DEPTH" --dump-vcd "$ART_DIR/load-integrated-cover%.vcd" "$ART_DIR/load-integrated.smt2" >"$ART_DIR/load-integrated-cover.log" 2>&1; then
    sanitize_log "$ART_DIR/load-integrated-cover.log"
    echo "integrated loader+core covers: all reachable (depth $INT_COV_DEPTH)"
  else
    sanitize_log "$ART_DIR/load-integrated-cover.log"
    echo "integrated loader+core covers: at least one cover unreachable" >&2
    tail -5 "$ART_DIR/load-integrated-cover.log" >&2
    fail=1
  fi
else
  echo "integrated loader+core SMT2 elaboration failed" >&2
  fail=1
fi

if elab_int_aig "$ART_DIR/load-integrated.aig" rtl/protocol_program_memory.v; then
  pdr_expect_proved "integrated loader+core (8 core + 5 load assertions)" "$ART_DIR/load-integrated.aig" 13
else
  echo "integrated loader+core AIGER export failed" >&2
  fail=1
fi

if [ "$HAVE_RIC3" -eq 1 ]; then
  if elab_int_aig "$ART_DIR/load-integrated-coreprop.aig" rtl/protocol_program_memory.v "-D CORE_PROP_ONLY"; then
    "$RIC3_BIN" check --ui false "$ART_DIR/load-integrated-coreprop.aig" ic3 --time-limit "$RIC3_TIME" >"$ART_DIR/load-integrated-coreprop-ric3.log" 2>&1
    rc=$?
    sanitize_log "$ART_DIR/load-integrated-coreprop-ric3.log"
    if [ "$rc" -eq 0 ] && grep -q '^UNSAT$' "$ART_DIR/load-integrated-coreprop-ric3.log" && grep -q 'IC3 proved the property' "$ART_DIR/load-integrated-coreprop-ric3.log"; then
      echo "integrated loader+core (no_data_dependent_latency): rIC3 PROVED all 8 assertions UNBOUNDED"
    else
      echo "integrated loader+core (no_data_dependent_latency): rIC3 did not prove unbounded (rc=$rc)" >&2
      fail=1
    fi
  else
    echo "integrated loader+core CORE_PROP_ONLY AIGER export failed" >&2
    fail=1
  fi
fi

run_mutant () {
  local label="$1" tag="$2" expr="$3" want="$4"
  local mut_v="$ART_DIR/protocol_program_memory_mut_${tag}.v" n
  sed "$expr" rtl/protocol_program_memory.v >"$mut_v"
  n="$(diff rtl/protocol_program_memory.v "$mut_v" | grep -c '^>')"
  if [ "$n" -ne "$want" ]; then
    echo "ERROR: $label substitution applied to $n line(s), expected $want" >&2
    fail=1
    return
  fi
  if elab_seq_smt2 "$ART_DIR/mut-$tag.smt2" "$mut_v"; then
    expect_cex "$label" "$ART_DIR/mut-$tag.smt2" "$ART_DIR/mut-$tag-cex.vcd" "$SEQ_BMC_DEPTH"
  else
    echo "$label: SMT2 elaboration failed" >&2
    fail=1
  fi
  if elab_seq_aig "$ART_DIR/mut-$tag.aig" "$mut_v"; then
    pdr_expect_disproved "$label" "$ART_DIR/mut-$tag.aig"
    if [ "$HAVE_RIC3" -eq 1 ]; then
      ric3_expect_disproved "$label" "$ART_DIR/mut-$tag.aig"
    fi
  else
    echo "$label: AIGER export failed" >&2
    fail=1
  fi
}

echo
echo "== [3/7] loader mutant exit-stall (load exit delayed while serial_in is high) =="
run_mutant "mutant exit-stall" exit \
  's/^        if (!mode_pin) begin$/        if (!mode_pin \&\& !serial_in) begin/' 1

echo "== [4/7] loader mutant bit-stall (intra-word shift stalls at bit 7 when serial_in is high) =="
run_mutant "mutant bit-stall" bit \
  's/^            bit_cnt <= bit_cnt + 4'"'"'d1;$/            bit_cnt <= (bit_cnt == 4'"'"'d7 \&\& serial_in) ? bit_cnt : (bit_cnt + 4'"'"'d1);/' 1

echo "== [5/7] loader mutant addr-stall (commit write-address stalls when load_word == 0xA5A5) =="
run_mutant "mutant addr-stall" addr \
  's/^                wr_addr <= wr_addr + 8'"'"'d1;$/                wr_addr <= (load_word == 16'"'"'hA5A5) ? wr_addr : (wr_addr + 8'"'"'d1);/' 1

echo "== [6/7] integrated end-to-end mutant check (loader exit-stall disproved via integrated model) =="
if elab_int_aig "$ART_DIR/mut-int-exit.aig" "$ART_DIR/protocol_program_memory_mut_exit.v"; then
  pdr_expect_disproved "integrated mutant exit-stall" "$ART_DIR/mut-int-exit.aig"
  if [ "$HAVE_RIC3" -eq 1 ]; then
    ric3_expect_disproved "integrated mutant exit-stall" "$ART_DIR/mut-int-exit.aig"
  fi
else
  echo "integrated mutant exit-stall: AIGER export failed" >&2
  fail=1
fi

echo "== [7/7] last-word write at the SRAM pins =="
# A directed trace reaches the 4096th serial bit cheaply. Constants below
# apply only to this replay. The unbounded proofs use free loader inputs.
replay_full_load () {
  local mem_v="$1" log="$2"
  yosys -Q -T -q -p "
    read_verilog -formal -sv $mem_v verification/formal/serial_load_latency.sv verification/formal/formal_top_load.v
    prep -top formal_top_load_seq -flatten
    cd formal_top_load_seq
    delete -input w:mode_pin w:serial_in
    connect -set mode_pin 1
    connect -set serial_in 1
    chformal -cover -remove
    async2sync
    chformal -lower
    sim -q -clock clk -n 4116 -assert
  " >"$log" 2>&1
}

final_mut="$ART_DIR/protocol_program_memory_mut_final.v"
sed "s/\.A_WEN      (mem_wen_pin)/.A_WEN      (mem_wen_pin \&\& !(load_active \&\& wr_addr == 8'hff \&\& serial_in))/" \
  rtl/protocol_program_memory.v >"$final_mut"
if [ "$(diff rtl/protocol_program_memory.v "$final_mut" | grep -c '^>')" -ne 1 ]; then
  echo "ERROR: final-write substitution must change exactly one line" >&2
  fail=1
elif ! replay_full_load rtl/protocol_program_memory.v "$ART_DIR/full-load.log"; then
  echo "Unmodified loader failed the 256-word replay" >&2
  fail=1
elif replay_full_load "$final_mut" "$ART_DIR/mut-final.log" ||
     ! grep -Eq '^ERROR: Assertion formal_top_load_seq\.mon\.serial_commit .* failed\.$' "$ART_DIR/mut-final.log"; then
  echo "Missing serial_commit failure on the final-write mutant" >&2
  fail=1
else
  echo "Final-write replay: original passed through saturation; suppressed SRAM write failed serial_commit"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "RESULT: all expectations met (standalone + integrated shift-in proofs closed, covers reached, all loader mutants disproved)"
else
  echo "RESULT: FAILED -- do not mint a record from this run" >&2
fi
exit "$fail"
