#!/usr/bin/env bash
#
# flow/run-reset-power-up-gate-level.sh -- target-spec row 14 /
# spec/verification-plan.md section 8 (issue #131): reset, power-up and
# reselect, on the **LibreLane gate-level netlist** (the flow of record),
# zero-delay. Flow attribution: the netlist is a Tiny Tapeout LibreLane
# artifact (DR 0002's sign-off flow); the simulator is Icarus + cocotb driven
# through the template's own test/Makefile `GATES=yes` plumbing (stdcell + UDP
# models from the PDK, the vendored SRAM macro behavioural model,
# -DFUNCTIONAL), exactly as flow/run-firmware-gate-level.sh drives it. No klt
# synthesis or timing number is produced or implied.
#
# Default netlist: the byte-identical copy frozen under verification/records/
# post-layout-sdf-regression/ from gds run 38071502150 (the first netlist with
# both DR 0015's P1/P2, issue #208, and the UART load in the boot ROM, issue
# #139; before the merge it was gds run 38055685598's for #208 and gds run
# 38054423540's for #139; before those gds run 38032061275's, the first with
# the A_REN drive buffer, issue #173; until #173 gds run 38013383254's, the
# first with the SPI-flash boot program, issue #140; until #140 gds run
# 37996177546's, the first with DR 0013's boot ROM, issue #138). It must carry
# the same boot ROM as rtl/protocol_boot_rom.v, because the bench predicts the
# boot from the committed image. Override with --netlist <file>. The netlist
# is never edited: the bench sets the power-up state from the testbench
# (verification/test_reset_power_up.py's docstring says how).
#
# Steps, all of which must come out as required or this script fails:
#
#   1. Reset-coverage listing (verification/reset_coverage.py) on the netlist
#      against verification/reset_coverage_justifications.json: must PASS.
#   2. The bench (verification/test_reset_power_up.py): every test must PASS.
#   3. Negative controls (a suite that cannot fail cannot cite its passes):
#      (i)   mutant `uio_dir0-noreset`: the flop whose Q is
#            \u_core.uio_dir[0] (UIO_DIR bit 0, which drives uio_oe[0]) gets
#            RESET_B tied to 1'b1 -- a flop that is never reset and leaks to a
#            pin. The bench's all-X and random-seed tests must FAIL, citing
#            the pin clause [row14-b].
#      (ii)  the same mutant must make the reset-coverage check FAIL with an
#            UNJUSTIFIED entry for u_core.uio_dir[0]; and a justification file
#            with one extra entry naming no non-reset element must make it
#            FAIL with a STALE entry, on the golden netlist.
#      (iii) mutant `rom_exit-stuck1`: every input pin fed by the net
#            \u_core.rom_exit is tied to 1'b1, so the core believes it has
#            already left the boot ROM and fetches from the SRAM from reset
#            (DR 0013's MODE-low boot bypassed). The bench's
#            uninitialised-program-memory test must FAIL, citing the
#            fetch-source clause [row14-c].
#
# Usage:  ./flow/run-reset-power-up-gate-level.sh [--netlist FILE]
# Env:    PDK_ROOT must contain ihp-sg13cmos5l/ (default ~/share/pdk).
# Runs sims strictly one at a time. Writes flow/reset-power-up/ (gitignored):
# per-run results.xml, console logs, bench summaries, mutated netlists, the
# coverage listings and summary.json.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH="${REPO_ROOT}/flow/reset-power-up"
NETLIST="${REPO_ROOT}/verification/records/post-layout-sdf-regression/artifacts/20261010-174900-f8428aa/tt_um_2amlogic_protocol_emulator.v"
JUSTIFICATIONS="${REPO_ROOT}/verification/reset_coverage_justifications.json"
MODULE=test_reset_power_up
export PDK_ROOT="${PDK_ROOT:-$HOME/share/pdk}"

while [ $# -gt 0 ]; do
  case "$1" in
    --netlist) NETLIST="$2"; shift 2 ;;
    -h|--help) sed -n '2,50p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "FATAL: unknown argument $1" >&2; exit 1 ;;
  esac
done

[ -f "$NETLIST" ] || { echo "FATAL: netlist ${NETLIST} not found." >&2; exit 1; }
[ -f "${PDK_ROOT}/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_stdcell.v" ] \
  || { echo "FATAL: PDK cell models not found under PDK_ROOT=${PDK_ROOT}." >&2; exit 1; }
command -v iverilog >/dev/null && command -v cocotb-config >/dev/null \
  || { echo "FATAL: iverilog and cocotb-config are required." >&2; exit 1; }

rm -rf "$SCRATCH"; mkdir -p "$SCRATCH"
NETLIST_SHA="$(sha256sum "$NETLIST" | cut -d' ' -f1)"
MUT_NORESET="${SCRATCH}/mutant-uio_dir0-noreset.v"
MUT_ROMEXIT="${SCRATCH}/mutant-rom_exit-stuck1.v"
STALE_JUST="${SCRATCH}/justifications-with-stale-entry.json"

# ---- mutants ---------------------------------------------------------------
python3 -I - "$NETLIST" "$MUT_NORESET" <<'PYEOF'
import re, sys
src, dst = sys.argv[1:3]
text = open(src, encoding="utf-8").read()
# the one cell instance whose Q pin is \u_core.uio_dir[0]
inst = re.compile(r"(sg13cmos5l_df\w+\s+\S+\s*\()([^;]*?\.Q\(\\u_core\.uio_dir\[0\] \)[^;]*?)(\);)", re.S)
hits = [m for m in inst.finditer(text) if m.group(2).count(".Q(") == 1]
if len(hits) != 1:
    sys.exit(f"FATAL: expected one flop driving \\u_core.uio_dir[0], found {len(hits)}")
m = hits[0]
body, n = re.subn(r"\.RESET_B\([^)]*\)", ".RESET_B(1'b1)", m.group(2))
if n != 1:
    sys.exit("FATAL: that flop has no RESET_B pin to tie")
text = text[:m.start(2)] + body + text[m.end(2):]
open(dst, "w", encoding="utf-8").write(text)
print("fault injected: RESET_B of the \\u_core.uio_dir[0] flop tied to 1'b1", file=sys.stderr)
PYEOF
python3 -I - "$NETLIST" "$MUT_ROMEXIT" <<'PYEOF'
import re, sys
src, dst = sys.argv[1:3]
text = open(src, encoding="utf-8").read()
# every input-pin connection (never .Q/.Y/.X) to the net, as run-firmware-gate-level.sh does
pat = re.compile(r"(\.(?:A|B|C|D1|S|A_N|B_N|A1|A2|B1|B2)\d?)\(\\u_core\.rom_exit \)")
text, n = pat.subn(lambda m: m.group(1) + "(1'b1)", text)
if n == 0:
    sys.exit("FATAL: no combinational sink of \\u_core.rom_exit found to inject the fault")
open(dst, "w", encoding="utf-8").write(text)
print(f"fault injected: \\u_core.rom_exit stuck at 1 on {n} input pin(s)", file=sys.stderr)
PYEOF
python3 -I - "$JUSTIFICATIONS" "$STALE_JUST" <<'PYEOF'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
doc["justifications"].append({"element": "u_core.no_such_register",
                              "justification": "negative control: names nothing"})
json.dump(doc, open(sys.argv[2], "w", encoding="utf-8"), indent=2)
PYEOF
for m in "$MUT_NORESET" "$MUT_ROMEXIT"; do
  diff "$NETLIST" "$m" > "${m%.v}.diff" || true
done

FAILED=0
RESULTS=()
note() {  # note <kind> <name> <as_required 0/1> <detail>
  echo "$( [ "$3" -eq 1 ] && echo OK || echo NOT-AS-REQUIRED )  $1 $2: $4" >&2
  [ "$3" -eq 1 ] || FAILED=1
  RESULTS+=("$(python3 -I -c 'import json,sys; print(json.dumps({"kind": sys.argv[1], "name": sys.argv[2], "as_required": sys.argv[3] == "1", "detail": sys.argv[4]}))' "$1" "$2" "$3" "$4")")
}

# ---- reset-coverage listing ------------------------------------------------
coverage() {  # coverage <tag> <netlist> <justifications> -> sets RC
  set +e
  python3 -I "${REPO_ROOT}/verification/reset_coverage.py" --netlist "$2" --justifications "$3" \
      --json "${SCRATCH}/coverage-$1.json" > "${SCRATCH}/coverage-$1.txt" 2>&1
  RC=$?
  set -e
}
coverage golden "$NETLIST" "$JUSTIFICATIONS"
note golden reset-coverage "$([ $RC -eq 0 ] && echo 1 || echo 0)" "exit ${RC}; $(head -1 "${SCRATCH}/coverage-golden.txt")"
coverage mutant-noreset "$MUT_NORESET" "$JUSTIFICATIONS"
ok=0; [ $RC -eq 1 ] && grep -q 'UNJUSTIFIED non-reset state element `u_core.uio_dir\[0\]`' "${SCRATCH}/coverage-mutant-noreset.txt" && ok=1
note negative-control "reset-coverage (ii) unlisted non-reset flop" "$ok" "exit ${RC}"
coverage stale-entry "$NETLIST" "$STALE_JUST"
ok=0; [ $RC -eq 1 ] && grep -q 'STALE justification `u_core.no_such_register`' "${SCRATCH}/coverage-stale-entry.txt" && ok=1
note negative-control "reset-coverage (ii) stale justification" "$ok" "exit ${RC}"

# ---- the bench -------------------------------------------------------------
run_bench() {  # run_bench <tag> <netlist> -> prints "tests= failed= unparsed= rc="
  local tag="$1" nl="$2" dir="${SCRATCH}/${1}"
  mkdir -p "$dir"
  set +e
  (cd "$dir" && PYTHONPATH="${REPO_ROOT}/verification" RESET_POWER_UP_NETLIST="$nl" \
      RESET_POWER_UP_SUMMARY="${dir}/bench-summary.json" \
      make -f "${REPO_ROOT}/test/Makefile" PWD="${REPO_ROOT}/test" GATES=yes GATE_LEVEL_NETLIST="$nl" \
      COCOTB_TEST_MODULES="$MODULE" SIM_BUILD="${dir}/sim_build") > "${dir}/console.txt" 2>&1
  local rc=$?
  set -e
  rm -f "${dir}/tb.fst"
  python3 -I - "${dir}/results.xml" "$rc" <<'PYEOF'
import sys, xml.etree.ElementTree as ET
path, rc = sys.argv[1:3]
try:
    root = ET.parse(path).getroot()
except Exception:
    print(f"tests=0 failed=0 unparsed=1 rc={rc} failing="); sys.exit(0)
cases = list(root.iter("testcase"))
failed = [c.get("name") for c in cases if c.find("failure") is not None or c.find("error") is not None]
print(f"tests={len(cases)} failed={len(failed)} unparsed=0 rc={rc} failing={','.join(failed)}")
PYEOF
}
failed_with() {  # failed_with <tag> <test> <regex>: the test failed and its message matches
  python3 -I - "${SCRATCH}/$1/bench-summary.json" "$2" "$3" <<'PYEOF'
import json, re, sys
path, test, regex = sys.argv[1:4]
try:
    msg = json.load(open(path, encoding="utf-8")).get("failures", {}).get(test)
except Exception:
    msg = None
sys.exit(0 if msg is not None and re.search(regex, msg) else 1)
PYEOF
}

out="$(run_bench golden "$NETLIST")"
ok=0; [[ "$out" == *"tests=5 failed=0 unparsed=0 rc=0"* ]] && ok=1
note golden "$MODULE" "$ok" "$out"

out="$(run_bench mutant-noreset "$MUT_NORESET")"
ok=1
for t in test_power_up_all_x test_power_up_random_seeds; do
  failed_with mutant-noreset "$t" '\[row14-b\]' || ok=0
done
note negative-control "${MODULE} (i) non-reset flop leaking to uio_oe" "$ok" "$out"

out="$(run_bench mutant-romexit "$MUT_ROMEXIT")"
ok=0; failed_with mutant-romexit test_uninitialised_program_memory '\[row14-c\]' && ok=1
note negative-control "${MODULE} (iii) boot ROM bypassed at reset" "$ok" "$out"

python3 -I - "${SCRATCH}/summary.json" "$NETLIST" "$NETLIST_SHA" "${RESULTS[@]}" <<'PYEOF'
import json, sys
path, netlist, sha, *runs = sys.argv[1:]
json.dump({
    "netlist": netlist, "netlist_sha256": sha,
    "flow": "LibreLane (Tiny Tapeout gds workflow) netlist; Icarus+cocotb zero-delay simulation via test/Makefile GATES=yes",
    "runs": [json.loads(r) for r in runs],
}, open(path, "w", encoding="utf-8"), indent=2)
PYEOF
[ "$FAILED" -eq 0 ] && echo "OK: coverage listing and bench pass; all negative controls fail as required" >&2 \
  || { echo "FATAL: reset/power-up regression not as required; see ${SCRATCH}" >&2; exit 1; }
