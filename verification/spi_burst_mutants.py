#!/usr/bin/env python3
"""Negative controls for the multi-byte SPI burst (issue #286, target-spec
row 11's multi-byte caveat): `test_firmware_spi_burst.py`'s
`test_mode0_three_byte_burst_under_one_cs`.

A bench that cannot fail cannot cite its passes. Following
`boot_spi_mutants.py`, this runner copies the sources the bench needs into
a scratch tree, injects ONE defect into the copy of
`firmware/asm/spi_mode0_burst3.asm`, rebuilds the copy's image with
`firmware/tools/asm.py`, and runs the UNMODIFIED bench on it through
`klt functional-verification`, requiring a parsed result with at least one
failed test, including the test meant to catch that defect. `firmware/`,
`rtl/` and `src/` in the repository are never edited. Each substitution
must apply exactly as many times as stated, so a later edit to the
program cannot silently turn a negative control into a second positive
run.

The defects are all at a byte boundary of the one-CS burst (the place a
bit-banged controller most plausibly loses a bit or the f_clk/4 cadence):
a bit dropped, a bit repeated (at each of the two boundaries), and one
extra cycle of inter-byte gap.

Usage:
    python3 verification/spi_burst_mutants.py [--out DIR] [--only NAME]

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
ASM = "firmware/asm/spi_mode0_burst3.asm"
REQUEST = "verification/request-firmware-spi-burst.json"

T_BURST = "test_mode0_three_byte_burst_under_one_cs"


def bit_block(byte: int, bit: int, img: str, mosi: int) -> str:
    """The four source lines of one bit, exactly as the committed program has them."""
    return (
        f"        LDI   R2, {img}          ; byte {byte} bit {bit}: SCLK active + MOSI {mosi}\n"
        f"        OUT   UIO_OUT, R2       ; byte {byte} bit {bit} leading edge (sampling edge)\n"
        f"        IN    R3, UIO_IN        ; byte {byte} bit {bit} sample MISO\n"
        f"        OUT   UIO_OUT, R1       ; byte {byte} bit {bit} trailing edge (static image)\n"
    )


# 0xA5 = 1010 0101 -> byte 0 bit 7 is a 1 (0x0A); 0x3C = 0011 1100 -> byte 1
# bit 7 is a 0 (0x08); byte 1 bit 0 is a 0 (0x08); byte 2 (0xD2) bit 0 is a 1.
B0_LAST = bit_block(0, 7, "0x0A", 1)
B1_LAST = bit_block(1, 7, "0x08", 0)
B1_FIRST = bit_block(1, 0, "0x08", 0)

# (name, what the defect is, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("drop-bit-at-boundary-0-1",
     "the last bit of byte 0 is not clocked: 23 SCLK periods, every later bit shifts one place",
     [(B0_LAST, "", 1)],
     {T_BURST}),
    ("repeat-bit-at-boundary-0-1",
     "the last bit of byte 0 is clocked twice: 25 SCLK periods, every later bit shifts one place",
     [(B0_LAST, B0_LAST + B0_LAST, 1)],
     {T_BURST}),
    ("drop-bit-at-boundary-1-2",
     "the last bit of byte 1 is not clocked",
     [(B1_LAST, "", 1)],
     {T_BURST}),
    ("repeat-bit-at-boundary-1-2",
     "the last bit of byte 1 is clocked twice",
     [(B1_LAST, B1_LAST + B1_LAST, 1)],
     {T_BURST}),
    ("extra-cycle-between-bytes",
     "one NOP between byte 0 and byte 1: the inter-byte SCLK gap is 3 cycles, not the 2-cycle half-period",
     [(B1_FIRST, "        NOP                     ; MUTANT: one extra cycle at the byte boundary\n" + B1_FIRST, 1)],
     {T_BURST}),
]


def copy_tree(dst: Path) -> None:
    for name in ("rtl", "src", "firmware", "spec"):
        shutil.copytree(REPO_ROOT / name, dst / name, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "verification", dst / "verification", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "records", ".klt"))


def rebuild(tree: Path) -> None:
    cmd = [sys.executable, "firmware/tools/asm.py", ASM, "--out-dir", "firmware/build"]
    proc = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd}: {proc.stderr[-400:]}")


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
    summary = {"bench": "verification/test_firmware_spi_burst.py", "runs": []}

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
        path = tree / ASM
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
        try:
            rebuild(tree)
        except RuntimeError as err:
            print(f"FAIL {name}: the mutated program does not build: {err}")
            summary["runs"].append({"kind": "mutant", "name": name, "as_required": False, "error": str(err)})
            ok = False
            continue
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
            "kind": "mutant", "name": name, "defect": what, "file": ASM,
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
