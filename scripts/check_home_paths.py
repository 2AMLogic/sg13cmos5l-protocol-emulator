#!/usr/bin/env python3
"""Fail on a committed file that contains an absolute home-directory path.

This is a public repository. A path such as `/Users/<name>/...` or
`/home/<name>/...` written into a record or artifact by the machine that
produced it publishes an account name and a directory layout, and makes the
artifact non-reproducible anywhere else. Issue #86 found 72 such files under
`verification/records/`; evidence there is append-only, so they cannot be
edited. This check is what stops the 73rd.

What it does
    Scans every tracked text file for `/Users/<name>` or `/home/<name>` at
    the start of a path (so `docs/home/x` and `https://host/home/x` do not
    match) and fails on any file that has a hit, unless:

    * `<name>` is one of the generic CI/container accounts in
      `ALLOWED_NAMES`, which identify no one; or
    * the file is listed in the baseline, `verification/home-path-baseline.txt`,
      the frozen list of files that already carried such a path when the
      check landed, with the reason they stay; or
    * the file is under a vendored tooling directory (`EXCLUDED_DIRS`),
      which is a resync copy of another repository's documentation and
      examples, not this repository's content.

    Because the baseline is an explicit list rather than a merge-base diff,
    the check needs no base ref, never skips, and gives the same answer on a
    shallow clone. "Newly added" means "not in the baseline".

    A failure prints `path:line` only. It never echoes the matched text, so
    the name does not reach a CI log either.

Fixing a failure
    Regenerate the artifact with repo-relative paths (see
    `scripts/normalize-envelope-input-path.py` for the one field with a
    normalizer). Adding the file to the baseline is a disclosure decision,
    not a lint fix, and should be reviewed as one.

Usage
    python3 scripts/check_home_paths.py              # the working tree
    python3 scripts/check_home_paths.py --rev REF    # a committed tree

Zero dependencies beyond the Python 3 standard library and `git`.
Exit codes: 0 pass, 1 a file failed, 2 usage or git error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_REL = "verification/home-path-baseline.txt"

# Generic CI / container accounts. They name an image, not a person.
ALLOWED_NAMES = frozenset({"ubuntu", "runner", "vscode"})

# Vendored tooling, overwritten on resync from its own repository.
EXCLUDED_DIRS = (".loom", ".claude", ".agents")

_NAME = r"[A-Za-z0-9._-]+"
# POSIX ERE for `git grep`; the leading group stands in for a lookbehind.
_GREP_PATTERN = rf"(^|[^A-Za-z0-9_.-])/(Users|home)/{_NAME}"
_MATCH_RE = re.compile(rf"/(?:Users|home)/({_NAME})")


class GitError(Exception):
    pass


def read_baseline(path: Path) -> set[str]:
    """Paths listed in the baseline file; `#` comments and blanks ignored."""
    if not path.exists():
        return set()
    entries = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.add(line)
    return entries


def find_hits(repo: Path, rev: str | None = None) -> dict[str, list[int]]:
    """Map each offending file to the line numbers of its hits.

    Tracked text files only (`-I` skips binaries). With `rev`, the committed
    tree at that revision is scanned instead of the working tree.
    """
    cmd = ["git", "-C", str(repo), "grep", "-I", "-n", "-o", "-z", "-E", _GREP_PATTERN]
    if rev:
        cmd.append(rev)
    cmd += ["--", "."] + [f":(exclude){d}" for d in EXCLUDED_DIRS]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode == 1:
        return {}  # git grep: no match
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", "replace").strip())

    hits: dict[str, list[int]] = {}
    prefix = f"{rev}:" if rev else ""
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        # `-z` output is `<path>\0<lineno>\0<match>`.
        parts = line.split("\0")
        if len(parts) != 3:
            continue
        path, lineno, match = parts
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        m = _MATCH_RE.search(match)
        if not m or m.group(1) in ALLOWED_NAMES:
            continue
        lines = hits.setdefault(path, [])
        if not lines or lines[-1] != int(lineno):
            lines.append(int(lineno))
    return hits


def check(repo: Path, rev: str | None, baseline: set[str]) -> tuple[dict[str, list[int]], list[str]]:
    """Return (offenders not in the baseline, baseline entries with no hit)."""
    hits = find_hits(repo, rev)
    offenders = {p: lines for p, lines in hits.items() if p not in baseline}
    stale = sorted(baseline - set(hits))
    return offenders, stale


def _format_lines(lines: list[int], limit: int = 5) -> str:
    shown = ", ".join(str(n) for n in lines[:limit])
    more = len(lines) - limit
    return f"{shown} (+{more} more)" if more > 0 else shown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rev", help="scan this committed tree instead of the working tree")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    parser.add_argument(
        "--baseline",
        type=Path,
        help=f"baseline file (default: {BASELINE_REL} in the working tree)",
    )
    args = parser.parse_args(argv)

    baseline_path = args.baseline or (args.repo / BASELINE_REL)
    baseline = read_baseline(baseline_path)
    try:
        offenders, stale = check(args.repo, args.rev, baseline)
    except GitError as exc:
        print(f"ERROR: home-path check could not run git grep: {exc}", file=sys.stderr)
        return 2

    where = args.rev or "working tree"
    for path in stale:
        print(f"NOTE: baseline entry has no home-directory path in {where}: {path}")

    if offenders:
        print(
            f"FAIL: {len(offenders)} file(s) in {where} contain an absolute "
            "home-directory path (/Users/<name> or /home/<name>) and are not "
            f"in {BASELINE_REL}:",
            file=sys.stderr,
        )
        for path in sorted(offenders):
            print(f"  {path}: line {_format_lines(offenders[path])}", file=sys.stderr)
        print(
            "Regenerate with repo-relative paths. Do not add the file to the "
            "baseline to make this pass; see scripts/check_home_paths.py.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: no absolute home-directory path outside the baseline in {where} "
        f"({len(baseline)} baselined file(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
