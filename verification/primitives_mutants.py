#!/usr/bin/env python3
"""Negative controls for `test_primitives.py` (issue #208, DR 0015 P1/P2).

A bench that cannot fail cannot cite its passes. This runner copies the
sources the bench needs into a scratch tree, injects ONE defect into the
copy of `rtl/protocol_core.v`, runs the unmodified bench on it through
`klt functional-verification`, and requires the bench to FAIL -- by a
parsed result with at least one failed test, not by a crash -- and to fail
in at least one of the tests named as that defect's catchers (so a defect
caught only by accident does not count). `rtl/` and `src/` in the
repository are never edited.

Each defect is an exact-text substitution whose anchor must appear exactly
as often as stated, so a later RTL edit cannot silently turn a negative
control into a second positive run. Same mechanics as
`control_space_mutants.py`, which this file copies.

Usage:
    python3 verification/primitives_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH. Writes `summary.json` and
one directory per mutant under --out (default: a temporary directory).
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

T_CHECK = "test_crc_catalogue_check_values"
T_RANDOM = "test_crc_random_messages"
T_BITS = "test_crc_bit_steps"
T_LFSR = "test_lfsr_prbs"
T_REGS = "test_crc_registers_pointer_and_masking"
T_USB = "test_line_usb_nrzi_stuff6"
T_HDLC = "test_line_hdlc_stuff5"
T_CAN = "test_line_can_stuff5_equal"
T_LINEREG = "test_line_stuff_slot_ignores_rs_and_registers"
T_LAT = "test_fixed_latency_is_data_independent"
T_FLAGS = "test_no_flag_side_effects_and_unassigned"

# (name, what the defect is, file, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("crc-byte-latency-data-dependent",
     "WCTL CRC_BYTE stalls 1 cycle instead of 8 when Rs is 0x00 (data-dependent latency)",
     CORE,
     [("                      wait_cnt <= 8'd8;\n",
       "                      wait_cnt <= (rd_val == 8'h00) ? 8'd1 : 8'd8;\n", 1)],
     {T_LAT}),
    ("crc-byte-seven-bits",
     "WCTL CRC_BYTE stalls (and steps) 7 cycles instead of 8",
     CORE,
     [("                      wait_cnt <= 8'd8;\n", "                      wait_cnt <= 8'd7;\n", 1)],
     {T_CHECK, T_RANDOM, T_LAT}),
    ("crc-byte-bit-order-fixed",
     "CRC_BYTE feeds Rs MSB first in reflected mode too",
     CORE,
     [("  wire [2:0] crc_j    = crc_refl ? ~crc_j0 : crc_j0;",
       "  wire [2:0] crc_j    = crc_j0;", 1)],
     {T_CHECK, T_RANDOM}),
    ("crc-tap-ignores-width",
     "the normal-mode feedback taps bit 31 instead of bit W-1",
     CORE,
     [("(crc_refl ? crc_state[0] : crc_state[crc_wm1])",
       "(crc_refl ? crc_state[0] : crc_state[31])", 1)],
     {T_CHECK, T_RANDOM, T_BITS, T_LFSR}),
    ("crc-reflected-shift-unmasked",
     "the reflected step shifts state bits from above the width into bit W-1",
     CORE,
     [("((crc_state & crc_mask) >> 1)", "(crc_state >> 1)", 1)],
     {T_REGS}),
    ("crc-next-not-inverted",
     "CRC_NEXT ignores the read-out inversion bit",
     CORE,
     [("(crc_state_b ^ {8{crc_inv}}) & crc_mask_b", "crc_state_b & crc_mask_b", 1)],
     {T_CHECK, T_RANDOM, T_REGS}),
    ("crc-cfg-keeps-pointer",
     "a CRC_CFG write does not rewind the byte pointer",
     CORE,
     [("                      crc_inv  <= rd_val[6];\n                      crc_ptr  <= 2'd0;\n",
       "                      crc_inv  <= rd_val[6];\n", 1)],
     {T_REGS, T_LFSR}),
    ("crc-bit-reads-bit7",
     "CRC_BIT takes its data bit from Rs[7] instead of Rs[0]",
     CORE,
     [("crc_busy ? rd_val[crc_j] : rd_val[0];", "crc_busy ? rd_val[crc_j] : rd_val[7];", 1)],
     {T_BITS, T_LFSR}),
    ("crc-state-reset-nonzero",
     "CRC_STATE resets to 0x00000001 instead of 0",
     CORE,
     [("      crc_state    <= 32'h0000_0000;", "      crc_state    <= 32'h0000_0001;", 1)],
     {T_REGS}),
    ("line-stuff-one-late",
     "P2 stuffs after N+1 bits instead of N",
     CORE,
     [("(line_cnt == line_cfg[6:4])", "(line_cnt == line_cfg[6:4] + 3'd1)", 1)],
     {T_USB, T_HDLC, T_CAN, T_LINEREG}),
    ("line-stuff-slot-emits-data",
     "a stuff slot emits Rs[0] (and still flags LINE_STUF) instead of the stuff bit",
     CORE,
     [("line_due ? (line_equal & ~line_prev) : rd_val[0]", "rd_val[0]", 1)],
     {T_USB, T_HDLC, T_CAN, T_LINEREG}),
    ("line-nrzi-wrong-polarity",
     "NRZI mode 01 toggles on a 1 instead of a 0",
     CORE,
     [("(line_lvl ^ ~line_e) :  // toggle on 0", "(line_lvl ^ line_e) :  // toggle on 0", 1)],
     {T_USB, T_LINEREG}),
    ("line-equal-run-restarts-at-zero",
     "the equal-bits rule restarts its run at 0 instead of 1 on a change",
     CORE,
     [("{2'b00, ~line_ones}", "3'd0", 1)],
     {T_CAN, T_LINEREG}),
    ("line-put-writes-z",
     "WCTL LINE_PUT writes the Z flag from the emitted bit",
     CORE,
     [("                      line_stuf <= line_due;\n",
       "                      line_stuf <= line_due;\n                      flag_z    <= line_e;\n", 1)],
     {T_FLAGS}),
]


def copy_tree(dst: Path) -> None:
    for name in ("rtl", "src", "firmware", "spec"):
        shutil.copytree(REPO_ROOT / name, dst / name, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "verification", dst / "verification", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "records", ".klt"))


def run_bench(tree: Path) -> dict:
    proc = subprocess.run(
        ["klt", "functional-verification", "verification/request-primitives.json",
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
    summary = {"bench": "verification/test_primitives.py", "runs": []}

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
