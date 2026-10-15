#!/usr/bin/env python3
"""Negative controls for the pad path of the I2C benches (issue #136,
DR 0012): defects in how the top turns `UIO_OD` / `UIO_DIR` and the
core's port-11 register (`core_uio_out`; DR 0020, issue #244) into
`uio_oe`.

Why this exists. Until #136 the I2C benches composed the bus as `uio_out
AND uio_in` and never read `uio_oe`, so **none** of the defects below
could change their verdict: not one of them touches `uio_out`. They are
the class of fault the silicon-true pad model (`uio_pads.py`) was added
to see, and this runner is the demonstration that it does. The first
mutant is the pre-DR-0012 top itself (`uio_oe = 8'h00`), the design the
old benches passed on and that cannot pull an I2C line low.

Method (the same as `control_space_mutants.py`, via the shared
`_mutant_runner.py`): copy the sources into a scratch tree, inject ONE defect into the
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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mutant_runner import (finish, fresh_tree, open_out, parse_args,  # noqa: E402
                            run_bench as _run_bench)
from control_space_mutants import TOP  # noqa: E402

PIN_MODE = "assign uio_oe  = (uio_od & ~core_uio_out) | (~uio_od & uio_dir);"

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
    ("open-drain-never-releases",
     "an open-drain pin is enabled whatever the port-11 bit is. Its pad data is "
     "0 (DR 0020), so the line is held low and writing 1 never releases it. "
     "(Before DR 0020 this same defect drove the line high: the pad data was "
     "the register bit, and the mutant was named open-drain-drives-high.)",
     "assign uio_oe = uio_od | uio_dir;"),
    ("open-drain-polarity-inverted",
     "an open-drain pin is enabled on a 1 and released on a 0: it can never "
     "pull a line low",
     "assign uio_oe = (uio_od & core_uio_out) | (~uio_od & uio_dir);"),
    ("sda-pad-never-enabled",
     "uio_oe[3] stuck at 0: SCL toggles, SDA is never driven",
     "assign uio_oe = ((uio_od & ~core_uio_out) | (~uio_od & uio_dir)) & 8'hF7;"),
    ("scl-pad-never-enabled",
     "uio_oe[2] stuck at 0: SDA moves, SCL is never driven",
     "assign uio_oe = ((uio_od & ~core_uio_out) | (~uio_od & uio_dir)) & 8'hFB;"),
]


def run_bench(tree: Path, request: str) -> dict:
    return _run_bench(tree, request, tag=Path(request).stem)


def main(argv=None) -> int:
    args = parse_args(__doc__, argv)
    out, tmp = open_out(args.out)

    ok = True
    summary = {"benches": sorted(BENCHES), "pin_mode_anchor": PIN_MODE, "runs": []}

    golden = fresh_tree(out, "golden")
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
        tree = fresh_tree(out, name)
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

    return finish(out, tmp, summary, ok, "golden passes and every pad-path mutant is caught by both benches")


if __name__ == "__main__":
    sys.exit(main())
