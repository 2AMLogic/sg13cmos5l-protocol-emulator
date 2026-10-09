#!/usr/bin/env python3
"""Negative controls for `test_control_space.py` (issue #135, DR 0012).

A bench that cannot fail cannot cite its passes. This runner copies the
sources the bench needs into a scratch tree, injects ONE defect into the
copy of the RTL, runs the unmodified bench on it through
`klt functional-verification`, and requires the bench to FAIL -- by a
parsed result with at least one failed test, not by a crash. It repeats
that for each defect below. `rtl/` and `src/` in the repository are never
edited.

Each defect is an exact-text substitution that must apply (the anchor must
be present exactly as many times as stated), so a later RTL edit cannot
silently turn a negative control into a second positive run.

Each mutant also names the tests that exist to catch it; the run fails if
none of them is among the failures (the defect was caught, but only by
accident).

Usage:
    python3 verification/control_space_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH, like the bench itself.
Runs one simulation at a time. Writes `summary.json` and one directory per
mutant under --out (default: a temporary directory, removed on exit).
Exit 0 = the golden run passed and every mutant was caught as required.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE = "rtl/protocol_core.v"
PMEM = "rtl/protocol_program_memory.v"
TOP = "src/tt_um_2amlogic_protocol_emulator.v"

T_RESET = "test_reset_values_and_identity"
T_PINMODE = "test_readback_and_pin_mode_logic"
T_RESERVED = "test_reserved_indices_and_remaining_noops"
T_STALL = "test_fixed_stall_is_exact_and_data_independent"
T_FLAGS = "test_no_flag_side_effects"
T_ROUNDTRIP = "test_program_memory_write_read_roundtrip"
T_RUN = "test_written_code_executes_and_run_jumps"
T_CRC = "test_pm_crc_matches_binascii_crc_hqx"
T_I2C = "test_i2c_images_open_drain_preamble"

# (name, what the defect is, file, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("stall-skipped-on-zero-data",
     "WCTL PM_DATA_LO skips its stall cycle when the written byte is 0x00 (data-dependent latency)",
     CORE,
     [("                      pm_addr_r <= pm_addr_r + 8'd1;\n"
       "                      ctl_stall <= 1'b1;",
       "                      pm_addr_r <= pm_addr_r + 8'd1;\n"
       "                      ctl_stall <= (rd_val != 8'h00);", 1)],
     {T_STALL}),
    ("run-falls-through",
     "WCTL RUN stalls its 2 cycles but then fetches pc+1 instead of Rs",
     CORE,
     [("next_addr = stall_run ? rd_val : pc_next;", "next_addr = pc_next;", 1)],
     {T_RUN}),
    ("rctl-sets-z",
     "a 1-cycle RCTL writes the Z flag from the value it read",
     CORE,
     [("                  regs[rd] <= rctl_val;\n",
       "                  regs[rd] <= rctl_val;\n"
       "                  flag_z   <= (rctl_val == 8'h00);\n", 1)],
     {T_FLAGS}),
    ("reserved-read-leaks",
     "a read of an unassigned index returns PM_ADDR instead of 0x00",
     CORE,
     [("default:         rctl_val = 8'h00;", "default:         rctl_val = pm_addr_r;", 1)],
     {T_RESERVED}),
    ("port01-decodes-as-wctl",
     "OUT to the reserved port 01 is decoded as a control write",
     CORE,
     [("wire       is_wctl   = (opcode == OP_OUT) && (rs == PORT_UI_IN);",
       "wire       is_wctl   = (opcode == OP_OUT) && (rs[1] == 1'b0);", 1),
      ("                PORT_UI_IN: begin\n", "                PORT_UI_IN, PORT_UIO_IN: begin\n", 1)],
     {T_RESERVED}),
    ("no-addr-increment-on-read",
     "RCTL PM_DATA_LO does not advance PM_ADDR",
     CORE,
     [("                  if (imm8 == CTL_PM_DATA_LO) begin\n",
       "                  if (1'b0) begin\n", 1)],
     {T_ROUNDTRIP}),
    ("uio-od-resets-enabled",
     "UIO_OD resets to 0x81 instead of 0x00 (pins driven from reset)",
     CORE,
     [("      uio_od       <= 8'h00;", "      uio_od       <= 8'h81;", 1)],
     {T_RESET, T_I2C}),
    ("od-does-not-win",
     "pin mode: UIO_DIR drives a pin push-pull even when UIO_OD selects open-drain",
     TOP,
     [("assign uio_oe = (uio_od & ~uio_out) | (~uio_od & uio_dir);",
       "assign uio_oe = (uio_od & ~uio_out) | uio_dir;", 1)],
     {T_PINMODE}),
    ("crc-wrong-polynomial",
     "PM_CRC uses polynomial 0x8005 (CRC-16/ARC family) instead of 0x1021",
     PMEM,
     [("16'h1021 : 16'h0000", "16'h8005 : 16'h0000", 1)],
     {T_CRC}),
    ("crc-skips-serial-load",
     "PM_CRC covers PM_DATA_LO commits but not the serial load's",
     PMEM,
     [("      if (mem_wen) begin\n        pm_crc <=", "      if (run_wen) begin\n        pm_crc <=", 1)],
     {T_CRC, T_RESET}),
    ("crc-byte-order-swapped",
     "PM_CRC feeds each word low byte first",
     PMEM,
     [("pm_crc <= crc16_word(pm_crc, mem_din);",
       "pm_crc <= crc16_word(pm_crc, {mem_din[7:0], mem_din[15:8]});", 1)],
     {T_CRC}),
    ("pm-write-wrong-address",
     "a run-phase program-memory write lands at the fetch address, not PM_ADDR",
     PMEM,
     [("                          (run_wen || pm_re)   ? pm_addr :",
       "                          pm_re                ? pm_addr :", 1)],
     {T_ROUNDTRIP, T_RUN}),
]


def copy_tree(dst: Path) -> None:
    for name in ("rtl", "src", "firmware", "spec"):
        shutil.copytree(REPO_ROOT / name, dst / name, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "verification", dst / "verification", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "records", ".klt"))


def run_bench(tree: Path) -> dict:
    proc = subprocess.run(
        ["klt", "functional-verification", "verification/request-control-space.json",
         "--format", "json"],
        cwd=tree, capture_output=True, text=True, check=False,
    )
    (tree / "klt-stdout.json").write_text(proc.stdout, encoding="utf-8")
    (tree / "klt-stderr.txt").write_text(proc.stderr, encoding="utf-8")
    try:
        doc = json.loads(proc.stdout)
        tests = {t["name"]: t["status"] for t in doc["tests"]}
    except (ValueError, KeyError, TypeError):
        return {"parsed": False, "rc": proc.returncode, "tests": {}}
    return {"parsed": True, "rc": proc.returncode, "tests": tests}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="directory to keep the per-mutant trees and summary.json in")
    ap.add_argument("--only", help="run just this mutant (the golden run still runs)")
    args = ap.parse_args(argv)

    tmp = None
    if args.out:
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory()
        out = Path(tmp.name)

    ok = True
    summary = {"bench": "verification/test_control_space.py", "runs": []}

    golden = out / "golden"
    shutil.rmtree(golden, ignore_errors=True)
    copy_tree(golden)
    res = run_bench(golden)
    failed = sorted(n for n, s in res["tests"].items() if s != "passed")
    good = res["parsed"] and res["tests"] and not failed
    print(f"{'ok  ' if good else 'FAIL'} golden (unmodified copy): "
          f"{len(res['tests']) - len(failed)}/{len(res['tests'])} passed")
    summary["runs"].append({"kind": "golden", "tests": len(res["tests"]), "failed": failed,
                            "as_required": bool(good)})
    ok = ok and bool(good)

    for name, what, rel, subs, catchers in MUTANTS:
        if args.only and name != args.only:
            continue
        tree = out / name
        shutil.rmtree(tree, ignore_errors=True)
        copy_tree(tree)
        path = tree / rel
        text = path.read_text(encoding="utf-8")
        applied = True
        for old, new, count in subs:
            if text.count(old) != count:
                print(f"FAIL {name}: anchor found {text.count(old)}x, expected {count}x: {old!r}")
                applied = False
                break
            text = text.replace(old, new)
        if not applied:
            summary["runs"].append({"kind": "mutant", "name": name, "as_required": False,
                                    "error": "substitution did not apply"})
            ok = False
            continue
        path.write_text(text, encoding="utf-8")
        res = run_bench(tree)
        failed = sorted(n for n, s in res["tests"].items() if s != "passed")
        caught = res["parsed"] and bool(failed)
        targeted = bool(catchers & set(failed))
        good = caught and targeted
        print(f"{'ok  ' if good else 'FAIL'} {name}: {len(failed)}/{len(res['tests'])} tests failed"
              f"{'' if res['parsed'] else ' (NO PARSED RESULT)'}"
              f"{'' if targeted or not caught else ' (not by the test meant to catch it)'}"
              f" -- {what}")
        summary["runs"].append({
            "kind": "mutant", "name": name, "defect": what, "file": rel,
            "tests": len(res["tests"]), "failed": failed,
            "expected_catchers": sorted(catchers), "as_required": bool(good),
        })
        ok = ok and good

    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print("RESULT: " + ("golden passes and every mutant is caught by its target test" if ok
                        else "NOT as required"))
    if tmp is not None:
        tmp.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
