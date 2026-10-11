#!/usr/bin/env python3
"""Inventory check for the per-PR RTL bench gate (issue #225).

`scripts/rtl-bench-inventory.txt` classifies every `verification/request-*.json`
as `include <name>` (run by scripts/run-rtl-benches.sh) or
`exclude <name> :: <reason>`. This check fails when

  * a request file is in neither list (a new bench cannot be silently omitted),
  * an entry names a request file that no longer exists (stale entry),
  * a name is listed more than once, or an exclusion has no reason,
  * a line is not a recognised directive.

Standard library only.

Usage:
    python3 scripts/check_rtl_bench_inventory.py [--repo-root DIR]
    python3 scripts/check_rtl_bench_inventory.py --list-includes [--repo-root DIR]

Exit codes: 0 pass, 1 a check failed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
INVENTORY = "scripts/rtl-bench-inventory.txt"
REQUEST_RE = re.compile(r"^request-(.+)\.json$")


def parse(text: str) -> tuple[list[str], dict[str, str], list[str]]:
    """Return (includes in order, excludes name->reason, errors)."""
    includes: list[str] = []
    excludes: dict[str, str] = {}
    errors: list[str] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if parts[0] == "include" and len(parts) == 2 and " " not in parts[1]:
            name = parts[1]
            if name in includes or name in excludes:
                errors.append(f"line {n}: {name!r} listed more than once")
            includes.append(name)
        elif parts[0] == "exclude" and len(parts) == 2 and "::" in parts[1]:
            name, reason = (s.strip() for s in parts[1].split("::", 1))
            if not name or " " in name or not reason:
                errors.append(f"line {n}: exclude needs '<name> :: <reason>'")
                continue
            if name in includes or name in excludes:
                errors.append(f"line {n}: {name!r} listed more than once")
            excludes[name] = reason
        else:
            errors.append(f"line {n}: unrecognised directive: {line!r}")
    return includes, excludes, errors


def check(root: Path) -> tuple[list[str], list[str]]:
    inv = root / INVENTORY
    if not inv.is_file():
        return [], [f"{INVENTORY} is missing"]
    includes, excludes, errors = parse(inv.read_text())
    requests = set()
    for p in (root / "verification").glob("request-*.json"):
        m = REQUEST_RE.match(p.name)
        if m:
            requests.add(m.group(1))
    listed = set(includes) | set(excludes)
    for name in sorted(requests - listed):
        errors.append(
            f"verification/request-{name}.json is neither included nor "
            f"excluded in {INVENTORY}"
        )
    for name in sorted(listed - requests):
        errors.append(
            f"{INVENTORY} lists {name!r} but verification/request-{name}.json "
            "does not exist"
        )
    return includes, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--list-includes", action="store_true",
                    help="print the included bench names, one per line")
    args = ap.parse_args(argv)
    includes, errors = check(args.repo_root)
    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    if args.list_includes:
        print("\n".join(includes))
    else:
        print(f"rtl bench inventory ok ({len(includes)} included)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
