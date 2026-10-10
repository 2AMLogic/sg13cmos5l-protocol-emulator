#!/usr/bin/env python3
"""Negative controls for `test_boot_uart.py` (issue #139, DR 0013 layer 2).

A bench that cannot fail cannot cite its passes. Like
`boot_rom_mutants.py`, this runner copies the sources the bench needs into a
scratch tree, injects ONE defect into the copy of the *generated* boot ROM
(`rtl/protocol_boot_rom.v`) as a changed word, runs the bench on it through
`klt functional-verification`, and requires a test that is meant to catch
that defect to FAIL, by a parsed result and not by a crash. `rtl/`, `src/`
and `firmware/` in the repository are never edited. A ROM mutant also fails
the bench's image-chain test (the ROM no longer matches the committed
image) and that failure does not count.

Each mutant names the addresses it changes in the committed image
(`firmware/build/boot/boot_rom.cycles.txt` lists them) and must apply
exactly as many times as stated, so a later edit to the boot program cannot
silently turn a negative control into a second positive run.

To keep a run affordable each mutant is run against just the tests that are
meant to catch it (the request's `testcase` is narrowed in the copy); the
golden run is the whole bench.

Usage:
    python3 verification/boot_uart_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH, like the bench itself;
`KLT_CMD` overrides the command (for example a `uvx --with cocotb ... klt`
line). Runs one simulation at a time.
Exit 0 = the golden run passed and every mutant was caught as required.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROM = "rtl/protocol_boot_rom.v"
REQUEST = "verification/request-boot-uart.json"

T_NOMINAL = "test_nominal_load_runs_the_image"
T_BAD = "test_bad_images_never_run"
T_TOL = "test_row10_tolerance_edges"


def word(addr, old, new):
    return (f"      8'h{addr:02X}: word = 16'h{old:04X};", f"      8'h{addr:02X}: word = 16'h{new:04X};", 1)


# (name, what the defect is, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("verdict-always-accepts",
     "the trailer comparison's branch is a NOP: every frame is answered 0x06 and run",
     [word(0x3C, 0xE03E, 0x0000)], {T_BAD}),
    ("trailer-high-byte-unchecked",
     "the trailer comparison ORs R0 with itself, so only the low CRC byte is compared",
     [word(0x3A, 0x6100, 0x6000)], {T_BAD}),
    ("crc-not-cleared-at-the-count",
     "the count handler no longer clears PM_CRC, so a retry after a rejected frame carries the "
     "old frame's residue",
     [word(0x7A, 0xA406, 0x0000)], {T_BAD}),
    ("rx-bit-period-wrong",
     "the receiver's bit period is 466 cycles, not 434",
     [word(0x25, 0xB0A3, 0xB0C3)], {T_NOMINAL}),
    ("rx-reads-ui-in-bit-0",
     "the receiver masks ui_in[0] instead of ui_in[1]",
     [word(0x0F, 0x1402, 0x1401)], {T_NOMINAL}),
    ("tx-stop-bit-too-short",
     "the reply's stop bit is padded for 82 cycles, not 171",
     [word(0x53, 0xB0AA, 0xB051)], {T_NOMINAL}),
    ("handover-drops-the-guard-last",
     "the hand-over clears uio_out before UIO_OD and UIO_DIR: for two cycles every uio pin drives low",
     [word(0x68, 0xA000, 0xA300), word(0x69, 0xA001, 0xA000), word(0x6A, 0xA300, 0xA001)],
     {T_NOMINAL}),
]


def klt_command() -> list:
    return shlex.split(os.environ.get("KLT_CMD", "klt"))


def copy_tree(dst: Path) -> None:
    for name in ("rtl", "src", "firmware", "spec"):
        shutil.copytree(REPO_ROOT / name, dst / name, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "verification", dst / "verification", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "records", ".klt"))


def narrow_request(tree: Path, testcases) -> None:
    path = tree / REQUEST
    doc = json.loads(path.read_text(encoding="utf-8"))
    names = sorted(testcases)
    doc["testbench"]["testcase"] = names if len(names) > 1 else names[0]
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def run_bench(tree: Path) -> dict:
    proc = subprocess.run(
        klt_command() + ["functional-verification", REQUEST, "--format", "json"],
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
    ap.add_argument("--skip-golden", action="store_true", help="do not run the whole bench first")
    args = ap.parse_args(argv)

    tmp = None
    if args.out:
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory()
        out = Path(tmp.name)

    ok = True
    summary = {"bench": "verification/test_boot_uart.py", "runs": []}

    if not args.skip_golden:
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

    for name, what, subs, catchers in MUTANTS:
        if args.only and name != args.only:
            continue
        tree = out / name
        shutil.rmtree(tree, ignore_errors=True)
        copy_tree(tree)
        path = tree / ROM
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
        narrow_request(tree, catchers)
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
            "kind": "mutant", "name": name, "defect": what, "file": ROM,
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
