#!/usr/bin/env python3
"""Fail if a TinyTapeout/tt-gds-action reference is not an immutable SHA pin.

Submission risk R2 (docs/submission/README.md): a branch ref such as
`@ihp-cmos5l` floats, so an upstream push silently changes the sign-off flow.
Every `uses:` whose value starts with `TinyTapeout/tt-gds-action` (the root
action and any sub-path such as `/precheck` or `/fpga/ice40up5k`, one family)
must carry a full lowercase 40-hex commit SHA, and all of them must carry the
same SHA.

What it checks
    Scans `.github/workflows/*.yml` and `*.yaml`. Commented-out lines are
    ignored; `uses:` in a list item (`- uses:`), with or without quotes, is
    checked. Uppercase hex is rejected (git prints lowercase; one spelling).
    Zero matching refs is a failure, so a renamed action cannot make the
    lint pass vacuously.

Limit
    Only our own reference is pinned. The composite actions at that SHA call
    floating refs of their own (actions/checkout@v6 and others); this check
    does not and cannot freeze those.

Usage
    python3 scripts/check_action_pins.py

Standard library only. Exit codes: 0 pass, 1 a ref failed, 2 usage or IO error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_REL = ".github/workflows"
FAMILY = "TinyTapeout/tt-gds-action"

_USES_RE = re.compile(
    r"""^\s*(?:-\s+)?uses:\s*["']?(?P<action>""" + re.escape(FAMILY) + r"""[^@\s"'#]*)(?:@(?P<ref>[^\s"'#]*))?"""
)
_SHA_RE = re.compile(r"[0-9a-f]{40}")


def find_refs(workflows: Path) -> list[tuple[str, int, str]]:
    """Return (relative path, line number, ref) for every family reference."""
    refs = []
    files = sorted(list(workflows.glob("*.yml")) + list(workflows.glob("*.yaml")))
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _USES_RE.match(line)
            if m:
                refs.append((f"{WORKFLOWS_REL}/{path.name}", n, m.group("ref") or ""))
    return refs


def check(workflows: Path) -> list[str]:
    """Return failure messages (`path:line` plus a reason); empty means pass."""
    refs = find_refs(workflows)
    if not refs:
        return [f"{WORKFLOWS_REL}: no {FAMILY} reference found (renamed action?)"]
    failures = [
        f"{p}:{n}: ref is not a 40-hex lowercase commit SHA"
        for p, n, ref in refs
        if not _SHA_RE.fullmatch(ref)
    ]
    valid = {ref for _, _, ref in refs if _SHA_RE.fullmatch(ref)}
    if len(valid) > 1:
        for p, n, ref in refs:
            if _SHA_RE.fullmatch(ref):
                failures.append(f"{p}:{n}: refs do not all share one SHA")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    workflows = args.repo / WORKFLOWS_REL
    try:
        failures = check(workflows)
        count = len(find_refs(workflows))
    except OSError as exc:
        print(f"ERROR: cannot read workflows: {exc}", file=sys.stderr)
        return 2
    if failures:
        print("FAIL: tt-gds-action refs must be one full commit SHA (R2):", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print(f"OK: {count} {FAMILY} refs, all pinned to one commit SHA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
