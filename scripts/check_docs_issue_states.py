#!/usr/bin/env python3
"""On demand: flag issue/PR states in docs/submission/ that the forge contradicts.

The judge-facing documents say things like "#217 is still open" or "PR #248
merged". Those sentences go stale the moment the issue moves, and no offline
lint can see that. This script asks GitHub (through `gh`) for the live state
of every `#N` the documents put next to state wording, and prints each
mismatch. It needs the network and an authenticated `gh`, so it is **not**
part of `npm run lint` or CI; run it before pushing a change to
`docs/submission/` (issue #238).

Heuristics, stated plainly (it is a reading aid, not a proof):

- A reference is `#N` not preceded by a letter, digit, `/` or `-`, so
  `klayout-tools#2635` and URLs are skipped. A markdown link whose target is
  a different repository (`[#1784](https://github.com/<other>/issues/1784)`)
  is skipped too.
- A state word is one of `open`, `closed`, `merged`, `unmerged`, `not merged`,
  `no longer open`, `not open` (whole words, any case). `open-drain`,
  `open drain`, `opened`, `opens` and `open item(s)` are not state words.
- Text is read a paragraph at a time (wrapped lines joined; a list item, a
  table row or a heading starts a new unit). Each reference takes the
  **nearest** state word within 60 characters, not counting balanced
  `( ... )` asides, and without crossing `.`, `;`, `:`, `|` or an unbalanced
  parenthesis (except a reference that opens an aside right after the state
  word, "open finding (F8, #211)", or closes one just before a short verb,
  "(issue #235) is closed"). A reference with no state word in reach is not checked.
  "Nearest" can pick the wrong word in a sentence that lists several states,
  and a sentence that names a state without a nearby number is not seen at
  all; read each hit before acting on it.
- `merged` is checked against the pull request's merge time; written next to
  an issue (not a PR) it only flags an issue that is still open.
- Dated historical text that is deliberately kept as written can carry
  `<!-- state-ok: <reason> -->`; every reference in that paragraph, list item
  or table row is then skipped. Prefer fixing the sentence or adding a dated correction.

`--digest [FILE]` is a second, separate mode (issue #282): it reads the
"Current reading" digest atop `spec/gap-to-submission.md` and flags every
issue number in its `Open issues` column that is not an open issue (closed,
a pull request, or nonexistent). Like the rest of this script it needs the
network, so "every issue in the digest is open" is enforced by the weekly
scheduled `digest-issue-state` workflow (and on `workflow_dispatch`),
deliberately not as a PR gate; the offline shape check is
`scripts/check_gap_digest.py`, which is in `npm run lint`.

Usage:
    python3 scripts/check_docs_issue_states.py [--docs DIR] [--repo OWNER/NAME]
    python3 scripts/check_docs_issue_states.py --digest [FILE] [--repo OWNER/NAME]
Exit codes: 0 no mismatch, 1 at least one mismatch, 2 `gh` failed.
Standard library only (plus the `gh` CLI on PATH).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_gap_digest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS = REPO_ROOT / "docs" / "submission"
WINDOW = 60

REF_RE = re.compile(r"(?<![A-Za-z0-9/-])#(\d+)\b")
OTHER_REPO_LINK_RE = re.compile(r"\]\(https?://github\.com/([^/]+/[^/]+)/(?:issues|pull)/(\d+)")
# Longest alternatives first so "not merged" wins over "merged".
STATE_RE = re.compile(
    r"\b(no longer open|not open|not merged|unmerged|still open|open|closed|merged)\b"
    r"(?![-\w])(?!\s+drain)(?!\s+items?\b)",
    re.IGNORECASE,
)
BREAK_RE = re.compile(r"[.;:|]")
OK_RE = re.compile(r"<!--\s*state-ok:\s*(\S.*?)\s*-->")

CLAIMS = {
    "open": "open",
    "still open": "open",
    "closed": "closed",
    "no longer open": "closed",
    "not open": "closed",
    "merged": "merged",
    "unmerged": "not-merged",
    "not merged": "not-merged",
}


PAREN_GROUP_RE = re.compile(r"\([^()]*\)")
UNIT_START_RE = re.compile(r"\s*([-*+] |\d+\. |\||#)")


def _gap_ok(gap: str, state_first: bool) -> bool:
    """True if a state word separated from a reference by `gap` applies to it.

    `state_first` is True when the state word comes before the reference.
    """
    if len(gap) > 4 * WINDOW:
        return False
    prev = None
    while prev != gap:  # drop balanced asides, innermost first
        prev, gap = gap, PAREN_GROUP_RE.sub("", gap)
    if state_first:
        # "open finding (F8, #211": the reference annotates the state's noun.
        gap = gap.replace("(", " ", 1) if gap.count("(") == 1 else gap
    else:
        gap = gap.rstrip().rstrip("(").rstrip()  # "#211 (closed"
        if gap.startswith(")"):
            # "(issue #235) is closed": only a short verb phrase may follow.
            if len(gap) > 15:
                return False
            gap = gap[1:]
    return len(gap) <= WINDOW and not BREAK_RE.search(gap) and "(" not in gap and ")" not in gap


def claims_in_text(text: str, repo: str) -> list[tuple[int, int, str, str]]:
    """Return (offset, number, claim, phrase) for every checkable reference."""
    if OK_RE.search(text):
        return []
    skip_at = set()
    for m in OTHER_REPO_LINK_RE.finditer(text):
        if m.group(1).lower() != repo.lower():
            skip_at.add(m.start())  # the link text `[#N]` ends just before `](`
    states = [(m.start(), m.end(), m.group(1).lower()) for m in STATE_RE.finditer(text)]
    out = []
    for ref in REF_RE.finditer(text):
        if ref.end() in skip_at:
            continue
        best = None
        for s_start, s_end, word in states:
            if s_start >= ref.end():
                gap = text[ref.end():s_start]
            elif s_end <= ref.start():
                gap = text[s_end:ref.start()]
            else:
                continue
            if _gap_ok(gap, s_end <= ref.start()) and (best is None or len(gap) < best[0]):
                best = (len(gap), word)
        if best:
            out.append((ref.start(), int(ref.group(1)), CLAIMS[best[1]], best[1]))
    return out


def units(text: str):
    """Yield (first_lineno, joined_text, line_starts) per paragraph/list item/row."""
    buf: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or UNIT_START_RE.match(line):
            if buf:
                yield buf
            buf = [(lineno, line)] if line.strip() else []
        else:
            buf.append((lineno, line))
    if buf:
        yield buf


def scan(docs: Path, repo: str):
    """Yield (file, lineno, number, claim, phrase, unit_text)."""
    for path in sorted(docs.glob("*.md")):
        for unit in units(path.read_text(encoding="utf-8")):
            joined, starts = "", []
            for lineno, line in unit:
                starts.append((len(joined), lineno))
                joined += line.strip() + " "
            for off, num, claim, phrase in claims_in_text(joined, repo):
                lineno = max(ln for o, ln in starts if o <= off)
                yield path.name, lineno, num, claim, phrase, joined.strip()


def live_state(repo: str, num: int) -> dict:
    """{'kind': 'issue'|'pr', 'state': 'open'|'closed', 'merged': bool}."""
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{num}",
         "--jq", "{pr: (.pull_request != null), state: .state, "
                 "merged: (.pull_request.merged_at != null)}"],
        capture_output=True, text=True, check=True,
    )
    d = json.loads(out.stdout)
    return {"kind": "pr" if d["pr"] else "issue", "state": d["state"], "merged": bool(d["merged"])}


def mismatch(claim: str, live: dict) -> bool:
    if claim == "open":
        return live["state"] != "open"
    if claim == "closed":
        return live["state"] != "closed"
    if claim == "merged":
        return (not live["merged"]) if live["kind"] == "pr" else live["state"] == "open"
    if claim == "not-merged":
        return live["kind"] == "pr" and live["merged"]
    raise ValueError(claim)


def describe(live: dict) -> str:
    if live["kind"] == "pr":
        return "PR merged" if live["merged"] else f"PR {live['state']}, unmerged"
    return f"issue {live['state']}"


def default_repo() -> str:
    out = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                         capture_output=True, text=True, check=True, cwd=REPO_ROOT)
    return out.stdout.strip()


def digest_problems(text: str, lookup) -> list[tuple[int, int, str]]:
    """(row, number, what) for each digest-cited number that is not an open issue.

    `lookup(num)` returns `live_state`'s dict, or None if the number does not exist.
    """
    bad = []
    for row, num in check_gap_digest.digest_issues(text):
        live = lookup(num)
        if live is None:
            bad.append((row, num, "does not exist"))
        elif live["kind"] != "issue":
            bad.append((row, num, "is a pull request"))
        elif live["state"] != "open":
            bad.append((row, num, f"is {live['state']}"))
    return bad


def gh_lookup(repo: str):
    def lookup(num: int):
        try:
            return live_state(repo, num)
        except subprocess.CalledProcessError as exc:
            if "Not Found" in (exc.stderr or "") or "404" in (exc.stderr or ""):
                return None
            raise
    return lookup


def main_digest(path: Path, repo_arg: str | None) -> int:
    try:
        repo = repo_arg or default_repo()
        bad = digest_problems(path.read_text(encoding="utf-8"), gh_lookup(repo))
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"ERROR: gh failed: {detail.strip()}", file=sys.stderr)
        return 2
    for row, num, what in bad:
        print(f"MISMATCH {path.name} digest row {row}: #{num} {what}, but the digest lists it as open")
    print(f"\nchecked the digest in {path.name} against {repo}: {len(bad)} mismatch(es)")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--docs", type=Path, default=DEFAULT_DOCS)
    ap.add_argument("--repo", help="OWNER/NAME (default: this checkout's GitHub repository)")
    ap.add_argument("--digest", nargs="?", type=Path, const=check_gap_digest.DEFAULT_PATH,
                    metavar="FILE", help="check the gap-to-submission.md digest's issue numbers instead")
    args = ap.parse_args()
    if args.digest:
        return main_digest(args.digest, args.repo)
    try:
        repo = args.repo or default_repo()
        cache: dict = {}
        hits = list(scan(args.docs, repo))
        bad = []
        for name, lineno, num, claim, phrase, line in hits:
            if num not in cache:
                cache[num] = live_state(repo, num)
            if mismatch(claim, cache[num]):
                bad.append((name, lineno, num, phrase, describe(cache[num]), line))
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"ERROR: gh failed: {detail.strip()}", file=sys.stderr)
        return 2
    for name, lineno, num, phrase, live, line in bad:
        snippet = line if len(line) <= 200 else line[:197] + "..."
        print(f"MISMATCH {name}:{lineno}: #{num} written near \"{phrase}\", live: {live}\n    {snippet}")
    print(f"\nchecked {len(hits)} state mention(s) of {len(cache)} issue/PR number(s) "
          f"in {args.docs.name}/ against {repo}: {len(bad)} mismatch(es)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
