#!/usr/bin/env bash
#
# Cold-start runner for the SECOND, INDEPENDENT formal engine on
# `no_data_dependent_latency` (issue #529 step 1, target-spec row 3,
# characterization row 3).
#
# Why this engine is independent of the live record (`20261013-003554-0a242d7`):
#   The live record's unbounded proof rests on Berkeley ABC (`scorr; pdr -a` on
#   Yosys's AIGER export). This runner proves the EXACT SAME unrelaxed property
#   (`verification/formal/no_data_dependent_latency.sv`, byte-identical) and
#   harness (`verification/formal/formal_top.v`, byte-identical) on `rtl/protocol_core.v`
#   using `rIC3` (https://github.com/gipsyh/rIC3, Rust IC3/PDR/BMC model checker
#   backed by its own GipSAT / CaDiCaL / Kissat / Bitwuzla solvers and its own
#   Rust `scorr` / `frts` preprocessors -- zero Berkeley ABC code or reduction).
#
# Legs (every one is a hard exit condition):
#   [1/5] Unbounded per-property IC3 (`ric3 check ... multi-prop --no-parallel`)
#         on the Yosys AIGER export (`core.aig`): all 8 assertions must report UNSAT.
#   [2/5] Unbounded IC3 (`ric3 check ... ic3`) on a word-level BTOR2 export
#         (`core.btor2`, straight from Yosys `write_btor` -- bypassing Yosys
#         `aigmap`/`write_aiger` too): must report UNSAT.
#   [3/5] Bounded model check (`ric3 check ... bmc --end $BMC_DEPTH`, default 35,
#         refusing BMC_DEPTH < 30 so depth is never shallower than the live
#         record's depth 30): must reach bound $BMC_DEPTH with zero SAT.
#   [4/5]..[4c/5] Negative controls on the same three scratch-copy real-core
#         mutants as `run-no-data-dependent-latency.sh` (`rtl/` is never edited):
#           - WAIT stall cut to 1 cycle when ui_in == 0xA5
#           - 2-cycle control-space stall stretched while ui_in == 0xA5 (DR 0012)
#           - WCTL CRC_BYTE stall cut to 1 cycle when ui_in == 0xA5 (DR 0015)
#         Each must produce a genuine `SAT` + `IC3 found a counterexample` verdict
#         from `rIC3` (a tool crash or missing verdict fails the gate).
#
# Usage:
#   RIC3=/path/to/ric3 ./verification/formal/run-no-data-dependent-latency-second-engine.sh [artifacts-dir]

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT" || exit 1

ART_ARG="${1:-$REPO_ROOT/.loom/formal-scratch/no-data-dependent-latency-second-engine}"
mkdir -p "$ART_ARG"
ART_DIR="$(cd "$ART_ARG" && pwd)"

BMC_DEPTH="${BMC_DEPTH:-35}"
RIC3_BIN="${RIC3:-ric3}"
RIC3_TIME="${RIC3_TIME:-300}"
export RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-2}"
fail=0

if ! [[ "$BMC_DEPTH" =~ ^[0-9]+$ ]] || [ "$BMC_DEPTH" -lt 30 ]; then
  echo "ERROR: BMC_DEPTH ($BMC_DEPTH) must be an integer >= 30 (no shallower than the live record)" >&2
  exit 1
fi

command -v yosys >/dev/null 2>&1 || { echo "ERROR: yosys not found on PATH" >&2; exit 1; }
command -v "$RIC3_BIN" >/dev/null 2>&1 || { echo "ERROR: rIC3 binary ($RIC3_BIN) not found" >&2; exit 1; }

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
"$RIC3_BIN" --version

echo
echo "== input hashes (monitor must equal the live record's sha256) =="
sha256sum \
  verification/formal/no_data_dependent_latency.sv \
  verification/formal/formal_top.v \
  rtl/protocol_core.v

aig_core () {
  local out="$1" core="$2"
  yosys -ql "$out.yosys.log" -p "read_verilog -formal -sv $core; read_verilog -formal -sv -nomem2reg -D REAL_CORE verification/formal/no_data_dependent_latency.sv verification/formal/formal_top.v; hierarchy -top formal_top; proc; flatten; opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean; async2sync; dffunmap; setundef -anyseq; chformal -remove -cover; techmap; opt_clean; aigmap; opt_clean; write_aiger -zinit -ywmap ${out%.aig}.ywb $out" 2>"$out.yosys.stderr"
  local rc=$?
  sanitize_log "$out.yosys.log"
  sanitize_log "$out.yosys.stderr"
  [ "$rc" -eq 0 ] && [ -s "$out" ]
}

btor_core () {
  local out="$1" core="$2"
  yosys -ql "$out.yosys.log" -p "read_verilog -formal -sv $core; read_verilog -formal -sv -nomem2reg -D REAL_CORE verification/formal/no_data_dependent_latency.sv verification/formal/formal_top.v; hierarchy -top formal_top; proc; flatten; opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean; async2sync; dffunmap; chformal -remove -cover; setundef -anyseq; opt_clean; write_btor $out" 2>"$out.yosys.stderr"
  local rc=$?
  sanitize_log "$out.yosys.log"
  sanitize_log "$out.yosys.stderr"
  [ "$rc" -eq 0 ] && [ -s "$out" ]
}

ric3_expect_disproved () {
  local label="$1" model="$2" log="$3"
  rm -f "$log"
  "$RIC3_BIN" check --ui false "$model" ic3 --time-limit "$RIC3_TIME" >"$log" 2>&1
  local rc=$?
  sanitize_log "$log"
  if [ "$rc" -ne 0 ]; then
    echo "$label: solver/tool failure (rIC3 exited $rc -- not evidence of a counterexample)" >&2
    tail -5 "$log" >&2
    fail=1
  elif grep -q '^SAT$' "$log" && grep -q 'IC3 found a counterexample at depth' "$log"; then
    echo "$label: rIC3 DISPROVED mutant as required"
  elif grep -q '^UNSAT$' "$log"; then
    echo "$label: rIC3 reported UNSAT -- missed a data-dependent latency mutant" >&2
    fail=1
  else
    echo "$label: solver/tool failure -- no SAT counterexample verdict in log" >&2
    tail -5 "$log" >&2
    fail=1
  fi
}

echo "== [1/5] real core: AIGER export + rIC3 multi-prop unbounded proof (8 properties) =="
if aig_core "$ART_DIR/core.aig" rtl/protocol_core.v; then
  "$RIC3_BIN" check --ui false "$ART_DIR/core.aig" multi-prop --no-parallel --time-limit "$RIC3_TIME" >"$ART_DIR/core-ric3-multiprop.log" 2>&1
  rc=$?
  sanitize_log "$ART_DIR/core-ric3-multiprop.log"
  unsat_cnt="$(grep -c '^UNSAT$' "$ART_DIR/core-ric3-multiprop.log")"
  sat_cnt="$(grep -c '^SAT$' "$ART_DIR/core-ric3-multiprop.log")"
  unk_cnt="$(grep -c '^UNKNOWN$' "$ART_DIR/core-ric3-multiprop.log")"
  if [ "$rc" -eq 0 ] && [ "$unsat_cnt" -eq 8 ] && [ "$sat_cnt" -eq 0 ] && [ "$unk_cnt" -eq 0 ]; then
    echo "real core (AIGER multi-prop): rIC3 PROVED all 8 assertions UNBOUNDED"
  else
    echo "real core (AIGER multi-prop): expected 8 UNSAT, got rc=$rc unsat=$unsat_cnt sat=$sat_cnt unknown=$unk_cnt" >&2
    tail -10 "$ART_DIR/core-ric3-multiprop.log" >&2
    fail=1
  fi
else
  echo "real core: AIGER export failed" >&2
  fail=1
fi

echo "== [2/5] real core: word-level BTOR2 export + rIC3 IC3 unbounded proof =="
if btor_core "$ART_DIR/core.btor2" rtl/protocol_core.v; then
  sanitize_log "$ART_DIR/core.btor2"
  "$RIC3_BIN" check --ui false "$ART_DIR/core.btor2" ic3 --time-limit "$RIC3_TIME" >"$ART_DIR/core-ric3-btor2.log" 2>&1
  rc=$?
  sanitize_log "$ART_DIR/core-ric3-btor2.log"
  if [ "$rc" -eq 0 ] && grep -q '^UNSAT$' "$ART_DIR/core-ric3-btor2.log" && grep -q 'IC3 proved the property' "$ART_DIR/core-ric3-btor2.log"; then
    echo "real core (BTOR2 ic3): rIC3 PROVED all 8 assertions UNBOUNDED"
  else
    echo "real core (BTOR2 ic3): did not prove unbounded (rc=$rc)" >&2
    tail -10 "$ART_DIR/core-ric3-btor2.log" >&2
    fail=1
  fi
else
  echo "real core: BTOR2 export failed" >&2
  fail=1
fi

echo "== [3/5] real core: rIC3 BMC to depth $BMC_DEPTH (expect no counterexample) =="
"$RIC3_BIN" check --ui false "$ART_DIR/core.aig" bmc --end "$BMC_DEPTH" >"$ART_DIR/core-ric3-bmc.log" 2>&1
rc=$?
sanitize_log "$ART_DIR/core-ric3-bmc.log"
if [ "$rc" -eq 0 ] \
   && grep -q "BMC found no counterexample up to depth $BMC_DEPTH" "$ART_DIR/core-ric3-bmc.log" \
   && ! grep -q '^SAT$' "$ART_DIR/core-ric3-bmc.log"; then
  echo "real core (BMC): PASS through depth $BMC_DEPTH"
else
  echo "real core (BMC): failed at or before depth $BMC_DEPTH (rc=$rc)" >&2
  tail -10 "$ART_DIR/core-ric3-bmc.log" >&2
  fail=1
fi

echo "== [4/5] real-core WAIT mutant (WAIT stall cut to 1 cycle when ui_in == 0xA5): expect SAT =="
sed 's/wait_cnt <= imm8;/wait_cnt <= (port_ui_in == 8'"'"'hA5) ? 8'"'"'d1 : imm8;/' \
  rtl/protocol_core.v >"$ART_DIR/protocol_core_mutant.v"
changed="$(diff rtl/protocol_core.v "$ART_DIR/protocol_core_mutant.v" | grep -c '^>')"
if [ "$changed" -ne 1 ]; then
  echo "ERROR: core WAIT mutant substitution applied to $changed line(s), expected 1" >&2
  fail=1
elif aig_core "$ART_DIR/core-mutant.aig" "$ART_DIR/protocol_core_mutant.v"; then
  ric3_expect_disproved "core WAIT mutant" "$ART_DIR/core-mutant.aig" "$ART_DIR/core-mutant-ric3.log"
else
  echo "core WAIT mutant: AIGER export failed" >&2
  fail=1
fi

echo "== [4b/5] real-core control-space mutant (2-cycle access stalls while ui_in == 0xA5, DR 0012): expect SAT =="
sed -e 's/^          ctl_stall  <= 1'"'"'b0;$/          ctl_stall  <= (port_ui_in == 8'"'"'hA5);/' \
    -e 's/next_addr = stall_run ? rd_val : pc_next;/next_addr = (port_ui_in == 8'"'"'hA5) ? pc : (stall_run ? rd_val : pc_next);/' \
  rtl/protocol_core.v >"$ART_DIR/protocol_core_mutant_ctl.v"
changed="$(diff rtl/protocol_core.v "$ART_DIR/protocol_core_mutant_ctl.v" | grep -c '^>')"
if [ "$changed" -ne 2 ]; then
  echo "ERROR: core control-space mutant substitution applied to $changed line(s), expected 2" >&2
  fail=1
elif aig_core "$ART_DIR/core-mutant-ctl.aig" "$ART_DIR/protocol_core_mutant_ctl.v"; then
  ric3_expect_disproved "core control-space mutant" "$ART_DIR/core-mutant-ctl.aig" "$ART_DIR/core-mutant-ctl-ric3.log"
else
  echo "core control-space mutant: AIGER export failed" >&2
  fail=1
fi

echo "== [4c/5] real-core P1 mutant (WCTL CRC_BYTE stall cut to 1 cycle when ui_in == 0xA5, DR 0015): expect SAT =="
sed "s/wait_cnt <= 8'd8;/wait_cnt <= (port_ui_in == 8'hA5) ? 8'd1 : 8'd8;/" \
  rtl/protocol_core.v >"$ART_DIR/protocol_core_mutant_crcb.v"
changed="$(diff rtl/protocol_core.v "$ART_DIR/protocol_core_mutant_crcb.v" | grep -c '^>')"
if [ "$changed" -ne 1 ]; then
  echo "ERROR: core P1 mutant substitution applied to $changed line(s), expected 1" >&2
  fail=1
elif aig_core "$ART_DIR/core-mutant-crcb.aig" "$ART_DIR/protocol_core_mutant_crcb.v"; then
  ric3_expect_disproved "core P1 mutant" "$ART_DIR/core-mutant-crcb.aig" "$ART_DIR/core-mutant-crcb-ric3.log"
else
  echo "core P1 mutant: AIGER export failed" >&2
  fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "RESULT: all expectations met (rIC3 unbounded AIGER + BTOR2 proofs, BMC depth $BMC_DEPTH pass, and all 3 core mutants disproved)"
else
  echo "RESULT: FAILED -- do not mint a record from this run" >&2
fi
exit "$fail"
