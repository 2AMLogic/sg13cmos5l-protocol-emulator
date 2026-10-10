#!/usr/bin/env python3
"""Negative controls for `test_isa_lockstep.py` (issue #152).

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
    python3 verification/isa_lockstep_mutants.py [--out DIR] [--only NAME]

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

T_LOCK = "test_isa_lockstep_random_programs"
T_SUBPIN = "test_sub_carry_polarity_pin"

# (name, what the defect is, file, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("sub-carry-polarity-flipped",
     "SUB writes C as 'no borrow' instead of the borrow convention the model pins (open detail)",
     CORE,
     [("flag_c   <= sub_diff[8];  // borrow", "flag_c   <= ~sub_diff[8];  // borrow", 1)],
     {T_LOCK, T_SUBPIN}),
    ("shf-direction-swapped",
     "SHF shifts left when Rs[0] = 0 and right when 1",
     CORE,
     [("wire       shf_left = rs[0];", "wire       shf_left = ~rs[0];", 1)],
     {T_LOCK}),
    ("bz-bnz-swapped",
     "BZ branches when Z = 0 and BNZ when Z = 1",
     CORE,
     [("OP_BZ:   next_addr = flag_z  ? imm8 : pc_next;", "OP_BZ:   next_addr = !flag_z ? imm8 : pc_next;", 1),
      ("OP_BNZ:  next_addr = !flag_z ? imm8 : pc_next;", "OP_BNZ:  next_addr = flag_z  ? imm8 : pc_next;", 1)],
     {T_LOCK}),
    ("wait-off-by-one",
     "WAIT n stalls n+2 cycles instead of n+1",
     CORE,
     [("                waiting  <= 1'b1;\n                wait_cnt <= imm8;",
       "                waiting  <= 1'b1;\n                wait_cnt <= imm8 + 8'd1;", 1)],
     {T_LOCK}),
    ("add-carry-dropped",
     "ADD never sets C",
     CORE,
     [("flag_c   <= add_sum[8];", "flag_c   <= 1'b0;", 1)],
     {T_LOCK}),
    ("and-clears-c",
     "AND clears C (DR 0001: AND sets Z only; C is unchanged)",
     CORE,
     [("regs[rd] <= and_res;\n              flag_z   <= (and_res == 8'h00);",
       "regs[rd] <= and_res;\n              flag_z   <= (and_res == 8'h00);\n              flag_c   <= 1'b0;", 1)],
     {T_LOCK}),
    ("halt-does-not-hold-pc",
     "after HALT the fetch address keeps advancing",
     CORE,
     [("next_addr = pc;                                  // HALT: hold forever",
       "next_addr = pc_next;", 1)],
     {T_LOCK}),
    ("reserved-in-port-reads-uio",
     "IN from the reserved port 11 reads uio_in instead of being a no-op",
     CORE,
     [("wire       in_readable = (rs == PORT_UI_IN) || (rs == PORT_UIO_IN);",
       "wire       in_readable = (rs == PORT_UI_IN) || (rs == PORT_UIO_IN) || (rs == PORT_UIO_OUT);", 1)],
     {T_LOCK}),
]


def copy_tree(dst: Path) -> None:
    for name in ("rtl", "src", "firmware", "spec"):
        shutil.copytree(REPO_ROOT / name, dst / name, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "verification", dst / "verification", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "records", ".klt"))


def run_bench(tree: Path) -> dict:
    proc = subprocess.run(
        ["klt", "functional-verification", "verification/request-isa-lockstep.json",
         "--format", "json"],
        cwd=tree, capture_output=True, text=True, check=False,
    )
    (tree / "klt-stdout.json").write_text(proc.stdout, encoding="utf-8")
    (tree / "klt-stderr.txt").write_text(proc.stderr, encoding="utf-8")
    log = tree / "verification" / ".klt" / "functional-verification" / "test_icarus.log"
    first = ""
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if "ISA LOCKSTEP MISMATCH" in line or "OPEN DETAIL" in line:
                first = " | ".join(x.strip() for x in lines[i:i + 3])
                break
    try:
        doc = json.loads(proc.stdout)
        tests = {t["name"]: t["status"] for t in doc["tests"]}
    except (ValueError, KeyError, TypeError):
        return {"parsed": False, "rc": proc.returncode, "tests": {}, "first": first}
    return {"parsed": True, "rc": proc.returncode, "tests": tests, "first": first}


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
    summary = {"bench": "verification/test_isa_lockstep.py", "runs": []}

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
        if res.get("first"):
            print(f"       first mismatch: {res['first'][:420]}")
        summary["runs"].append({
            "kind": "mutant", "name": name, "defect": what, "file": rel,
            "tests": len(res["tests"]), "failed": failed,
            "expected_catchers": sorted(catchers), "as_required": bool(good),
            "first_mismatch": res.get("first", ""),
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
