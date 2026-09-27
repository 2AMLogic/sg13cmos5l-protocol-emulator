#!/usr/bin/env python3
"""Ratification gate: a `spec/` Status flip to `Ratified` needs two RATIFY-KEY reviews.

This is the enforcement half of the two-key mechanism documented in
`spec/README.md` § "How ratification works here" and
`spec/decision-records/0004-target-spec-ratification.md` § "The binding
process". Until this script existed, that mechanism was described in prose
and enforced by nothing: `spec/decision-records/0006-two-key-ratification-
never-ran.md` records the consequence -- PR #29 flipped five `Status:` lines
to `Ratified` and merged with zero PR reviews of any kind, 4m37s after a
correct stand-down comment that nothing mechanical could read.

**The documented mechanism and the enforced mechanism must name the same
thing.** `docs/ratification-gate.md` is the authoritative description of what
this script checks; if the two disagree, that is a defect in this script.

What is gated (and only this): a **flip**, i.e. a file under `spec/` whose
`Status:` line asserts ratification in the PR's head tree but did not in the
merge-base tree. Everything else about a `spec/` change is untouched --
editing a `Proposed` record, reflowing prose on an already-`Ratified` line,
or reconciling a line *away* from `Ratified` (DR 0006's own repair) is not a
flip and is not gated.

When a flip is present, the gate requires **all** of:

1. At least one `<!-- RATIFY-KEY: ee ... -->` marker and at least one
   `<!-- RATIFY-KEY: market ... -->` marker, each in a non-dismissed review
   on the carrying PR (`/pulls/<N>/reviews`), each well-formed per its
   skill's "Output format" grammar (`verdict=`, `block=`, `reviewer=`,
   `date=` all present and non-placeholder).
2. A releasing verdict on each: `ee` must be `approve`; `market` must be
   `competitive` or `adequate-for-catalog`. A `request-changes` /
   `uncompetitive` / `escalate` key is a review that happened, not a release.
   It is also not a *veto*: a review list is append-only, so a rejected
   candidate fails the gate only when its kind has no usable key at all, and
   only a reviewer's latest marker of a kind is operative (see
   `evaluate_keys`).
3. The two markers' `reviewer=` values distinct (case-insensitively).
4. Neither key attributable to the PR's author -- neither the review's forge
   login nor the marker's `reviewer=` value may equal the PR author's login.
5. No change, in the same diff, to the gate's own files (see `GUARDED_PATHS`).
   A PR may not ratify and rewrite its own gate in one move.

**What this gate deliberately does not decide.** DR 0006 § "Routed, not
decided" routes one question to an operator: whether two agent sessions
sharing a single forge identity satisfy *"neither held by the design's
author"*, or whether distinct forge principals are required. This script
does not pre-empt that ruling -- it enforces distinct `reviewer=` values and
non-authorship, and *reports* each key's forge login so the record shows it.
When the operator rules that distinct principals are required, `--require-
distinct-principals` turns that into a failure with no code change.

Zero dependencies beyond the Python 3 standard library, `git`, and -- only
when resolving PR context -- the `gh` CLI.

Usage:
    # CI / authoritative: explicit PR context.
    python3 scripts/check_ratification_gate.py --pr 47

    # Local (npm run lint): auto-discovers the PR for the current branch.
    # No flip -> pass. Flip with no resolvable PR context -> SKIP (the
    # workflow job is the authoritative check).
    python3 scripts/check_ratification_gate.py --base-ref origin/main

    # Offline, for the self-test and for reproducing a control case.
    python3 scripts/check_ratification_gate.py --base-ref REF \
        --pr-author some-bot --reviews-file reviews.json

Exit codes: 0 pass (or nothing to gate), 1 the gate failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SPEC_SUBDIR = "spec"

#: Paths whose modification, in a diff that also flips a Status line, fails
#: the gate. A ratification PR may not also rewrite the thing checking it.
GUARDED_PATHS = (
    "scripts/check_ratification_gate.py",
    "scripts/test_check_ratification_gate.py",
    ".github/workflows/ratification-gate.yml",
    # `npm run lint` is where the local copy of the gate is invoked; removing
    # that invocation in the same diff is the same move as editing the gate.
    "package.json",
)

#: A `Status:` value asserting that the ratification act has happened. Matched
#: against the *leading* value only (text before the first delimiter), so
#: `Status: **PROPOSED -- not ratified.**` reads as `PROPOSED`, not as a flip.
RATIFIED_VALUE_RE = re.compile(r"^(ratified|in force)\b")

#: Negations that disqualify a value even if it leads with a ratified word.
NEGATION_RE = re.compile(r"\b(not|never|un-?)\s*ratified\b|\bnot in force\b")

STATUS_LINE_RE = re.compile(r"^Status:[ \t]*(?P<value>.*)$", re.MULTILINE)

#: Cut a Status value down to its leading token region. The repo's convention
#: is `Status: <VALUE> -- <prose>` (see docs/ratification-gate.md).
VALUE_DELIMITERS = ("—", "--", "(", ".", ",", ";", ":", "–")

#: Matched line-wise and tolerant of an unterminated marker, so that a marker
#: still carrying the skill's `reviewer=<agent-id>` placeholder is *parsed and
#: reported as a placeholder* rather than silently not matching at all.
MARKER_RE = re.compile(
    r"<!--[ \t]*RATIFY-KEY:[ \t]*(?P<kind>[A-Za-z-]+)[ \t]+(?P<fields>[^\n]*?)[ \t]*(?:-->|$)",
    re.IGNORECASE | re.MULTILINE,
)
FIELD_RE = re.compile(r"(?P<key>[A-Za-z][A-Za-z_-]*)=(?P<value>\S+)")

KEY_KINDS = ("ee", "market")

#: Verdicts that *release* the PR, per each skill's "Output format" section.
RELEASING_VERDICTS = {
    "ee": {"approve"},
    "market": {"competitive", "adequate-for-catalog"},
}

REQUIRED_MARKER_FIELDS = ("verdict", "block", "reviewer", "date")

#: A marker that still carries the skill's own angle-bracket placeholder is a
#: copied template, not a key.
PLACEHOLDER_RE = re.compile(r"^<.*>$")

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


class GateError(Exception):
    """A usage / environment problem, not a gate verdict."""


# ---------------------------------------------------------------- git helpers


def run_git(repo_root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def resolve_base(repo_root: Path, base_ref: str) -> str | None:
    """Return the merge-base commit of `base_ref` and HEAD, or None."""
    rev = run_git(repo_root, "rev-parse", "--verify", "--quiet", base_ref, check=False)
    if not rev.strip():
        return None
    merge_base = run_git(repo_root, "merge-base", base_ref, "HEAD", check=False)
    return merge_base.strip() or None


def tree_spec_files(repo_root: Path, commit: str) -> set[str]:
    out = run_git(repo_root, "ls-tree", "-r", "--name-only", commit, "--", SPEC_SUBDIR)
    return {line for line in out.splitlines() if line.endswith(".md")}


def head_spec_files(repo_root: Path) -> set[str]:
    tracked = run_git(repo_root, "ls-files", "--", SPEC_SUBDIR)
    untracked = run_git(
        repo_root, "ls-files", "--others", "--exclude-standard", "--", SPEC_SUBDIR
    )
    return {
        line
        for line in (tracked + untracked).splitlines()
        if line.endswith(".md") and (repo_root / line).is_file()
    }


def blob_text(repo_root: Path, commit: str, path: str) -> str:
    out = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout if out.returncode == 0 else ""


def changed_paths(repo_root: Path, base: str) -> set[str]:
    committed = run_git(repo_root, "diff", "--name-only", f"{base}..HEAD")
    worktree = run_git(repo_root, "diff", "--name-only", base)
    return {line for line in (committed + worktree).splitlines() if line}


# ----------------------------------------------------------- status detection


def normalize_status_value(raw: str) -> str:
    """Reduce a raw `Status:` value to its leading token region, lowercased."""
    value = raw.strip()
    for char in "*_`>":
        value = value.replace(char, "")
    cut = len(value)
    for delim in VALUE_DELIMITERS:
        found = value.find(delim)
        if found != -1:
            cut = min(cut, found)
    return value[:cut].strip().lower()


def asserts_ratified(text: str) -> bool:
    """True if any start-of-line `Status:` in `text` asserts ratification."""
    for match in STATUS_LINE_RE.finditer(text):
        raw = match.group("value")
        if NEGATION_RE.search(raw.lower()):
            continue
        if RATIFIED_VALUE_RE.match(normalize_status_value(raw)):
            return True
    return False


def find_flips(repo_root: Path, base: str) -> list[str]:
    """Spec files that assert ratification at HEAD but did not at `base`."""
    base_files = tree_spec_files(repo_root, base)
    paths = sorted(base_files | head_spec_files(repo_root))
    flips = []
    for path in paths:
        head_path = repo_root / path
        head_text = head_path.read_text(encoding="utf-8") if head_path.is_file() else ""
        if not asserts_ratified(head_text):
            continue
        if asserts_ratified(blob_text(repo_root, base, path)):
            continue  # already ratified at base -- not a flip
        flips.append(path)
    return flips


# ----------------------------------------------------------- marker detection


def parse_markers(reviews: list[dict]) -> tuple[list[dict], list[str]]:
    """Return (well-formed markers, complaints about malformed ones)."""
    markers: list[dict] = []
    complaints: list[str] = []
    for review in reviews:
        state = str(review.get("state") or "").upper()
        login = str((review.get("user") or {}).get("login") or "")
        body = str(review.get("body") or "")
        url = str(review.get("html_url") or "")
        for match in MARKER_RE.finditer(body):
            kind = match.group("kind").lower()
            fields = {
                m.group("key").lower(): m.group("value")
                for m in FIELD_RE.finditer(match.group("fields"))
            }
            where = f"review by {login or '<unknown>'} ({url or 'no url'})"
            if state == "DISMISSED":
                complaints.append(f"{where}: marker ignored, the review is DISMISSED")
                continue
            if kind not in KEY_KINDS:
                complaints.append(f"{where}: unknown key kind {kind!r}")
                continue
            missing = [f for f in REQUIRED_MARKER_FIELDS if f not in fields]
            if missing:
                complaints.append(
                    f"{where}: {kind} marker missing field(s) {', '.join(missing)}"
                )
                continue
            placeholders = [
                f for f in REQUIRED_MARKER_FIELDS if PLACEHOLDER_RE.match(fields[f])
            ]
            if placeholders:
                complaints.append(
                    f"{where}: {kind} marker still carries the skill's placeholder for "
                    f"{', '.join(placeholders)} -- a copied template is not a key"
                )
                continue
            if not ISO_DATE_RE.match(fields["date"]):
                complaints.append(
                    f"{where}: {kind} marker date={fields['date']!r} is not ISO-8601"
                )
                continue
            markers.append(
                {
                    "kind": kind,
                    "verdict": fields["verdict"].lower(),
                    "block": fields["block"],
                    "reviewer": fields["reviewer"],
                    "date": fields["date"],
                    "login": login,
                    "state": state,
                    "url": url,
                }
            )
    return markers, complaints


def evaluate_keys(
    markers: list[dict],
    pr_author: str,
    *,
    require_distinct_principals: bool,
) -> tuple[bool, list[str], list[str], dict[str, dict]]:
    """Apply requirements 1-4. Returns (ok, failures, notes, accepted-by-kind).

    Two properties of a forge review list shape this, and both are what
    `docs/ratification-gate.md` § "A rejected candidate is not a veto" states:

    * **Reviews are append-only.** A `request-changes` review the author then
      fixed stays in `/pulls/<N>/reviews` forever. So a rejected candidate is
      evaluated **per kind** and only becomes a failure when that kind ends up
      with no usable key at all -- otherwise the ordinary review cycle
      (`request-changes` then `approve` from the same holder) could never
      release, and any junk `RATIFY-KEY` review by anyone, the PR author
      included, would be a permanent veto. Rejections a usable key outlives
      are still reported, as audit `notes`.
    * **A reviewer speaks once per kind.** Only a reviewer's *latest* marker of
      a kind is operative (reviews arrive in chronological order), so a
      withdrawn key -- `approve` later followed by `request-changes` from the
      same `reviewer=` -- stops releasing rather than being outvoted by its own
      earlier self.
    """
    failures: list[str] = []
    notes: list[str] = []
    author = pr_author.strip().lower()
    accepted: dict[str, dict] = {}

    for kind in KEY_KINDS:
        candidates = [m for m in markers if m["kind"] == kind]
        if not candidates:
            failures.append(f"no {kind} key: zero well-formed RATIFY-KEY {kind} markers")
            continue

        # Latest marker per reviewer wins; earlier ones are superseded, not votes.
        operative: dict[str, dict] = {}
        for marker in candidates:
            who = marker["reviewer"].strip().lower()
            previous = operative.get(who)
            if previous is not None:
                notes.append(
                    f"NOTE: an earlier {kind} marker from reviewer="
                    f"{previous['reviewer']} (verdict={previous['verdict']}) is "
                    "superseded by a later review from the same reviewer"
                )
            operative[who] = marker

        usable: list[dict] = []
        rejections: list[str] = []
        for marker in operative.values():
            reviewer = marker["reviewer"].strip().lower()
            login = marker["login"].strip().lower()
            if author and reviewer == author:
                rejections.append(
                    f"{kind} key rejected: reviewer={marker['reviewer']} is the PR author"
                )
                continue
            if author and login == author:
                rejections.append(
                    f"{kind} key rejected: review posted by the PR author ({marker['login']})"
                )
                continue
            if marker["verdict"] not in RELEASING_VERDICTS[kind]:
                rejections.append(
                    f"{kind} key does not release: verdict={marker['verdict']} "
                    f"(releasing verdicts: {', '.join(sorted(RELEASING_VERDICTS[kind]))})"
                )
                continue
            usable.append(marker)

        if not usable:
            # Nothing of this kind released: now the rejections are the reason.
            failures.extend(rejections)
            continue
        accepted[kind] = usable[0]
        for rejection in rejections:
            notes.append(
                f"NOTE: unusable {kind} candidate, outlived by an accepted "
                f"{kind} key -- {rejection}"
            )
        if len(usable) > 1:
            notes.append(
                f"{len(usable)} usable {kind} keys present; the first is reported"
            )

    if len(accepted) == len(KEY_KINDS):
        reviewers = {k: accepted[k]["reviewer"].strip().lower() for k in KEY_KINDS}
        if reviewers["ee"] == reviewers["market"]:
            failures.append(
                "both keys name the same reviewer="
                f"{accepted['ee']['reviewer']} -- two keys means two holders"
            )
        logins = {k: accepted[k]["login"].strip().lower() for k in KEY_KINDS}
        if logins["ee"] == logins["market"]:
            message = (
                "both keys were posted by the same forge login "
                f"({accepted['ee']['login'] or '<unknown>'}); whether distinct forge "
                "principals are required is the operator question DR 0006 "
                "§ 'Routed, not decided' routes"
            )
            if require_distinct_principals:
                failures.append(
                    message + " -- failing because --require-distinct-principals is set"
                )
            else:
                notes.append("NOTE: " + message)

    return (not failures), failures, notes, accepted


# ------------------------------------------------------------------ PR context


def gh_json(repo_root: Path, *args: str) -> object:
    proc = subprocess.run(
        ["gh", *args], cwd=repo_root, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GateError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout or "null")


def fetch_pr_context(
    repo_root: Path, repo: str | None, pr: int
) -> tuple[str, list[dict]]:
    slug = repo or "{owner}/{repo}"
    pr_data = gh_json(repo_root, "api", f"repos/{slug}/pulls/{pr}")
    if not isinstance(pr_data, dict):
        raise GateError(f"unexpected response for PR #{pr}")
    author = str((pr_data.get("user") or {}).get("login") or "")
    reviews = gh_json(repo_root, "api", "--paginate", f"repos/{slug}/pulls/{pr}/reviews")
    if not isinstance(reviews, list):
        raise GateError(f"unexpected reviews response for PR #{pr}")
    return author, reviews


def discover_pr_number(repo_root: Path) -> int | None:
    proc = subprocess.run(
        ["gh", "pr", "view", "--json", "number"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None
    number = (data or {}).get("number") if isinstance(data, dict) else None
    return int(number) if number else None


# ------------------------------------------------------------------- reporting


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail unless a spec/ Status flip to Ratified is carried by two "
            "distinct-reviewer, non-author RATIFY-KEY reviews."
        )
    )
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="ref whose merge-base with HEAD is the pre-change state (default: origin/main)",
    )
    parser.add_argument(
        "--base-sha", help="explicit base commit; overrides --base-ref's merge-base"
    )
    parser.add_argument("--pr", type=int, help="carrying PR number (authoritative mode)")
    parser.add_argument("--repo", help="OWNER/REPO for gh API calls (default: current)")
    parser.add_argument(
        "--pr-author", help="PR author login (skips the gh lookup; used by the self-test)"
    )
    parser.add_argument(
        "--reviews-file",
        help="JSON file shaped like /pulls/<N>/reviews (skips the gh lookup)",
    )
    parser.add_argument(
        "--require-distinct-principals",
        action="store_true",
        help=(
            "also require the two key reviews to come from distinct forge logins "
            "(turn on once an operator rules per DR 0006 § 'Routed, not decided')"
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="repository root (default: the parent of this script's directory)",
    )
    args = parser.parse_args(argv)

    repo_root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parent.parent
    )

    try:
        base = args.base_sha or resolve_base(repo_root, args.base_ref)
        if not base:
            print(
                f"SKIP: base ref {args.base_ref!r} could not be resolved, so no "
                "pre-change state is available to compare against."
            )
            return 0

        flips = find_flips(repo_root, base)
        if not flips:
            print(
                "PASS: no spec/ Status line is flipped to Ratified by this change "
                f"(base {base[:12]}); nothing for the two-key gate to check."
            )
            return 0

        print("Ratification gate: spec/ Status flip(s) to Ratified detected")
        print(f"  base: {base[:12]}")
        for path in flips:
            print(f"  flipped: {path}")

        touched_guarded = sorted(
            set(GUARDED_PATHS) & changed_paths(repo_root, base)
        )

        # Resolve review context.
        if args.reviews_file is not None or args.pr_author is not None:
            if args.reviews_file is None or args.pr_author is None:
                raise GateError("--reviews-file and --pr-author must be given together")
            reviews_raw = json.loads(
                Path(args.reviews_file).read_text(encoding="utf-8") or "[]"
            )
            if not isinstance(reviews_raw, list):
                raise GateError("--reviews-file must contain a JSON array")
            pr_author, reviews = args.pr_author, reviews_raw
            source = f"--reviews-file {args.reviews_file}"
        else:
            pr_number = args.pr or discover_pr_number(repo_root)
            if not pr_number:
                print(
                    "SKIP: a ratification flip is present but no carrying PR could be "
                    "resolved for this branch, so the two-key requirement cannot be "
                    "evaluated here. The authoritative check is the "
                    '"ratification gate" workflow job, which always has PR context.'
                )
                return 0
            pr_author, reviews = fetch_pr_context(repo_root, args.repo, pr_number)
            source = f"PR #{pr_number} /pulls/{pr_number}/reviews"

        print(f"  reviews source: {source}")
        print(f"  PR author: {pr_author or '<unknown>'}")
        print(f"  reviews on the PR: {len(reviews)}")

        markers, complaints = parse_markers(reviews)
        print(f"  well-formed RATIFY-KEY markers: {len(markers)}")
        for complaint in complaints:
            print(f"  ignored marker: {complaint}")

        ok, failures, notes, accepted = evaluate_keys(
            markers,
            pr_author,
            require_distinct_principals=args.require_distinct_principals,
        )

        if touched_guarded:
            ok = False
            failures.insert(
                0,
                "this change flips a Status line AND modifies the gate's own files "
                f"({', '.join(touched_guarded)}); split the gate change into its own PR",
            )

        for kind in KEY_KINDS:
            marker = accepted.get(kind)
            if marker:
                print(
                    f"  {kind} key: reviewer={marker['reviewer']} "
                    f"verdict={marker['verdict']} login={marker['login'] or '<unknown>'} "
                    f"date={marker['date']}"
                )
        for note in notes:
            print(f"  {note}")

        if ok:
            print(
                "PASS: the flip is carried by two distinct-reviewer, non-author "
                "RATIFY-KEY reviews with releasing verdicts."
            )
            return 0

        print("")
        print("FAIL: the two-key ratification act is not evidenced on this PR.")
        for failure in failures:
            print(f"  - {failure}")
        print("")
        print(
            "A spec/ Status line may read Ratified only once the act has run. See "
            "docs/ratification-gate.md, spec/README.md and "
            "spec/decision-records/0006-two-key-ratification-never-ran.md "
            "§ 'How this gets closed'."
        )
        return 1

    except GateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
