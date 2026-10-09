#!/usr/bin/env python3
"""Negative controls for the pad path of the I2C benches (issue #136,
DR 0012): defects in how the top turns `UIO_OD` / `UIO_DIR` / `uio_out`
into `uio_oe`.

Why this exists. Until #136 the I2C benches composed the bus as `uio_out
AND uio_in` and never read `uio_oe`, so **none** of the defects below
could change their verdict: not one of them touches `uio_out`. They are
the class of fault the silicon-true pad model (`uio_pads.py`) was added
to see, and this runner is the demonstration that it does. The first
mutant is the pre-DR-0012 top itself (`uio_oe = 8'h00`), the design the
old benches passed on and that cannot pull an I2C line low.

Method (the same as `control_space_mutants.py`, whose tree-copying it
reuses): copy the sources into a scratch tree, inject ONE defect into the
copy of the top, run the unmodified benches on it through `klt
functional-verification`, and require each bench to FAIL -- by a parsed
result with a failed test from the set that exists to catch it, not by a
crash. `rtl/` and `src/` in the repository are never edited. Each defect
is an exact-text substitution that must apply exactly once, so a later
RTL edit cannot silently turn a negative control into a positive run.

The benches' own in-simulation negative control (`UIO_OD` left at reset,
by mutating the *image*) covers the firmware side of the same question;
this runner covers the hardware side.

Usage:
    python3 verification/uio_pad_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH, like the benches. Runs
one simulation at a time. Writes `summary.json` and one directory per
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_space_mutants import TOP, copy_tree  # noqa: E402

PIN_MODE = "assign uio_oe = (uio_od & ~uio_out) | (~uio_od & uio_dir);"

#: request -> the tests that run committed programs on the pads and must
#: therefore notice a broken pad path.
BENCHES = {
    "verification/request-firmware-i2c.json": {
        "test_i2c_both_grades_pass_independent_reference_model",
    },
    "verification/request-firmware-i2c-sr.json": {
        "test_sr_exact_programs_pass_model_with_negative_controls",
        "test_sr_poll_programs_stretch",
    },
}

# (name, what the defect is, replacement for the pin-mode assign)
MUTANTS = [
    ("oe-fixed-at-zero",
     "the pre-DR-0012 top: uio_oe = 8'h00, no pad ever drives (the design the "
     "bench-composed evidence was minted on)",
     "assign uio_oe = 8'h00;"),
    ("open-drain-drives-high",
     "an open-drain pin is enabled whatever uio_out is, so writing 1 drives "
     "the line high instead of releasing it (push-pull on an I2C bus)",
     "assign uio_oe = uio_od | uio_dir;"),
    ("open-drain-polarity-inverted",
     "an open-drain pin is enabled on a 1 and released on a 0: it can never "
     "pull a line low",
     "assign uio_oe = (uio_od & uio_out) | (~uio_od & uio_dir);"),
    ("sda-pad-never-enabled",
     "uio_oe[7] stuck at 0: SCL toggles, SDA is never driven",
     "assign uio_oe = ((uio_od & ~uio_out) | (~uio_od & uio_dir)) & 8'h7F;"),
    ("scl-pad-never-enabled",
     "uio_oe[0] stuck at 0: SDA moves, SCL is never driven",
     "assign uio_oe = ((uio_od & ~uio_out) | (~uio_od & uio_dir)) & 8'hFE;"),
]


def run_bench(tree: Path, request: str) -> dict:
    proc = subprocess.run(
        ["klt", "functional-verification", request, "--format", "json"],
        cwd=tree, capture_output=True, text=True, check=False,
    )
    stem = Path(request).stem
    (tree / f"klt-{stem}-stdout.json").write_text(proc.stdout, encoding="utf-8")
    (tree / f"klt-{stem}-stderr.txt").write_text(proc.stderr, encoding="utf-8")
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
    summary = {"benches": sorted(BENCHES), "pin_mode_anchor": PIN_MODE, "runs": []}

    golden = out / "golden"
    shutil.rmtree(golden, ignore_errors=True)
    copy_tree(golden)
    for request in BENCHES:
        res = run_bench(golden, request)
        failed = sorted(n for n, s in res["tests"].items() if s != "passed")
        good = bool(res["parsed"] and res["tests"] and not failed)
        print(f"{'ok  ' if good else 'FAIL'} golden {Path(request).stem}: "
              f"{len(res['tests']) - len(failed)}/{len(res['tests'])} passed")
        summary["runs"].append({"kind": "golden", "request": request,
                                "tests": len(res["tests"]), "failed": failed,
                                "as_required": good})
        ok = ok and good

    for name, what, replacement in MUTANTS:
        if args.only and name != args.only:
            continue
        tree = out / name
        shutil.rmtree(tree, ignore_errors=True)
        copy_tree(tree)
        path = tree / TOP
        text = path.read_text(encoding="utf-8")
        if text.count(PIN_MODE) != 1:
            print(f"FAIL {name}: pin-mode anchor found {text.count(PIN_MODE)}x, expected 1x")
            summary["runs"].append({"kind": "mutant", "name": name, "as_required": False,
                                    "error": "substitution did not apply"})
            ok = False
            continue
        path.write_text(text.replace(PIN_MODE, replacement), encoding="utf-8")
        for request, catchers in BENCHES.items():
            res = run_bench(tree, request)
            failed = sorted(n for n, s in res["tests"].items() if s != "passed")
            caught = res["parsed"] and bool(failed)
            targeted = bool(catchers & set(failed))
            good = bool(caught and targeted)
            print(f"{'ok  ' if good else 'FAIL'} {name} / {Path(request).stem}: "
                  f"{len(failed)}/{len(res['tests'])} tests failed"
                  f"{'' if res['parsed'] else ' (NO PARSED RESULT)'}"
                  f"{'' if targeted or not caught else ' (not by a test meant to catch it)'}")
            summary["runs"].append({
                "kind": "mutant", "name": name, "defect": what, "file": TOP,
                "replacement": replacement, "request": request,
                "tests": len(res["tests"]), "failed": failed,
                "expected_catchers": sorted(catchers), "as_required": good,
            })
            ok = ok and good

    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print("RESULT: " + ("golden passes and every pad-path mutant is caught by both benches"
                        if ok else "NOT as required"))
    if tmp is not None:
        tmp.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
