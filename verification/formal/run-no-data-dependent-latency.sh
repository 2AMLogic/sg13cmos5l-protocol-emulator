#!/usr/bin/env bash
#
# Cold-start runner for the formal property `no_data_dependent_latency`
# (spec/verification-plan.md section 2.1, target-spec row 3, issue #24).
#
# Proves the property against the conformant timing-contract fixture
# (bounded model check, no assumptions on program contents or data
# inputs), checks the cover (non-vacuity) set, attempts unbounded
# k-induction (recorded honestly -- see the property header for why it is
# not expected to close against a port-only monitor), and then proves the
# property HAS TEETH by showing it fails against the data-dependent
# early-out mutant fixture.
#
# Second DUT binding (issue #90): after the fixture legs, the SAME unmodified
# monitor is run against the shipped core rtl/protocol_core.v (legs
# [5/8]..[8/8]): BMC, covers, k-induction (informational), and a mutant of
# the real core (a data-dependent WAIT early-out injected by a checked text
# substitution into a scratch COPY -- rtl/ is never edited). Select with
# DUT=fixture|core|all (default all). See formal_top.v's REAL_CORE block for
# the binding (registered-read program model, pc/run_phase mapping).
#
# Control space (issue #135, DR 0012): the monitor's latency table now
# carries the three 2-cycle control accesses, so each binding gains a second
# negative control for exactly those rows -- leg [4b/4], a fixture whose
# 2-cycle control access skips its stall on a data match
# (fixtures/timing_contract_mutant_ctl.v), and leg [8b/8], the real core with
# its control stall stretched while ui_in == 0xA5. The original WAIT mutants
# (legs [4/4] and [8/8]) are unchanged.
#
# Cold start (a third party with a fresh clone needs exactly this):
#
#   ./verification/formal/run-no-data-dependent-latency.sh [artifacts-dir]
#
# Requirements on $PATH: yosys (with write_smt2 support), yosys-smtbmc,
# and z3 -- the same Homebrew/pip Yosys distribution this repo's other
# flows already use (see docs/environment.md; the exact versions used for
# the record of this harness are frozen in the record's artifacts). No
# PDK, netlist, or klt dependency: this is a pure RTL-level formal check,
# so the record's provenance cites pdk "n/a" per verification/README.md.
#
# Exit codes: 0 = all expectations met (BMC pass, all covers reachable,
# induction result recorded either way, mutant counterexample found);
# 1 = an expectation was violated (do not ship a record from such a run).

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

ART_DIR="${1:-$REPO_ROOT/.loom/formal-scratch/no-data-dependent-latency}"
mkdir -p "$ART_DIR"

# Default depth 30: measured feasibility for z3 on this transition system
# (~2.5 min at depth 30; growth past ~depth 35 is superlinear and blows past
# any sane budget -- no faster SMT solver is installable on this host, and
# temporal induction cannot close against a port-only monitor; see the
# property header). Depth 30 covers, for every free program and free data
# input: run-phase entry, every opcode class, full WAIT immediates (a
# WAIT 255's first ~28 stall cycles are checked; stalls to completion are
# covered for imm <= ~26 via cover c1), and branch/HALT behavior. Override
# with BMC_DEPTH=<n> if a faster solver is available.
BMC_DEPTH="${BMC_DEPTH:-30}"

DUT="${DUT:-all}"
fail=0

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: $1 not found on PATH" >&2; exit 1; }; }
need yosys
need yosys-smtbmc
need z3

case "$DUT" in fixture|core|all) ;; *) echo "ERROR: DUT must be fixture|core|all" >&2; exit 1;; esac
echo "== toolchain =="
yosys -V
z3 --version
yosys-smtbmc --help 2>&1 | head -1   # no --version flag; it ships with the yosys distribution above

# expect_cex <label> <model.smt2> <cex.vcd>: run BMC on a negative-control
# model and accept it ONLY if it produced a genuine assertion counterexample.
# A nonzero exit alone is not evidence -- a crashed/missing solver or a
# malformed model also exits nonzero -- so the log must carry smtbmc's
# assertion-failure markers and a fresh trace must exist. Stale trace and log
# are removed first so a previous run cannot satisfy the check.
expect_cex () {
  local label="$1" smt2="$2" vcd="$3" log="${2%.smt2}-bmc.log"
  rm -f "$vcd" "$log"
  if yosys-smtbmc -s z3 -t "$BMC_DEPTH" --dump-vcd "$vcd" "$smt2" >"$log" 2>&1; then
    echo "$label: NO counterexample -- the property failed to catch a data-dependent latency; it is vacuous or wrong" >&2
    fail=1
  elif grep -q 'Assert failed in' "$log" && grep -q 'BMC failed!' "$log" && [ -s "$vcd" ]; then
    echo "$label: counterexample found as required; VCD: $vcd"
  else
    echo "$label: solver/tool failure -- no assertion counterexample in the log and/or no fresh trace (not evidence the property has teeth)" >&2
    tail -5 "$log" >&2
    fail=1
  fi
}

SOURCES_CONFORMANT="\
$SCRIPT_DIR/fixtures/timing_contract_conformant.v \
$SCRIPT_DIR/no_data_dependent_latency.sv \
$SCRIPT_DIR/formal_top.v"

SOURCES_MUTANT="\
$SCRIPT_DIR/fixtures/timing_contract_mutant.v \
$SCRIPT_DIR/no_data_dependent_latency.sv \
$SCRIPT_DIR/formal_top.v"

run_elab () { # $1 = out.smt2, $2.. = sources, with an optional -D MUTANT flag
  local out="$1"; shift
  # The elaboration sequence below is load-bearing in three ways, each
  # verified against this exact design (bisected by diffing the elaborated
  # RTLIL and by the runner's own positive/negative controls):
  #
  # 1. The explicit opt sub-pass sequence (never a bare `opt`): on this
  #    design, bare `opt` after `flatten` replaces the live table-latency
  #    cone (u_property.tbl_lat and its uses) with 9'x constants -- an
  #    encoding in which write_smt2 exposes those bits as free -- which
  #    manifests as instant bogus counterexamples on the conformant fixture.
  # 2. -nomem2reg plus NO `memory` pass: the program memory must reach
  #    write_smt2 as a real $mem cell so it is modeled as an SMT array whose
  #    INITIAL CONTENTS ARE FREE -- the proof quantifies over every possible
  #    program. (The frontend's automatic mem2reg flattens it to registers
  #    that default to a zero-initialized all-NOP program -- a model that
  #    trivially passes and catches nothing; and running `memory -nomap`
  #    before write_smt2 on this design reintroduces the 9'x bug of item 1.)
  # 3. async2sync/dffunmap: required by write_smt2 for async-reset FFs, and
  #    exact in this harness because rst_n_r is itself a clocked register
  #    (reset changes are clock-synchronized).
  yosys -ql "$out.log" -p "read_verilog -formal -sv -nomem2reg $*; hierarchy -top formal_top; proc; flatten; opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean; async2sync; dffunmap; write_smt2 -wires $out"
}

if [ "$DUT" != core ]; then
# ---------------------------------------------------------------- conformant
echo
echo "== [1/4] conformant fixture: elaboration =="
run_elab "$ART_DIR/conformant.smt2" $SOURCES_CONFORMANT || fail=1

echo "== [2/4] conformant fixture: BMC depth $BMC_DEPTH (expect PASS) =="
if yosys-smtbmc -s z3 -t "$BMC_DEPTH" "$ART_DIR/conformant.smt2" >"$ART_DIR/conformant-bmc.log" 2>&1; then
  echo "BMC: PASS (no counterexample within $BMC_DEPTH cycles)"
else
  echo "BMC: UNEXPECTED CEX -- property fails on the conformant model (false positive)" >&2
  tail -5 "$ART_DIR/conformant-bmc.log" >&2
  fail=1
fi

echo "== [3/4] conformant fixture: covers (non-vacuity) =="
if yosys-smtbmc -s z3 -c -t "$BMC_DEPTH" "$ART_DIR/conformant.smt2" >"$ART_DIR/conformant-cover.log" 2>&1; then
  echo "covers: all reachable (assertions genuinely exercised)"
else
  echo "covers: at least one cover unreachable -- treat the BMC pass as possibly vacuous" >&2
  tail -5 "$ART_DIR/conformant-cover.log" >&2
  fail=1
fi

echo "== [3b/4] conformant fixture: k-induction attempt (informational) =="
# Not expected to close against a port-only monitor (arbitrary induction
# start states can desynchronize the countdown shadow from the DUT); the
# outcome is recorded either way. See the property header.
if yosys-smtbmc -s z3 -i "$ART_DIR/conformant.smt2" >"$ART_DIR/conformant-induction.log" 2>&1; then
  echo "induction: CLOSED (unbounded proof)"
else
  echo "induction: did not close (expected as shipped; bounded result above is the shipped guarantee)"
fi

# --------------------------------------------------------------------- mutant
echo
echo "== [4/4] mutant fixture (data-dependent WAIT early-out): BMC depth $BMC_DEPTH (expect CEX) =="
run_elab "$ART_DIR/mutant.smt2" -D MUTANT $SOURCES_MUTANT || fail=1
expect_cex "mutant" "$ART_DIR/mutant.smt2" "$ART_DIR/mutant-cex.vcd"

echo
echo "== [4b/4] control-space mutant fixture (data-dependent 2-cycle-access early-out, DR 0012): BMC depth $BMC_DEPTH (expect CEX) =="
run_elab "$ART_DIR/mutant-ctl.smt2" -D MUTANT_CTL \
  "$SCRIPT_DIR/fixtures/timing_contract_mutant_ctl.v" \
  "$SCRIPT_DIR/no_data_dependent_latency.sv" \
  "$SCRIPT_DIR/formal_top.v" || fail=1
expect_cex "control-space mutant" "$ART_DIR/mutant-ctl.smt2" "$ART_DIR/mutant-ctl-cex.vcd"

fi  # fixture legs

if [ "$DUT" != fixture ]; then
# ------------------------------------------------------------------ real core
# The core is read WITHOUT -nomem2reg: its `regs` array has async-reset
# writes, which yosys rejects as a memory (`Async reset causes memory write`);
# mem2reg turns it into 4 reset-to-zero registers, which is exactly its RTL
# semantics. The program is NOT a memory here (formal_top's anyconst table),
# so the free-program argument above is unaffected.
run_elab_core () { # $1 = out.smt2, $2 = core .v
  local out="$1" core="$2"
  yosys -ql "$out.log" -p "read_verilog -formal -sv $core; read_verilog -formal -sv -nomem2reg -D REAL_CORE $SCRIPT_DIR/no_data_dependent_latency.sv $SCRIPT_DIR/formal_top.v; hierarchy -top formal_top; proc; flatten; opt_expr; opt_merge; opt_muxtree; opt_reduce; opt_merge; opt_dff; opt_clean; async2sync; dffunmap; write_smt2 -wires $out"
}

echo
echo "== monitor hash (must equal the fixture-run hash of record) =="
sha256sum "$SCRIPT_DIR/no_data_dependent_latency.sv" "$REPO_ROOT/rtl/protocol_core.v"

echo "== [5/8] real core rtl/protocol_core.v: elaboration =="
run_elab_core "$ART_DIR/core.smt2" "$REPO_ROOT/rtl/protocol_core.v" || fail=1

echo "== [6/8] real core: BMC depth $BMC_DEPTH (expect PASS) =="
if yosys-smtbmc -s z3 -t "$BMC_DEPTH" "$ART_DIR/core.smt2" >"$ART_DIR/core-bmc.log" 2>&1; then
  echo "BMC: PASS (no counterexample within $BMC_DEPTH cycles)"
else
  echo "BMC: CEX on the real core -- the property FAILS; record a finding, do NOT weaken the property" >&2
  tail -5 "$ART_DIR/core-bmc.log" >&2
  fail=1
fi

echo "== [7/8] real core: covers (non-vacuity) =="
if yosys-smtbmc -s z3 -c -t "$BMC_DEPTH" "$ART_DIR/core.smt2" >"$ART_DIR/core-cover.log" 2>&1; then
  echo "covers: all reachable"
else
  echo "covers: at least one cover unreachable -- BMC pass possibly vacuous" >&2
  tail -5 "$ART_DIR/core-cover.log" >&2
  fail=1
fi

echo "== [7b/8] real core: k-induction attempt (informational) =="
if yosys-smtbmc -s z3 -i "$ART_DIR/core.smt2" >"$ART_DIR/core-induction.log" 2>&1; then
  echo "induction: CLOSED (unbounded proof)"
else
  echo "induction: did not close (bounded result above is the shipped guarantee)"
fi

echo "== [8/8] real-core mutant (WAIT stall cut to 1 cycle when ui_in == 0xA5): BMC depth $BMC_DEPTH (expect CEX) =="
# Inject the defect into a scratch COPY of the core; fail loudly if the
# substitution did not apply (so a future RTL edit cannot silently turn the
# negative control into a second positive run).
sed 's/wait_cnt <= imm8;/wait_cnt <= (port_ui_in == 8'"'"'hA5) ? 8'"'"'d1 : imm8;/' \
  "$REPO_ROOT/rtl/protocol_core.v" >"$ART_DIR/protocol_core_mutant.v"
if cmp -s "$REPO_ROOT/rtl/protocol_core.v" "$ART_DIR/protocol_core_mutant.v"; then
  echo "ERROR: core mutant substitution did not apply" >&2
  fail=1
else
  run_elab_core "$ART_DIR/core-mutant.smt2" "$ART_DIR/protocol_core_mutant.v" || fail=1
  expect_cex "core mutant" "$ART_DIR/core-mutant.smt2" "$ART_DIR/core-mutant-cex.vcd"
fi

echo "== [8b/8] real-core control-space mutant (2-cycle control access stalls on while ui_in == 0xA5, DR 0012): BMC depth $BMC_DEPTH (expect CEX) =="
# Two checked substitutions into a scratch COPY: the stall cycle neither
# ends nor releases the fetch address while the pin data matches. Each must
# apply (the count of changed lines is checked), so a future RTL edit cannot
# silently disarm the control.
sed -e 's/^          ctl_stall  <= 1'"'"'b0;$/          ctl_stall  <= (port_ui_in == 8'"'"'hA5);/' \
    -e 's/next_addr = stall_run ? rd_val : pc_next;/next_addr = (port_ui_in == 8'"'"'hA5) ? pc : (stall_run ? rd_val : pc_next);/' \
  "$REPO_ROOT/rtl/protocol_core.v" >"$ART_DIR/protocol_core_mutant_ctl.v"
changed="$(diff "$REPO_ROOT/rtl/protocol_core.v" "$ART_DIR/protocol_core_mutant_ctl.v" | grep -c '^>')"
if [ "$changed" -ne 2 ]; then
  echo "ERROR: core control-space mutant substitution applied to $changed line(s), expected 2" >&2
  fail=1
else
  run_elab_core "$ART_DIR/core-mutant-ctl.smt2" "$ART_DIR/protocol_core_mutant_ctl.v" || fail=1
  expect_cex "core control-space mutant" "$ART_DIR/core-mutant-ctl.smt2" "$ART_DIR/core-mutant-ctl-cex.vcd"
fi
fi  # real-core legs

echo
if [ "$fail" -eq 0 ]; then
  echo "RESULT: all expectations met (BMC pass + covers reachable + mutant caught, per selected DUT)"
else
  echo "RESULT: FAILED -- do not mint a record from this run" >&2
fi
exit "$fail"
