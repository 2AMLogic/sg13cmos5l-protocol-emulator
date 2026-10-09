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
# post-layout-sdf-regression/ from run 37995950973 (the first netlist with
# DR 0013 layer 1's load-phase CRC readout, issue #137; it supersedes the
# copy from run 37985271399, the first netlist of the DR 0012 control-space
# design, issue #135). Override with
# --netlist <file> (e.g. one from `gh run download <id> -n tt_submission`).
#
# Negative control (a suite that cannot fail cannot cite its passes): the
# same benches are re-run on a copy of the netlist with ONE fault injected --
# the net `\u_core.wait_cnt[0]` (bit 0 of the WAIT counter) stuck at 0: every
# combinational input pin it feeds is tied to 1'b0. Every bench module must
# FAIL on it (a parsed results.xml with failures, not a compile error), else
# this script fails.
#
# Why bit 0 on every sink, and not "the first sink of bit 3" as this runner
# first had it (issue #135 finding): "the first sink" is whatever gate the
# flow happens to emit first, so the fault moves when the netlist is
# re-synthesized. On the first netlist of the control-space design that sink
# is an inverter, and the faulted netlist still PASSED the SPI bench (whose
# only WAITs are inter-burst gaps) -- the control silently stopped
# controlling one of four modules. A whole-net stuck-at does not depend on
# gate order, and bit 0 is the bit every non-zero WAIT must count through.
#
# Control space (issue #135, DR 0012): --control-space adds
# verification/test_control_space.py, which is pin-only under GATES=yes. The
# WAIT-counter fault is not aimed at it, so it gets its own negative
# control: the net `\u_core.ctl_stall` (the fixed stall of the
# 2-cycle control accesses) stuck at 0 the same way, on a second mutated copy.
#
# Load integrity (issue #137, DR 0013 layer 1): --load-integrity adds
# verification/test_load_integrity.py, which is pin-only. Neither fault above
# is aimed at it (the load phase executes nothing), so it gets its own: the
# net `\pm_crc[0]` (bit 0 of PM_CRC, which feeds both the CRC's own feedback
# and the uo_out readout mux) stuck at 0 the same way, on a third mutated copy.
#
# Usage:  ./flow/run-firmware-gate-level.sh [--netlist FILE] [--full] [--control-space] [--load-integrity]
#   --full  also runs verification/test_firmware_i2c_sr.py (the Sr/stretch
#           sibling bench); default is the three issue-#108 protocol benches.
#   --control-space  also runs verification/test_control_space.py.
#   --load-integrity also runs verification/test_load_integrity.py.
# Env:    PDK_ROOT must contain ihp-sg13cmos5l/ (default ~/share/pdk).
# Runs sims strictly one at a time. Writes flow/firmware-gate-level/
# (gitignored): per-run results.xml, logs, mutated netlist, summary.json.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH="${REPO_ROOT}/flow/firmware-gate-level"
NETLIST="${REPO_ROOT}/verification/records/post-layout-sdf-regression/artifacts/20261009-220508-ce64319/tt_um_2amlogic_protocol_emulator.v"
MODULES=(test_firmware_uart test_firmware_spi test_firmware_i2c)
export PDK_ROOT="${PDK_ROOT:-$HOME/share/pdk}"

while [ $# -gt 0 ]; do
  case "$1" in
    --netlist) NETLIST="$2"; shift 2 ;;
    --full) MODULES+=(test_firmware_i2c_sr); shift ;;
    --control-space) MODULES+=(test_control_space); shift ;;
    --load-integrity) MODULES+=(test_load_integrity); shift ;;
    -h|--help) sed -n '2,57p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "FATAL: unknown argument $1" >&2; exit 1 ;;
  esac
done

[ -f "$NETLIST" ] || { echo "FATAL: netlist ${NETLIST} not found." >&2; exit 1; }
[ -f "${PDK_ROOT}/ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/verilog/sg13cmos5l_stdcell.v" ] \
  || { echo "FATAL: PDK cell models not found under PDK_ROOT=${PDK_ROOT}." >&2; exit 1; }
command -v iverilog >/dev/null && command -v cocotb-config >/dev/null \
  || { echo "FATAL: iverilog and cocotb-config are required." >&2; exit 1; }

rm -rf "$SCRATCH"; mkdir -p "$SCRATCH"
MUTANT="${SCRATCH}/mutant-wait_cnt0-stuck0.v"
MUTANT_CTL="${SCRATCH}/mutant-ctl_stall-stuck0.v"
MUTANT_CRC="${SCRATCH}/mutant-pm_crc0-stuck0.v"
inject_fault() {  # inject_fault <net-regex> <net-name-for-messages> <out-netlist>
  python3 -I - "$NETLIST" "$3" "$1" "$2" <<'PYEOF'
import re, sys
src, dst, net_re, net_name = sys.argv[1:5]
text = open(src, encoding="utf-8").read()
# every input-pin connection (.A.., .B.., .S.. -- never .Q/.Y/.X/.D) to the net
pat = re.compile(r"(\.(?:A|B|C|D1|S|A_N|B_N|A1|A2|B1|B2)\d?)\(" + net_re + r" \)")
text, n = pat.subn(lambda m: m.group(1) + "(1'b0)", text)
if n == 0:
    sys.exit(f"FATAL: no combinational sink of {net_name} found to inject the fault")
open(dst, "w", encoding="utf-8").write(text)
print(f"fault injected: {net_name} stuck at 0 on {n} input pin(s)", file=sys.stderr)
PYEOF
}
inject_fault '\\u_core\.wait_cnt\[0\]' '\u_core.wait_cnt[0]' "$MUTANT"
for mod in "${MODULES[@]}"; do
  if [ "$mod" = test_control_space ]; then
    inject_fault '\\u_core\.ctl_stall' '\u_core.ctl_stall' "$MUTANT_CTL"
  fi
  if [ "$mod" = test_load_integrity ]; then
    inject_fault '\\pm_crc\[0\]' '\pm_crc[0]' "$MUTANT_CRC"
  fi
done
mutant_for() {  # the faulted netlist that must make <module> fail
  case "$1" in
    test_control_space) echo "$MUTANT_CTL" ;;
    test_load_integrity) echo "$MUTANT_CRC" ;;
    *) echo "$MUTANT" ;;
  esac
}

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
  out="$(run_bench mutant "$(mutant_for "$mod")" "$mod")"
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
