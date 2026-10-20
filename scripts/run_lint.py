#!/usr/bin/env python3
"""Manifest-driven lint runner behind `npm run lint` (issue #296).

Reads `scripts/lint-manifest.txt` (one command per line, `#` comments), runs
every entry serially from the repo root -- a failure does not stop later
entries -- prints a per-check PASS/FAIL line with elapsed time, and exits
non-zero if any entry failed. Standard library only.

Usage:
    python3 scripts/run_lint.py [--manifest FILE] [--repo-root DIR]

Exit codes: 0 all passed, 1 one or more failed (or bad manifest).
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = "scripts/lint-manifest.txt"


def parse_manifest(text: str) -> tuple[list[str], list[str]]:
    """Return (commands in order, errors)."""
    cmds: list[str] = []
    errors: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            shlex.split(line)
        except ValueError as e:
            errors.append(f"line {n}: unparseable command ({e}): {line!r}")
            continue
        cmds.append(line)
    return cmds, errors


def run_all(cmds: list[str], root: Path) -> list[tuple[str, bool, float]]:
    results = []
    for cmd in cmds:
        print(f"==> {cmd}", flush=True)
        t0 = time.monotonic()
        try:
            ok = subprocess.run(shlex.split(cmd), cwd=root).returncode == 0
        except OSError as e:
            print(f"cannot run: {e}", file=sys.stderr)
            ok = False
        dt = time.monotonic() - t0
        print(f"{'PASS' if ok else 'FAIL'} ({dt:.1f}s) {cmd}", flush=True)
        results.append((cmd, ok, dt))
    return results


def summarize(results: list[tuple[str, bool, float]]) -> int:
    failed = [c for c, ok, _ in results if not ok]
    total = sum(dt for _, _, dt in results)
    print(f"\nlint: {len(results) - len(failed)}/{len(results)} passed in {total:.1f}s")
    for c in failed:
        print(f"  FAIL {c}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--manifest", type=Path, default=None)
    args = ap.parse_args(argv)
    root = args.repo_root
    path = args.manifest or root / MANIFEST
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"run_lint: cannot read manifest: {e}", file=sys.stderr)
        return 1
    cmds, errors = parse_manifest(text)
    if errors or not cmds:
        for e in errors or ["manifest has no commands"]:
            print(f"run_lint: {e}", file=sys.stderr)
        return 1
    return summarize(run_all(cmds, root))


if __name__ == "__main__":
    sys.exit(main())
