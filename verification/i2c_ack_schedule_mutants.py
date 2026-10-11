#!/usr/bin/env python3
"""Negative control for the I2C ACK-slot schedule (issue #258): the
ORIGINAL low-phase ACK sampling, assembled into fresh scratch images,
must fail `test_firmware_i2c_ack.test_late_ack_responses_are_read_as_ack`
with an assertion.

Why this exists. Until #258 `i2c_fast.asm` / `i2c_std.asm` sampled each
ACK with an `IN` in the ninth clock's LOW phase, and the I2C benches'
peripheral answered one cycle after the SCL fall, ahead of that sample --
so every bench passed. The late-response regression is the test that can
tell the two schedules apart; this runner is the demonstration that it
does, and that it does so by asserting, not by crashing.

Method (the tree-copying of `control_space_mutants.py`): copy the sources
into a scratch tree; in the copy, replace ONE ACK slot of ONE grade's
committed program with that slot's original text, byte for byte, read
from git at `ORIGINAL_REV` (the last revision with the low-phase
schedule); re-assemble that program with the copy's own assembler into
the copy's `firmware/build/` (a fresh, self-consistent image and cycle
report); run the benches unmodified through `klt functional-verification`.
Required per mutant:

* the assembled original slot really samples in the low phase, at the
  offset `test_firmware_i2c_ack.FORMER_LOW_PHASE_IN_OFFSET` names for that
  grade (re-derived here from the assembled scratch listing);
* `test_firmware_i2c.test_committed_images_are_fresh` PASSES in the copy
  (the scratch image is exactly its source: the failure below is not a
  stale-artifact failure);
* `test_late_ack_responses_are_read_as_ack` is reported FAILED in a parsed
  result, with `error_type` `AssertionError` -- a compile error, a tool
  error or an unparsed result does not count as detection.

The verdicts of the other tests on the mutant (the sibling bench's whole
suite, the early-response runs, the static schedule test) are recorded in
`summary.json` as observations, not requirements. `firmware/` in the
repository is never edited. Each substitution must apply exactly once.

Usage:
    python3 verification/i2c_ack_schedule_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb), `iverilog` and `git` on PATH. One simulation at
a time. Writes `summary.json` and one directory per run under --out
(default: a temporary directory, removed on exit). Exit 0 = the golden run
passed and every mutant was caught as required.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from control_space_mutants import REPO_ROOT, copy_tree  # noqa: E402

#: The last revision of `main` whose I2C write programs sampled ACK in the
#: low phase (origin/main when issue #258 was implemented; the programs
#: themselves last changed at c772542d, issue #125).
ORIGINAL_REV = "b76ec6d4cce124c4a861166029c4707c00276978"

ACK_REQUEST = "verification/request-firmware-i2c-ack.json"
SIBLING_REQUEST = "verification/request-firmware-i2c.json"
T_LATE = "test_late_ack_responses_are_read_as_ack"
T_FRESH = "test_committed_images_are_fresh"

#: One ACK slot's text, in the original and in the current program: the
#: address slot from its low section to the BNZ (the ACK/NACK paths after
#: the BNZ are not part of the slot's schedule), the data slot through the
#: end of its high section.
SLOTS = {
    "addr": re.compile(r"^\.cyclesec i2c_ack1_low\n.*?^        BNZ   stop_from_addr", re.S | re.M),
    "data": re.compile(r"^\.cyclesec i2c_ack2_low\n.*?^\.cyclesec i2c_ack2_high\n.*?^\.endcyclesec[^\n]*\n",
                       re.S | re.M),
}
SECTION = {"addr": "i2c_ack1_low", "data": "i2c_ack2_low"}

# (name, grade program, slot)
MUTANTS = [
    ("fast-addr-ack-low-phase", "i2c_fast", "addr"),
    ("fast-data-ack-low-phase", "i2c_fast", "data"),
    ("std-addr-ack-low-phase", "i2c_std", "addr"),
    ("std-data-ack-low-phase", "i2c_std", "data"),
]


def former_offsets() -> dict:
    """`FORMER_LOW_PHASE_IN_OFFSET` as the bench states it (read with
    `ast`, so this runner needs no cocotb)."""
    tree = ast.parse((REPO_ROOT / "verification" / "test_firmware_i2c_ack.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "FORMER_LOW_PHASE_IN_OFFSET" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise SystemExit("test_firmware_i2c_ack.py has no FORMER_LOW_PHASE_IN_OFFSET")


def original_source(program: str) -> str:
    return subprocess.run(
        ["git", "show", f"{ORIGINAL_REV}:firmware/asm/{program}.asm"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout


def low_phase_in_offsets(tree: Path, program: str, section: str) -> list:
    """Assemble the scratch copy's program with the scratch copy's
    assembler (writing its artifacts into the scratch build dir) and
    return the cycle offsets of every IN inside `section`."""
    subprocess.run([sys.executable, "firmware/tools/asm.py", f"firmware/asm/{program}.asm"],
                   cwd=tree, capture_output=True, text=True, check=True)
    probe = (
        "import sys; sys.path.insert(0, 'firmware/tools'); import asm, json\n"
        f"p = asm.assemble_file('firmware/asm/{program}.asm')\n"
        "by = {i.addr: i for i in p.instructions}\n"
        f"s = next(s for s in p.sections if s.name == '{section}')\n"
        "o, hits = 0, []\n"
        "for a in range(s.start_addr, s.end_addr + 1):\n"
        "    if by[a].mnemonic == 'IN': hits.append(o)\n"
        "    o += by[a].cycles\n"
        "print(json.dumps(hits))\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], cwd=tree,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def run_bench(tree: Path, request: str, tag: str) -> dict:
    proc = subprocess.run(
        ["klt", "functional-verification", request, "--format", "json"],
        cwd=tree, capture_output=True, text=True, check=False,
    )
    (tree / f"klt-{tag}-stdout.json").write_text(proc.stdout, encoding="utf-8")
    (tree / f"klt-{tag}-stderr.txt").write_text(proc.stderr, encoding="utf-8")
    try:
        doc = json.loads(proc.stdout)
        tests = {
            t["name"]: {
                "status": t["status"],
                "error_type": t.get("error_type"),
                "error_message": (t.get("error_message") or "").splitlines()[0][:300]
                if t.get("error_message") else None,
            }
            for t in doc["tests"]
        }
    except (ValueError, KeyError, TypeError):
        return {"parsed": False, "rc": proc.returncode, "tests": {}}
    return {"parsed": True, "rc": proc.returncode, "tests": tests}


def all_passed(res: dict) -> bool:
    return res["parsed"] and bool(res["tests"]) and all(
        t["status"] == "passed" for t in res["tests"].values()
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", help="directory to keep the per-run trees and summary.json in")
    ap.add_argument("--only", help="run just this mutant (the golden run still runs)")
    args = ap.parse_args(argv)

    tmp = None
    if args.out:
        out = Path(args.out).resolve()
        out.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory()
        out = Path(tmp.name)

    former = former_offsets()
    summary = {"benches": [ACK_REQUEST, SIBLING_REQUEST], "original_rev": ORIGINAL_REV,
               "runs": []}

    golden = out / "golden"
    shutil.rmtree(golden, ignore_errors=True)
    copy_tree(golden)
    ack = run_bench(golden, ACK_REQUEST, "ack")
    sib = run_bench(golden, SIBLING_REQUEST, "sibling")
    ok = all_passed(ack) and all_passed(sib)
    print(f"{'ok  ' if ok else 'FAIL'} golden (unmodified copy): "
          f"ack bench {sum(t['status'] == 'passed' for t in ack['tests'].values())}/{len(ack['tests'])}, "
          f"sibling bench {sum(t['status'] == 'passed' for t in sib['tests'].values())}/{len(sib['tests'])} passed")
    summary["runs"].append({"kind": "golden", "ack_bench": ack, "sibling_bench": sib,
                            "as_required": bool(ok)})

    for name, program, slot in MUTANTS:
        if args.only and name != args.only:
            continue
        tree = out / name
        shutil.rmtree(tree, ignore_errors=True)
        copy_tree(tree)
        path = tree / "firmware" / "asm" / f"{program}.asm"
        current = path.read_text(encoding="utf-8")
        orig_hits = SLOTS[slot].findall(original_source(program))
        cur_hits = SLOTS[slot].findall(current)
        if len(orig_hits) != 1 or len(cur_hits) != 1:
            print(f"FAIL {name}: slot found {len(orig_hits)}x in the original, "
                  f"{len(cur_hits)}x in the current source (need 1 and 1)")
            summary["runs"].append({"kind": "mutant", "name": name, "as_required": False,
                                    "error": "substitution did not apply"})
            ok = False
            continue
        path.write_text(current.replace(cur_hits[0], orig_hits[0], 1), encoding="utf-8")
        offsets = low_phase_in_offsets(tree, program, SECTION[slot])
        offsets_ok = offsets == [former[program]]

        ack = run_bench(tree, ACK_REQUEST, "ack")
        sib = run_bench(tree, SIBLING_REQUEST, "sibling")
        late = ack["tests"].get(T_LATE, {})
        fresh = sib["tests"].get(T_FRESH, {})
        caught = (ack["parsed"] and late.get("status") == "failed"
                  and late.get("error_type") == "AssertionError")
        fresh_ok = sib["parsed"] and fresh.get("status") == "passed"
        good = bool(offsets_ok and caught and fresh_ok)
        ok = ok and good
        print(f"{'ok  ' if good else 'FAIL'} {name}: original {SECTION[slot]} IN at offset(s) "
              f"{offsets} (bench states {former[program]}); {T_LATE} "
              f"{late.get('status', 'MISSING')} ({late.get('error_type')}): "
              f"{late.get('error_message')}; {T_FRESH} {fresh.get('status', 'MISSING')}"
              f"{'' if ack['parsed'] else ' (NO PARSED RESULT)'}")
        summary["runs"].append({
            "kind": "mutant", "name": name, "program": f"firmware/asm/{program}.asm",
            "slot": slot, "original_low_phase_in_offsets": offsets,
            "bench_former_offset": former[program], "ack_bench": ack, "sibling_bench": sib,
            "as_required": good,
        })

    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print("RESULT: " + ("golden passes and the late-response regression fails every "
                        "original-schedule mutant with an assertion" if ok else "NOT as required"))
    if tmp is not None:
        tmp.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
