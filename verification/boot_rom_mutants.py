#!/usr/bin/env python3
"""Negative controls for `test_boot_rom.py` (issue #138, DR 0013 layer 2).

A bench that cannot fail cannot cite its passes. Like
`control_space_mutants.py`, this runner copies the sources the bench needs
into a scratch tree, injects ONE defect into the copy, runs the unmodified
bench on it through `klt functional-verification`, and requires the bench
to FAIL -- by a parsed result with at least one failed test, not by a
crash. `rtl/`, `src/` and `firmware/` in the repository are never edited.

Two kinds of defect:

- in the RTL (`rtl/protocol_core.v`, `rtl/protocol_program_memory.v`): the
  fetch-source switch and the macro read gate;
- in the boot program, injected into the copy of the *generated* ROM
  (`rtl/protocol_boot_rom.v`) as a changed word. A ROM mutant also fails
  the bench's image-chain test, by construction (the ROM no longer matches
  the committed image); that failure does not count. Each mutant names the
  behavioural tests that exist to catch it, and one of those must fail.

Each substitution must apply exactly as many times as stated, so a later
edit to the RTL or to the boot program cannot silently turn a negative
control into a second positive run.

Usage:
    python3 verification/boot_rom_mutants.py [--out DIR] [--only NAME]

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
ROM = "rtl/protocol_boot_rom.v"
REQUEST = "verification/request-boot-rom.json"

T_STUB = "test_stub_straps_idle_on_unwritten_memory"
T_UNVERIFIED = "test_mode_low_never_runs_unverified_memory"
T_WARM = "test_warm_start_runs_a_verified_image"
T_CORRUPT = "test_warm_start_rejects_corrupted_images"

# (name, what the defect is, file, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("rom-never-selected",
     "the core always decodes program memory: MODE low at reset runs whatever the array holds "
     "(the pre-DR-0013 behaviour, target-spec row 14 (c))",
     CORE,
     [("  assign      fetch_rom = !serial_loaded && !rom_exit;",
       "  assign      fetch_rom = 1'b0;", 1)],
     {T_UNVERIFIED}),
    ("run-does-not-leave-rom",
     "WCTL RUN jumps but the fetch source stays the boot ROM",
     CORE,
     [("            rom_exit <= 1'b1;", "            rom_exit <= 1'b0;", 1)],
     {T_WARM}),
    ("run-target-not-fetched-from-memory",
     "the fetch presented in RUN's stall cycle is not a program-memory fetch: the first word "
     "executed after leaving the ROM is whatever the macro last read",
     CORE,
     [("  assign pm_fetch   = !fetch_rom || (ctl_stall && stall_run);",
       "  assign pm_fetch   = !fetch_rom;", 1)],
     {T_WARM}),
    ("boot-status-bit1-stuck",
     "BOOT_STATUS[1] reads 1 whatever the fetch source is",
     CORE,
     [("CTL_BOOT_STATUS: rctl_val = {6'b000000, fetch_rom, serial_loaded};",
       "CTL_BOOT_STATUS: rctl_val = {6'b000000, 1'b1, serial_loaded};", 1)],
     {T_WARM}),
    ("macro-read-not-gated",
     "the macro is read for fetch while the boot ROM is the source (invisible at the pins: "
     "caught by the white-box read-enable check)",
     PMEM,
     [("  wire        mem_ren   = !load_active && !run_wen && (fetch_en || pm_re);",
       "  wire        mem_ren   = !load_active && !run_wen;", 1)],
     {T_STUB, T_UNVERIFIED}),
    ("warm-start-skips-verdict",
     "boot program: the branch on the CRC verdict is a NOP, so every image is run",
     ROM,
     [("      8'h18: word = 16'hE009;", "      8'h18: word = 16'h0000;", 1)],
     {T_UNVERIFIED, T_CORRUPT}),
    ("verdict-ignores-crc-high-byte",
     "boot program: the verdict tests PM_CRC_LO only (OR R1, R1 for OR R0, R1)",
     ROM,
     [("      8'h17: word = 16'h6100;", "      8'h17: word = 16'h6500;", 1)],
     {T_CORRUPT}),
    ("verdict-ignores-crc-low-byte",
     "boot program: the verdict tests PM_CRC_HI only (OR R0, R0 for OR R0, R1)",
     ROM,
     [("      8'h17: word = 16'h6100;", "      8'h17: word = 16'h6000;", 1)],
     {T_CORRUPT}),
    ("straps-01-and-10-swapped",
     "boot program: strap 01 warm-starts and strap 10 goes to the SPI-flash boot",
     ROM,
     [("      8'h03: word = 16'h1440;", "      8'h03: word = 16'h1420;", 1),
      ("      8'h06: word = 16'h1420;", "      8'h06: word = 16'h1440;", 1)],
     {T_WARM}),
    ("handover-leaves-z-set",
     "boot program: the handover does not restore Z (OR R3, R3 is a NOP), so the image starts "
     "with Z = 1 instead of the reset value",
     ROM,
     [("      8'h19: word = 16'h6F00;", "      8'h19: word = 16'h0000;", 1)],
     {T_WARM}),
]


def copy_tree(dst: Path) -> None:
    for name in ("rtl", "src", "firmware", "spec"):
        shutil.copytree(REPO_ROOT / name, dst / name, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "verification", dst / "verification", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "records", ".klt"))


def run_bench(tree: Path) -> dict:
    proc = subprocess.run(
        ["klt", "functional-verification", REQUEST, "--format", "json"],
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
    summary = {"bench": "verification/test_boot_rom.py", "runs": []}

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
              f"{'' if targeted or not caught else ' (not by a test meant to catch it)'}"
              f" -- {what}")
        summary["runs"].append({
            "kind": "mutant", "name": name, "defect": what, "file": rel,
            "tests": len(res["tests"]), "failed": failed,
            "expected_catchers": sorted(catchers), "as_required": bool(good),
        })
        ok = ok and good

    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print("RESULT: " + ("golden passes and every mutant is caught by a test meant to catch it"
                        if ok else "NOT as required"))
    if tmp is not None:
        tmp.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
