#!/usr/bin/env bash
#
# flow/run-firmware-gate-level.sh -- run the committed UART / SPI / I2C
# firmware benches (verification/test_firmware_*.py, UNMODIFIED) against the
# **LibreLane gate-level netlist** of the submitted top, zero-delay (issue
# #108; spec/verification-plan.md section 3). Flow attribution: the netlist
# is a Tiny Tapeout LibreLane artifact (DR 0002's sign-off flow); the
# simulator is Icarus + cocotb driven through the template's own
# test/Makefile `GATES=yes` plumbing (stdcell + UDP models from the PDK, the
# vendored SRAM macro behavioural model, -DFUNCTIONAL). No klt synthesis or
# timing number is produced or implied.
#
# Which netlist: the `tt_submission` artifact's `<top>.v` of a `gds` workflow
# run -- the final netlist that the template's own `gl_test` job compiles.
# Default: the byte-identical copy frozen under verification/records/
# post-layout-sdf-regression/ from run 37911842396. Override with
# --netlist <file> (e.g. one from `gh run download <id> -n tt_submission`).
#
# Negative control (a suite that cannot fail cannot cite its passes): the
# same benches are re-run on a copy of the netlist with ONE fault injected --
# the first combinational input pin fed by `\u_core.wait_cnt[3]` (the WAIT
# counter) is tied to 1'b0. Every bench module must FAIL on it (a parsed
# results.xml with failures, not a compile error), else this script fails.
#
# Usage:  ./flow/run-firmware-gate-level.sh [--netlist FILE] [--full]
#   --full  also runs verification/test_firmware_i2c_sr.py (the Sr/stretch
#           sibling bench); default is the three issue-#108 protocol benches.
# Env:    PDK_ROOT must contain ihp-sg13cmos5l/ (default ~/share/pdk).
# Runs sims strictly one at a time. Writes flow/firmware-gate-level/
# (gitignored): per-run results.xml, logs, mutated netlist, summary.json.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH="${REPO_ROOT}/flow/firmware-gate-level"
NETLIST="${REPO_ROOT}/verification/records/post-layout-sdf-regression/artifacts/20261009-103407-9716a9e/tt_um_2amlogic_protocol_emulator.v"
MODULES=(test_firmware_uart test_firmware_spi test_firmware_i2c)
export PDK_ROOT="${PDK_ROOT:-$HOME/share/pdk}"

while [ $# -gt 0 ]; do
  case "$1" in
    --netlist) NETLIST="$2"; shift 2 ;;
    --full) MODULES+=(test_firmware_i2c_sr); shift ;;
    -h|--help) sed -n '2,32p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "FATAL: unknown argument $1" >&2; exit 1 ;;
  esac
done

[ -f "$NETLIST" ] || { echo "FATAL: netlist ${NETLIST} not found." >&2; exit 1; }
[ -f "${PDK_ROOT}/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_stdcell.v" ] \
  || { echo "FATAL: PDK cell models not found under PDK_ROOT=${PDK_ROOT}." >&2; exit 1; }
command -v iverilog >/dev/null && command -v cocotb-config >/dev/null \
  || { echo "FATAL: iverilog and cocotb-config are required." >&2; exit 1; }

rm -rf "$SCRATCH"; mkdir -p "$SCRATCH"
MUTANT="${SCRATCH}/mutant-wait_cnt3-stuck0.v"
python3 -I - "$NETLIST" "$MUTANT" <<'PYEOF'
import re, sys
src, dst = sys.argv[1:3]
text = open(src, encoding="utf-8").read()
# first input-pin connection (.A.., .B.., .S.. -- never .Q/.Y/.D) to the net
pat = re.compile(r"(\.(?:A|B|C|D1|S|A_N|B_N|A1|A2|B1|B2)\d?)\(\\u_core\.wait_cnt\[3\] \)")
m = pat.search(text)
if not m:
    sys.exit("FATAL: no combinational sink of \\u_core.wait_cnt[3] found to inject the fault")
text = text[:m.start()] + m.group(1) + "(1'b0)" + text[m.end():]
open(dst, "w", encoding="utf-8").write(text)
print(f"fault injected: {m.group(0)} -> {m.group(1)}(1'b0)", file=sys.stderr)
PYEOF

run_bench() {  # run_bench <tag> <netlist> <module>  -> sets RC, prints counts
  local tag="$1" nl="$2" mod="$3" dir="${SCRATCH}/${1}/${3}"
  mkdir -p "$dir"
  set +e
  (cd "$dir" && PYTHONPATH="${REPO_ROOT}/verification" make -f "${REPO_ROOT}/test/Makefile" \
      PWD="${REPO_ROOT}/test" GATES=yes GATE_LEVEL_NETLIST="$nl" \
      COCOTB_TEST_MODULES="$mod" SIM_BUILD="${dir}/sim_build") > "${dir}/console.txt" 2>&1
  RC=$?
  set -e
  python3 -I - "${dir}/results.xml" "$RC" <<'PYEOF'
import sys, xml.etree.ElementTree as ET
path, rc = sys.argv[1:3]
try:
    root = ET.parse(path).getroot()
except Exception as e:
    print(f"tests=0 failed=0 unparsed=1 rc={rc}"); sys.exit(0)
cases = list(root.iter("testcase"))
failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
print(f"tests={len(cases)} failed={len(failed)} unparsed=0 rc={rc}")
PYEOF
}

FAILED=0
echo "== netlist: ${NETLIST} (sha256 $(sha256sum "$NETLIST" | cut -d' ' -f1))" >&2
echo "{" > "${SCRATCH}/summary.json"
echo "  \"netlist\": \"${NETLIST}\", \"netlist_sha256\": \"$(sha256sum "$NETLIST" | cut -d' ' -f1)\"," >> "${SCRATCH}/summary.json"
echo "  \"flow\": \"LibreLane (Tiny Tapeout gds workflow) netlist; Icarus+cocotb zero-delay simulation\"," >> "${SCRATCH}/summary.json"
echo "  \"runs\": [" >> "${SCRATCH}/summary.json"
sep=""
for mod in "${MODULES[@]}"; do
  out="$(run_bench pass "$NETLIST" "$mod")"
  echo "PASS-RUN  ${mod}: ${out}" >&2
  ok=1
  [[ "$out" == *"unparsed=0"* && "$out" == *"failed=0"* && "$out" != *"tests=0 "* && "$out" == *"rc=0" ]] || ok=0
  [ "$ok" -eq 1 ] || FAILED=1
  echo "${sep}    {\"kind\": \"golden\", \"module\": \"${mod}\", \"result\": \"${out}\", \"as_required\": $([ $ok -eq 1 ] && echo true || echo false)}" >> "${SCRATCH}/summary.json"; sep=","
done
for mod in "${MODULES[@]}"; do
  out="$(run_bench mutant "$MUTANT" "$mod")"
  echo "MUTANT-RUN ${mod}: ${out}" >&2
  ok=1
  # must fail inside the bench: parsed results with >=1 failed test
  [[ "$out" == *"unparsed=0"* && "$out" != *"failed=0"* && "$out" != *"rc=0" ]] || ok=0
  [ "$ok" -eq 1 ] || FAILED=1
  echo "${sep}    {\"kind\": \"negative-control\", \"module\": \"${mod}\", \"result\": \"${out}\", \"as_required\": $([ $ok -eq 1 ] && echo true || echo false)}" >> "${SCRATCH}/summary.json"; sep=","
done
echo "" >> "${SCRATCH}/summary.json"; echo "  ]" >> "${SCRATCH}/summary.json"; echo "}" >> "${SCRATCH}/summary.json"
python3 -I -c "import json,sys; json.load(open(sys.argv[1]))" "${SCRATCH}/summary.json"
[ "$FAILED" -eq 0 ] && echo "OK: all golden runs pass and all negative controls fail" >&2 \
  || { echo "FATAL: gate-level firmware regression not as required; see ${SCRATCH}" >&2; exit 1; }
