#!/usr/bin/env python3
"""Inventory check for `npm run lint` wiring (issue #296, structural form of #294).

Every git-tracked `**/test_*.py` that is a stdlib self-test (does not import
cocotb; cocotb benches run from verification/request-*.json) must appear as a
command in `scripts/lint-manifest.txt` or in
`scripts/lint-self-test-exemptions.txt` (`<path> :: <reason>`). Also fails on
stale manifest/exemption paths, duplicate or reasonless exemptions, an
exemption for a file that is already in the manifest, a manifest whose first
entry is not the runner self-test, or whose last entry is not the
ratification gate.

Standard library only.

Usage:
    python3 scripts/check_lint_inventory.py [--repo-root DIR]

Exit codes: 0 pass, 1 a check failed.
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_lint  # noqa: E402

DEFAULT_ROOT = run_lint.DEFAULT_ROOT
EXEMPTIONS = "scripts/lint-self-test-exemptions.txt"
FIRST = "scripts/test_run_lint.py"
LAST = "scripts/check_ratification_gate.py"
COCOTB_RE = re.compile(r"^\s*(import cocotb|from cocotb)", re.M)


def parse_exemptions(text: str) -> tuple[dict[str, str], list[str]]:
    ex: dict[str, str] = {}
    errors: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, sep, reason = (s.strip() for s in line.partition("::"))
        if not sep or not path or not reason or " " in path:
            errors.append(f"exemptions line {n}: need '<path> :: <reason>'")
            continue
        if path in ex:
            errors.append(f"exemptions line {n}: {path!r} listed more than once")
        ex[path] = reason
    return ex, errors


def manifest_paths(cmds: list[str]) -> set[str]:
    paths: set[str] = set()
    for c in cmds:
        paths.update(a for a in shlex.split(c) if a.endswith(".py"))
    return paths


def tracked_selftests(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*test_*.py"], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.split()
    res = []
    for p in sorted(out):
        if not Path(p).name.startswith("test_"):
            continue
        if COCOTB_RE.search((root / p).read_text(encoding="utf-8", errors="replace")):
            continue
        res.append(p)
    return res


def check(tests: list[str], cmds: list[str], ex: dict[str, str], root: Path) -> list[str]:
    errors: list[str] = []
    wired = manifest_paths(cmds)
    for t in tests:
        if t not in wired and t not in ex:
            errors.append(f"{t}: stdlib self-test is neither in the lint manifest nor exempted")
    for p in sorted(wired):
        if not (root / p).exists():
            errors.append(f"manifest names missing file {p}")
    for p in ex:
        if p not in tests:
            errors.append(f"exemption {p}: not a tracked stdlib self-test (stale?)")
        elif p in wired:
            errors.append(f"exemption {p}: already in the manifest")
    if cmds:
        if FIRST not in shlex.split(cmds[0]):
            errors.append(f"first manifest entry must run {FIRST}")
        if LAST not in shlex.split(cmds[-1]):
            errors.append(f"last manifest entry must run {LAST}")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", type=Path, default=DEFAULT_ROOT)
    args = ap.parse_args(argv)
    root = args.repo_root
    cmds, errors = run_lint.parse_manifest(
        (root / run_lint.MANIFEST).read_text(encoding="utf-8"))
    ex, ex_errors = parse_exemptions((root / EXEMPTIONS).read_text(encoding="utf-8"))
    errors += ex_errors
    tests = tracked_selftests(root)
    errors += check(tests, cmds, ex, root)
    if errors:
        for e in errors:
            print(f"FAIL {e}", file=sys.stderr)
        return 1
    print(f"lint inventory: {len(tests)} stdlib self-test(s), "
          f"{len(cmds)} manifest entries, {len(ex)} exemption(s): ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
