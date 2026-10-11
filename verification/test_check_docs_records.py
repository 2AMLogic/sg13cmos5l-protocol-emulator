#!/usr/bin/env python3
"""Self-test for `verification/check_docs_records.py`.

Builds a throwaway records tree (a chain A <- B <- C in one experiment, one
unrelated live record) and a docs directory, then runs the real entry point
as a subprocess. Each violation class must fail; the clean docs must pass.

Usage: python3 verification/test_check_docs_records.py
Exit codes: 0 all cases behave as specified, 1 otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

LINT = Path(__file__).resolve().parent / "check_docs_records.py"
A, B, C = "20261001-000001-aaaaaaa", "20261002-000002-bbbbbbb", "20261003-000003-ccccccc"
OTHER = "20261004-000004-ddddddd"
MISSING = "20261005-000005-eeeeeee"


def write_record(root: Path, exp: str, rid: str, supersedes) -> None:
    d = root / exp / "records"
    d.mkdir(parents=True, exist_ok=True)
    meta = json.dumps({"record_id": rid, "experiment": exp, "supersedes": supersedes})
    (d / f"{rid}.md").write_text(f"<!-- record-meta\n{meta}\n-->\n- **Claim**: x\n")


def link(exp: str, rid: str) -> str:
    return f"[r](../../verification/records/{exp}/records/{rid}.md)"


def run(docs_text: dict) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        rec, docs = tmp / "records", tmp / "docs"
        docs.mkdir()
        write_record(rec, "exp", A, None)
        write_record(rec, "exp", B, A)
        write_record(rec, "exp", C, B)
        write_record(rec, "other", OTHER, None)
        for name, text in docs_text.items():
            (docs / name).write_text(text)
        p = subprocess.run(
            [sys.executable, str(LINT), "--docs", str(docs), "--records", str(rec)],
            capture_output=True, text=True,
        )
        return p.returncode, p.stdout + p.stderr


CASES = [
    ("live record by link passes", {"a.md": link("exp", C) + "\n"}, 0, ""),
    ("live bare id passes", {"a.md": f"see {OTHER} here\n"}, 0, ""),
    ("no citations passes", {"a.md": "nothing\n"}, 0, ""),
    ("superseded by link fails", {"a.md": link("exp", A) + "\n"}, 1, A),
    ("superseded middle of chain fails", {"a.md": f"cites `{B}`\n"}, 1, B),
    ("missing record fails", {"a.md": f"cites {MISSING}\n"}, 1, "not a record"),
    ("marker with reason excuses superseded", {"a.md": f"{link('exp', A)} <!-- superseded-ok: history -->\n"}, 0, ""),
    ("marker without reason fails", {"a.md": f"{link('exp', A)} <!-- superseded-ok: -->\n"}, 1, "needs a reason"),
    ("marker does not excuse a missing record", {"a.md": f"{MISSING} <!-- superseded-ok: history -->\n"}, 1, "not a record"),
    ("marker covers only its own line", {"a.md": f"{link('exp', A)} <!-- superseded-ok: h -->\n{link('exp', B)}\n"}, 1, B),
    ("every doc is scanned", {"a.md": "ok\n", "b.md": link("exp", A) + "\n"}, 1, "b.md:1"),
]


def main() -> int:
    bad = 0
    for name, docs, want_rc, want_text in CASES:
        rc, out = run(docs)
        good = rc == want_rc and want_text in out
        print(("ok:   " if good else "FAIL: ") + name)
        if not good:
            bad += 1
            print(f"      rc={rc} (want {want_rc}); wanted {want_text!r} in:\n{out}")
    # The shipped docs must be clean against the shipped records.
    p = subprocess.run([sys.executable, str(LINT)], capture_output=True, text=True)
    print(("ok:   " if p.returncode == 0 else "FAIL: ") + "shipped docs/submission cite only live records")
    if p.returncode != 0:
        bad += 1
        print(p.stdout)
    print(f"\n{bad} failure(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
