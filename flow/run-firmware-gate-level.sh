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
# post-layout-sdf-regression/ from run 38013383254 (the first netlist with
# the SPI-flash boot program, issue #140). Override with
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
# Pad path (issue #136, DR 0012): the I2C benches run on the silicon-true
# pad model (verification/uio_pads.py), so on this netlist the SCL/SDA lines
# they grade are resolved from the netlist's own `uio_oe` / `uio_out`; since
# issue #155 the SPI bench does too (CS/MOSI/SCLK on uio[0]/[1]/[3]). The
# WAIT-counter fault says nothing about that path, so every pad-model module
# gets a second negative control on a third mutated copy: the top-level
# output `uio_oe[3]` stuck at 0 -- the pad enable of SPI's SCLK and of I2C's
# SDA (DR 0010's target plan; it was SCL's `uio_oe[0]` before #155) -- its
# driving cell is rewired to a dangling net and the port tied to 1'b0.
# `uio_out` is untouched, which is the point: the bench-composed bus these
# benches graded before #136 would pass on that netlist; the pad model must
# not.
#
# Boot ROM (issue #138, DR 0013 layer 2): --boot-rom adds
# verification/test_boot_rom.py, pin-only under GATES=yes like the
# control-space bench. Its negative control is the net `\u_core.rom_exit`
# (the flop that records that a WCTL RUN left the boot ROM) stuck at 0 on a
# fourth mutated copy: the boot program still verifies the image and still
# jumps, but the core goes on decoding the ROM, so a verified image never
# runs and the bench's warm-start test must fail.
#
# SPI-flash boot (issue #140, DR 0013 strap 01): --boot-spi adds
# verification/test_boot_spi.py, pin-only under GATES=yes. It boots signed
# images from the independent flash model over the netlist's own CS0/MOSI/
# SCK/MISO pads. Its negative control is the same `\u_core.rom_exit` stuck-
# at-0 netlist: a good image never runs, so the bench's boot tests must fail.
#
# UART boot (issue #139, DR 0013 layer 2 strap 00): --boot-uart adds
# verification/test_boot_uart.py, pin-only under GATES=yes (its white-box
# reads and its two long runs -- the host-rate sweep and the 256-word image --
# are skipped there). It shares the boot-rom negative control (`rom_exit`
# stuck at 0: a verified UART load then never leaves the ROM).
#
# Usage:  ./flow/run-firmware-gate-level.sh [--netlist FILE] [--full] [--control-space] [--boot-rom] [--boot-spi] [--boot-uart]
#   --full  also runs verification/test_firmware_i2c_sr.py (the Sr/stretch
#           sibling bench); default is the three issue-#108 protocol benches.
#   --control-space  also runs verification/test_control_space.py.
#   --boot-rom       also runs verification/test_boot_rom.py.
#   --boot-spi       also runs verification/test_boot_spi.py.
#   --boot-uart      also runs verification/test_boot_uart.py.
# Env:    PDK_ROOT must contain ihp-sg13cmos5l/ (default ~/share/pdk).
# Runs sims strictly one at a time. Writes flow/firmware-gate-level/
# (gitignored): per-run results.xml, logs, mutated netlist, summary.json.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH="${REPO_ROOT}/flow/firmware-gate-level"
NETLIST="${REPO_ROOT}/verification/records/post-layout-sdf-regression/artifacts/20261010-020805-ed5f2d1/tt_um_2amlogic_protocol_emulator.v"
MODULES=(test_firmware_uart test_firmware_spi test_firmware_i2c)
export PDK_ROOT="${PDK_ROOT:-$HOME/share/pdk}"

while [ $# -gt 0 ]; do
  case "$1" in
    --netlist) NETLIST="$2"; shift 2 ;;
    --full) MODULES+=(test_firmware_i2c_sr); shift ;;
    --control-space) MODULES+=(test_control_space); shift ;;
    --boot-rom) MODULES+=(test_boot_rom); shift ;;
    --boot-spi) MODULES+=(test_boot_spi); shift ;;
    --boot-uart) MODULES+=(test_boot_uart); shift ;;
    -h|--help) sed -n '2,84p' "${BASH_SOURCE[0]}"; exit 0 ;;
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
MUTANT_BOOT="${SCRATCH}/mutant-rom_exit-stuck0.v"
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
  if [ "$mod" = test_boot_rom ] || [ "$mod" = test_boot_spi ] || [ "$mod" = test_boot_uart ]; then
    inject_fault '\\u_core\.rom_exit' '\u_core.rom_exit' "$MUTANT_BOOT"
  fi
done
MUTANT_PAD="${SCRATCH}/mutant-uio_oe3-stuck0.v"
python3 -I - "$NETLIST" "$MUTANT_PAD" <<'PYEOF'
import re, sys
src, dst = sys.argv[1:3]
text = open(src, encoding="utf-8").read()
# the one cell output that drives the port, rewired to a dangling net
text, n = re.subn(r"\.(Y|X|Q|Z)\(uio_oe\[3\]\)", r".\1(pad_fault_uio_oe3_unconnected)", text)
if n != 1:
    sys.exit(f"FATAL: expected exactly one cell output driving uio_oe[3], found {n}")
text, m = re.subn(r"(\n output \[7:0\] uio_oe;\n)",
                  r"\1 wire pad_fault_uio_oe3_unconnected;\n assign uio_oe[3] = 1'b0;\n", text)
if m != 1:
    sys.exit("FATAL: top-level `output [7:0] uio_oe;` declaration not found")
open(dst, "w", encoding="utf-8").write(text)
print("fault injected: top-level output uio_oe[3] stuck at 0 (driver disconnected)", file=sys.stderr)
PYEOF
on_pads() { case "$1" in test_firmware_spi|test_firmware_i2c|test_firmware_i2c_sr) return 0 ;; *) return 1 ;; esac; }
mutant_for() {  # the faulted netlist that must make <module> fail
  case "$1" in
    test_control_space) echo "$MUTANT_CTL" ;;
    test_boot_rom|test_boot_spi|test_boot_uart) echo "$MUTANT_BOOT" ;;
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
for mod in "${MODULES[@]}"; do
  on_pads "$mod" || continue
  out="$(run_bench mutant-pad "$MUTANT_PAD" "$mod")"
  echo "PAD-FAULT-RUN ${mod}: ${out}" >&2
  ok=1
  [[ "$out" == *"unparsed=0"* && "$out" != *"failed=0"* && "$out" != *"rc=0" ]] || ok=0
  [ "$ok" -eq 1 ] || FAILED=1
  echo "${sep}    {\"kind\": \"negative-control-pad\", \"fault\": \"uio_oe[3] stuck at 0\", \"module\": \"${mod}\", \"result\": \"${out}\", \"as_required\": $([ $ok -eq 1 ] && echo true || echo false)}" >> "${SCRATCH}/summary.json"; sep=","
done
echo "" >> "${SCRATCH}/summary.json"; echo "  ]" >> "${SCRATCH}/summary.json"; echo "}" >> "${SCRATCH}/summary.json"
python3 -I -c "import json,sys; json.load(open(sys.argv[1]))" "${SCRATCH}/summary.json"
[ "$FAILED" -eq 0 ] && echo "OK: all golden runs pass and all negative controls fail" >&2 \
  || { echo "FATAL: gate-level firmware regression not as required; see ${SCRATCH}" >&2; exit 1; }
