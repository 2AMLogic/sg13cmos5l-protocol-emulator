#!/usr/bin/env bash
#
# flow/run-ws2812-gate-level.sh -- run the row-13 WS2812 firmware bench
# (verification/test_firmware_ws2812.py, UNMODIFIED) against the LibreLane
# gate-level netlist of the submitted top, zero-delay (issue #141 part 2;
# spec/verification-plan.md sections 3 and 7). It does what
# flow/run-firmware-gate-level.sh does for the UART / SPI / I2C benches, in a
# separate script so that the live records hashing that runner stay live.
#
# Flow attribution: the netlist is a Tiny Tapeout LibreLane artifact (DR
# 0002's sign-off flow). The simulator is Icarus + cocotb, driven through the
# template's own test/Makefile `GATES=yes` plumbing (stdcell + UDP models from
# the PDK, the vendored SRAM macro model, -DFUNCTIONAL). No klt synthesis or
# timing number is produced or implied. Zero-delay: no SDF, no pad electrical
# behaviour, no measured wall-clock pulse width. The pulse widths the bench
# grades are core cycles x the 20 ns simulation clock.
#
# Which netlist: by default the same frozen copy flow/run-firmware-gate-level.sh
# uses, the `tt_submission` netlist of gds run 38083802720, frozen under
# verification/records/post-layout-sdf-regression/. Override with
# --netlist <file>.
#
# Negative controls, both required:
#  1. The bench's own mutant programs (short T1H, dropped bit, short reset)
#     run on the netlist and must be rejected by the reference model. They
#     are tests in the bench and must PASS on the golden netlist.
#  2. The same bench on a copy of the netlist with ONE fault injected: the net
#     `\u_core.wait_cnt[0]` (bit 0 of the WAIT counter) stuck at 0 on every
#     combinational input pin it feeds. Every WS2812 pulse is padded by a
#     WAIT, so the bench must FAIL (a parsed results.xml with failures, not
#     a compile error), or this script fails.
#
# Usage:  ./flow/run-ws2812-gate-level.sh [--netlist FILE]
# Env:    PDK_ROOT must contain ihp-sg13cmos5l/ (default ~/share/pdk).
# Writes flow/ws2812-gate-level/ (gitignored): per-run results.xml, logs,
# the mutated netlist, summary.json.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH="${REPO_ROOT}/flow/ws2812-gate-level"
NETLIST="${REPO_ROOT}/verification/records/post-layout-sdf-regression/artifacts/20261011-035358-1c19c24/tt_um_2amlogic_protocol_emulator.v"
MODULE=test_firmware_ws2812
export PDK_ROOT="${PDK_ROOT:-$HOME/share/pdk}"

while [ $# -gt 0 ]; do
  case "$1" in
    --netlist) NETLIST="$2"; shift 2 ;;
    -h|--help) sed -n '2,38p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "FATAL: unknown argument $1" >&2; exit 1 ;;
  esac
done

[ -f "$NETLIST" ] || { echo "FATAL: netlist ${NETLIST} not found." >&2; exit 1; }
[ -f "${PDK_ROOT}/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_stdcell.v" ] \
  || { echo "FATAL: PDK cell models not found under PDK_ROOT=${PDK_ROOT}." >&2; exit 1; }
command -v iverilog >/dev/null && command -v cocotb-config >/dev/null \
  || { echo "FATAL: iverilog and cocotb-config are required." >&2; exit 1; }

sha() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

rm -rf "$SCRATCH"; mkdir -p "$SCRATCH"
MUTANT="${SCRATCH}/mutant-wait_cnt0-stuck0.v"
python3 -I - "$NETLIST" "$MUTANT" <<'PYEOF'
import re, sys
src, dst = sys.argv[1:3]
text = open(src, encoding="utf-8").read()
# every input-pin connection (.A.., .B.., .S.. -- never .Q/.Y/.X/.D) to the net
pat = re.compile(r"(\.(?:A|B|C|D1|S|A_N|B_N|A1|A2|B1|B2)\d?)\(\\u_core\.wait_cnt\[0\] \)")
text, n = pat.subn(lambda m: m.group(1) + "(1'b0)", text)
if n == 0:
    sys.exit("FATAL: no combinational sink of \\u_core.wait_cnt[0] found to inject the fault")
open(dst, "w", encoding="utf-8").write(text)
print(f"fault injected: \\u_core.wait_cnt[0] stuck at 0 on {n} input pin(s)", file=sys.stderr)
PYEOF

run_bench() {  # run_bench <tag> <netlist>  -> prints counts, sets RC
  local tag="$1" nl="$2" dir="${SCRATCH}/${1}"
  mkdir -p "$dir"
  set +e
  (cd "$dir" && PYTHONPATH="${REPO_ROOT}/verification" make -f "${REPO_ROOT}/test/Makefile" \
      PWD="${REPO_ROOT}/test" GATES=yes GATE_LEVEL_NETLIST="$nl" \
      COCOTB_TEST_MODULES="$MODULE" SIM_BUILD="${dir}/sim_build") > "${dir}/console.txt" 2>&1
  RC=$?
  set -e
  python3 -I - "${dir}/results.xml" "$RC" <<'PYEOF'
import sys, xml.etree.ElementTree as ET
path, rc = sys.argv[1:3]
try:
    root = ET.parse(path).getroot()
except Exception:
    print(f"tests=0 failed=0 unparsed=1 rc={rc}"); sys.exit(0)
cases = list(root.iter("testcase"))
failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
print(f"tests={len(cases)} failed={len(failed)} unparsed=0 rc={rc}")
PYEOF
}

FAILED=0
echo "== netlist: ${NETLIST} (sha256 $(sha "$NETLIST"))" >&2
golden="$(run_bench pass "$NETLIST")"
echo "PASS-RUN   ${MODULE}: ${golden}" >&2
g_ok=1
[[ "$golden" == *"unparsed=0"* && "$golden" == *"failed=0"* && "$golden" != *"tests=0 "* && "$golden" == *"rc=0" ]] || g_ok=0
[ "$g_ok" -eq 1 ] || FAILED=1
mutant="$(run_bench mutant "$MUTANT")"
echo "MUTANT-RUN ${MODULE}: ${mutant}" >&2
m_ok=1
[[ "$mutant" == *"unparsed=0"* && "$mutant" != *"failed=0"* && "$mutant" != *"rc=0" ]] || m_ok=0
[ "$m_ok" -eq 1 ] || FAILED=1

python3 -I - "${SCRATCH}/summary.json" "$NETLIST" "$(sha "$NETLIST")" "$golden" "$g_ok" "$mutant" "$m_ok" <<'PYEOF'
import json, sys
out, netlist, digest, golden, g_ok, mutant, m_ok = sys.argv[1:8]
json.dump({
    "netlist": netlist, "netlist_sha256": digest,
    "flow": "LibreLane (Tiny Tapeout gds workflow) netlist; Icarus+cocotb zero-delay simulation",
    "runs": [
        {"kind": "golden", "module": "test_firmware_ws2812", "result": golden, "as_required": g_ok == "1"},
        {"kind": "negative-control", "fault": "\\u_core.wait_cnt[0] stuck at 0",
         "module": "test_firmware_ws2812", "result": mutant, "as_required": m_ok == "1"},
    ],
}, open(out, "w"), indent=2)
PYEOF
[ "$FAILED" -eq 0 ] && echo "OK: the golden run passes and the negative control fails" >&2 \
  || { echo "FATAL: WS2812 gate-level run not as required; see ${SCRATCH}" >&2; exit 1; }
