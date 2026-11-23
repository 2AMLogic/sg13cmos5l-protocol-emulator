#!/usr/bin/env python3
"""Self-test for `scripts/check_ratification_gate.py`.

The gate is the only thing standing between the two-key (`RATIFY-KEY`)
mechanism as a documented intention and the two-key mechanism as an enforced
property -- the distinction `spec/decision-records/0006-two-key-ratification-
never-ran.md` exists because nobody could make mechanically. A gate that
silently stops catching a violation class is worse than no gate, so every
requirement `docs/ratification-gate.md` states gets an executable case here,
starting with the two controls the gate's own acceptance criteria name:

* **Negative control** -- a branch that flips a `Status:` line to `Ratified`
  with zero `RATIFY-KEY` reviews must FAIL.
* **Positive control** -- the same flip carried by two well-formed,
  distinct-`reviewer=`, non-author key reviews with releasing verdicts must
  PASS.

Method (the same shape as `verification/test_check_records.py`): build a
throwaway git repo in a temp dir with a `spec/` tree, commit it as the base
ref, apply the case's change, then run the *real* shipped script as a
subprocess against that fixture via `--repo-root`. Nothing is monkeypatched
and no forge is contacted -- review context is supplied through
`--reviews-file` / `--pr-author`, which is exactly the shape
`/pulls/<N>/reviews` returns.

Zero dependencies beyond the Python 3 standard library and `git`.

Usage:
    python3 scripts/test_check_ratification_gate.py
Exit codes: 0 all cases behave as specified, 1 at least one did not.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
GATE = SCRIPT_DIR / "check_ratification_gate.py"
REPO_ROOT = SCRIPT_DIR.parent

BASE_REF = "refs/heads/fixture-base"

AUTHOR = "carrying-pr-author[bot]"

DR_0009 = Path("spec", "decision-records", "0009-a-record.md")

PROPOSED_DR = """# 0009: A Proposed Record

Status: **Proposed 2026-09-27** -- awaiting the two-key act.
Date: 2026-09-27
Issue: #99

## Decision

Something is proposed.
"""

RATIFIED_DR = """# 0009: A Proposed Record

Status: **Ratified 2026-09-27** -- two RATIFY-KEY reviews on PR #99.
Date: 2026-09-27
Issue: #99

## Decision

Something is proposed.
"""

#: The documented status vocabulary (spec/README.md, "Status vocabulary").
STATUS_VOCABULARY = ("draft", "proposed", "ratified", "recorded")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _make_fixture(tmp: Path) -> Path:
    repo = tmp / "fixture"
    (repo / "spec" / "decision-records").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "docs").mkdir()
    _git(repo.parent, "init", "--quiet", str(repo))
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "Fixture Committer")
    (repo / "spec" / "README.md").write_text("# spec\n\nProposed specification.\n")
    (repo / "spec" / "target-spec.md").write_text(
        "# Target Specification\n\nStatus: **PROPOSED -- not ratified.**\n"
    )
    (repo / DR_0009).write_text(PROPOSED_DR)
    (repo / "scripts" / "check_ratification_gate.py").write_text("# stand-in\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture base")
    _git(repo, "update-ref", BASE_REF, "HEAD")
    return repo


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", message)


def _rev_parse(repo: Path, ref: str) -> str:
    """Resolve `ref` in the fixture repo to its commit sha (`_git` discards
    stdout by design; the merge-group cases need the base commit's sha)."""
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _flip(
    repo: Path,
    message: str = "flip",
    extra_files: dict[Path, str] | None = None,
) -> None:
    """Apply the canonical fixture change: flip DR 0009's `Status:` line from
    Proposed to Ratified -- optionally writing `extra_files` in the same
    commit, for the self-modification cases -- and commit it as one move."""
    (repo / DR_0009).write_text(RATIFIED_DR)
    for path, text in (extra_files or {}).items():
        (repo / path).write_text(text)
    _commit(repo, message)


def _review(
    body: str,
    login: str = "ee-key-holder",
    state: str = "COMMENTED",
) -> dict:
    return {
        "state": state,
        "user": {"login": login},
        "body": body,
        "html_url": f"https://example.invalid/review/{login}",
    }


def _marker(
    kind: str,
    verdict: str,
    reviewer: str,
    date: str = "2026-09-27T00:00:00Z",
    block: str = "2AMLogic/sg13cmos5l-protocol-emulator#99",
) -> str:
    return (
        f"<!-- RATIFY-KEY: {kind} verdict={verdict} block={block} "
        f"reviewer={reviewer} date={date} -->\n"
        f"## {kind}-key review\n\nProse.\n"
    )


def EE_OK(reviewer: str = "ee-agent-7") -> str:
    return _marker("ee", "approve", reviewer)


def MARKET_OK(reviewer: str = "market-agent-3") -> str:
    return _marker("market", "competitive", reviewer)


def _two_keys(*extra: dict) -> list[dict]:
    """The review pair that legitimately carries a ratification: one ee key
    and one market key from two distinct forge logins, optionally followed by
    `extra` reviews (which land after the keys, as later reviews do)."""
    return [
        _review(EE_OK(), login="ee-key-holder"),
        _review(MARKET_OK(), login="market-key-holder"),
        *extra,
    ]


def _run_cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the real shipped gate as a subprocess against `repo` -- nothing is
    monkeypatched; `args` are the gate CLI flags for this run."""
    return subprocess.run(
        [sys.executable, str(GATE), "--repo-root", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_gate(
    repo: Path,
    reviews: list[dict],
    *,
    extra_args: tuple[str, ...] = (),
    pr_author: str = AUTHOR,
) -> subprocess.CompletedProcess:
    """The ordinary PR-run shape: fixed base ref plus review context supplied
    through `--reviews-file` / `--pr-author`."""
    reviews_file = repo / "reviews.json"
    reviews_file.write_text(json.dumps(reviews))
    return _run_cli(
        repo,
        "--base-ref",
        BASE_REF,
        "--pr-author",
        pr_author,
        "--reviews-file",
        str(reviews_file),
        *extra_args,
    )


def _expect(
    result: subprocess.CompletedProcess,
    code: int,
    contain: tuple[str, ...] = (),
    absent: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """The shared verdict: the expected exit code, every required substring
    present in stdout, every forbidden one absent."""
    ok = (
        result.returncode == code
        and all(s in result.stdout for s in contain)
        and all(s not in result.stdout for s in absent)
    )
    return ok, result.stdout


def _flip_case(
    name: str,
    *,
    doc: str = "",
    message: str = "flip",
    reviews: Callable[[Path], list[dict]] | None = None,
    extra_args: Callable[[Path], tuple[str, ...]] | None = None,
    code: int,
    contain: tuple[str, ...] = (),
    absent: tuple[str, ...] = (),
) -> Callable[[Path], tuple[bool, str]]:
    """Build one uniform fixture case: flip DR 0009, run the gate with the
    given reviews / extra CLI flags, and check the exit code plus stdout
    substrings. `name` and `doc` become the reported case name and its
    rationale, exactly as a handwritten `case_*` function would carry them."""

    def case(repo: Path) -> tuple[bool, str]:
        _flip(repo, message)
        result = _run_gate(
            repo,
            reviews(repo) if reviews is not None else [],
            extra_args=extra_args(repo) if extra_args is not None else (),
        )
        return _expect(result, code, contain=contain, absent=absent)

    case.__name__ = name
    case.__doc__ = doc
    return case


# --------------------------------------------------------------------- cases
case_negative_control = _flip_case(
    "case_negative_control",
    doc="A Status flip to Ratified with zero reviews must FAIL.",
    message="flip 0009 to Ratified",
    code=1,
    contain=("no ee key", "no market key", "0009-a-record.md"),
)
case_positive_control = _flip_case(
    "case_positive_control",
    doc="The same flip, carried by two proper keys, must PASS.",
    reviews=lambda repo: _two_keys(),
    code=0,
    contain=("PASS",),
)
case_same_reviewer_twice = _flip_case(
    "case_same_reviewer_twice",
    doc="Two keys naming the same reviewer= is one holder wearing two hats.",
    reviews=lambda repo: [
        _review(EE_OK("solo-agent"), login="a"),
        _review(MARKET_OK("solo-agent"), login="b"),
    ],
    code=1,
    contain=("same reviewer",),
)
case_key_posted_by_pr_author = _flip_case(
    "case_key_posted_by_pr_author",
    reviews=lambda repo: [
        _review(EE_OK(), login=AUTHOR),
        _review(MARKET_OK(), login="market-key-holder"),
    ],
    code=1,
    contain=("posted by the PR author",),
)
case_reviewer_field_is_pr_author = _flip_case(
    "case_reviewer_field_is_pr_author",
    reviews=lambda repo: [
        _review(EE_OK(AUTHOR), login="ee-key-holder"),
        _review(MARKET_OK(), login="market-key-holder"),
    ],
    code=1,
    contain=("is the PR author",),
)
case_only_one_kind = _flip_case(
    "case_only_one_kind",
    reviews=lambda repo: [_review(EE_OK(), login="ee-key-holder")],
    code=1,
    contain=("no market key",),
)
case_non_releasing_verdict = _flip_case(
    "case_non_releasing_verdict",
    reviews=lambda repo: [
        _review(_marker("ee", "request-changes", "ee-agent-7"), login="ee"),
        _review(MARKET_OK(), login="market"),
    ],
    code=1,
    contain=("does not release",),
)
case_rereview_after_request_changes = _flip_case(
    "case_rereview_after_request_changes",
    doc="""The ordinary review cycle must not deadlock the gate.

    GitHub's review list is **append-only**: when the ee key-holder posts
    `request-changes`, the author fixes the finding, and the same holder then
    posts `approve`, both reviews are in `/pulls/<N>/reviews` forever. The
    superseded `request-changes` is a review that happened; it is not a veto
    over the later `approve`, so the flip must be released.
    """,
    reviews=lambda repo: [
        _review(
            _marker("ee", "request-changes", "ee-agent-7"), login="ee-key-holder"
        ),
        _review(EE_OK(), login="ee-key-holder"),
        _review(MARKET_OK(), login="market-key-holder"),
    ],
    code=0,
    contain=(
        "PASS", "ee key: reviewer=ee-agent-7 verdict=approve", "superseded"
    ),
    absent=("FAIL",),
)
case_market_rereview_after_uncompetitive = _flip_case(
    "case_market_rereview_after_uncompetitive",
    doc="The same shape on the market side: uncompetitive -> competitive.",
    reviews=lambda repo: [
        _review(EE_OK(), login="ee-key-holder"),
        _review(
            _marker("market", "uncompetitive", "market-agent-3"),
            login="market-key-holder",
        ),
        _review(MARKET_OK(), login="market-key-holder"),
    ],
    code=0,
    contain=(
        "PASS",
        "market key: reviewer=market-agent-3 verdict=competitive",
        "superseded",
    ),
    absent=("FAIL",),
)
case_decoy_key_cannot_veto = _flip_case(
    "case_decoy_key_cannot_veto",
    doc="""A junk RATIFY-KEY review must not make ratification unpassable.

    Two genuine, usable keys are present. Alongside them sit two unusable
    candidates of the same kinds -- one `ee` marker posted by the PR author
    (rejected by requirement 4) and one non-releasing `market` marker from an
    unrelated login (rejected by requirement 2). Neither is a key, and neither
    may deny the keys that are: otherwise anyone who can post a review on the
    PR -- including the author -- holds a permanent veto over the act.
    """,
    reviews=lambda repo: _two_keys(
        _review(_marker("ee", "approve", "decoy-agent"), login=AUTHOR),
        _review(
            _marker("market", "uncompetitive", "drive-by-agent"),
            login="random-passerby",
        ),
    ),
    code=0,
    contain=(
        "PASS",
        "ee key: reviewer=ee-agent-7 verdict=approve",
        "market key: reviewer=market-agent-3 verdict=competitive",
        # the rejected candidates are still reported, as audit notes
        "posted by the PR author",
        "does not release",
    ),
    absent=("FAIL",),
)
case_withdrawn_approval_does_not_release = _flip_case(
    "case_withdrawn_approval_does_not_release",
    doc="""The converse of the re-review cases: a holder may take a key back.

    `approve` followed by `request-changes` from the *same* `reviewer=` is a
    withdrawn key, not a standing one. Only a reviewer's latest marker of a
    given kind is operative, so this must FAIL -- otherwise "supersede" would
    only ever work in the direction that releases.
    """,
    reviews=lambda repo: [
        _review(EE_OK(), login="ee-key-holder"),
        _review(
            _marker("ee", "request-changes", "ee-agent-7"), login="ee-key-holder"
        ),
        _review(MARKET_OK(), login="market-key-holder"),
    ],
    code=1,
    contain=("does not release",),
    absent=("ee key: reviewer=ee-agent-7 verdict=approve",),
)
case_dismissed_review = _flip_case(
    "case_dismissed_review",
    reviews=lambda repo: [
        _review(EE_OK(), login="ee"),
        _review(MARKET_OK(), login="market", state="DISMISSED"),
    ],
    code=1,
    contain=("DISMISSED", "no market key"),
)
case_placeholder_marker = _flip_case(
    "case_placeholder_marker",
    doc="A marker still carrying the skill's <agent-id> template is not a key.",
    reviews=lambda repo: [
        _review(_marker("ee", "approve", "<agent-id>"), login="ee"),
        _review(MARKET_OK(), login="market"),
    ],
    code=1,
    contain=("placeholder",),
)
case_malformed_marker_missing_field = _flip_case(
    "case_malformed_marker_missing_field",
    reviews=lambda repo: [
        _review("<!-- RATIFY-KEY: ee verdict=approve -->\nbody\n", login="ee"),
        _review(MARKET_OK(), login="market"),
    ],
    code=1,
    contain=("missing field",),
)


def case_prose_edit_to_proposed_record(repo: Path) -> tuple[bool, str]:
    """Editing a Proposed record is not a flip -- zero reviews must PASS."""
    (repo / DR_0009).write_text(
        PROPOSED_DR.replace("Something is proposed.", "Something else.")
    )
    _commit(repo, "edit prose")
    result = _run_gate(repo, [])
    return _expect(result, 0, contain=("no spec/ Status line is flipped",))


def case_reconcile_away_from_ratified(repo: Path) -> tuple[bool, str]:
    """DR 0006's own repair shape: Ratified -> 'PROPOSED -- not ratified'."""
    _flip(repo)
    _git(repo, "update-ref", BASE_REF, "HEAD")
    (repo / DR_0009).write_text(
        RATIFIED_DR.replace(
            "Status: **Ratified 2026-09-27** -- two RATIFY-KEY reviews on PR #99.",
            "Status: **PROPOSED -- not ratified.** The act never ran.",
        )
    )
    _commit(repo, "reconcile away from Ratified")
    result = _run_gate(repo, [])
    return _expect(result, 0, contain=("no spec/ Status line is flipped",))


def case_edit_on_already_ratified_line(repo: Path) -> tuple[bool, str]:
    """A typo fix on an already-Ratified line is not a new flip."""
    _flip(repo)
    _git(repo, "update-ref", BASE_REF, "HEAD")
    (repo / DR_0009).write_text(
        RATIFIED_DR.replace(
            "two RATIFY-KEY reviews on PR #99.",
            "two RATIFY-KEY reviews on PR #99 (merge commit abc1234)."
        )
    )
    _commit(repo, "amend the citation")
    result = _run_gate(repo, [])
    return _expect(result, 0, contain=("no spec/ Status line is flipped",))


def case_new_file_born_ratified(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0010-new.md").write_text(RATIFIED_DR)
    _commit(repo, "add a record born Ratified")
    result = _run_gate(repo, [])
    return _expect(result, 1, contain=("0010-new.md",))


def case_new_file_born_proposed(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0010-new.md").write_text(PROPOSED_DR)
    _commit(repo, "add a Proposed record")
    result = _run_gate(repo, [])
    return _expect(result, 0, contain=("no spec/ Status line is flipped",))


def case_status_outside_spec_ignored(repo: Path) -> tuple[bool, str]:
    """A Ratified Status line outside spec/ is out of the gate's scope."""
    (repo / "docs" / "note.md").write_text("# Note\n\nStatus: Ratified 2026-09-27\n")
    _commit(repo, "add a docs note")
    result = _run_gate(repo, [])
    return _expect(result, 0, contain=("no spec/ Status line is flipped",))


def case_gate_self_modification(repo: Path) -> tuple[bool, str]:
    """A PR may not ratify and rewrite its own gate in one move."""
    _flip(
        repo,
        "flip and edit the gate",
        extra_files={Path("scripts", "check_ratification_gate.py"): "# neutered\n"},
    )
    result = _run_gate(repo, _two_keys())
    return _expect(result, 1, contain=("modifies the gate's own files",))


def case_lint_wiring_self_modification(repo: Path) -> tuple[bool, str]:
    """`package.json` is guarded too: it is where `npm run lint` calls the gate.

    Deleting the gate's invocation from the lint script in the same diff that
    flips a Status line is the same move as editing the gate itself.
    """
    _flip(
        repo,
        "flip and rewire lint",
        extra_files={Path("package.json"): '{"scripts": {"lint": "true"}}\n'},
    )
    result = _run_gate(repo, _two_keys())
    return _expect(result, 1, contain=("modifies the gate's own files", "package.json"))


def case_same_login_note_only(repo: Path) -> tuple[bool, str]:
    """Two keys, one forge login: a NOTE by default (DR 0006's open question)."""
    _flip(repo)
    reviews = [
        _review(EE_OK(), login="shared-bot"),
        _review(MARKET_OK(), login="shared-bot"),
    ]
    lenient = _run_gate(repo, reviews)
    strict = _run_gate(repo, reviews, extra_args=("--require-distinct-principals",))
    ok = (
        lenient.returncode == 0
        and "same forge login" in lenient.stdout
        and strict.returncode == 1
        and "require-distinct-principals" in strict.stdout
    )
    return ok, lenient.stdout + "\n--- strict ---\n" + strict.stdout


def case_no_base_ref_skips(repo: Path) -> tuple[bool, str]:
    _flip(repo)
    result = _run_cli(
        repo,
        "--base-ref",
        "refs/heads/does-not-exist",
        "--pr-author",
        AUTHOR,
        "--reviews-file",
        str(repo / "reviews.json"),
    )
    return _expect(result, 0, contain=("SKIP",))


# ------------------------------------------------ merge-group (issue #432)
#
# On a merge_group run the gate is a REQUIRED check, so every path that the
# local mode answers with a SKIP must instead fail: a skipped required check
# reads as a pass to the queue. The base arrives as an explicit commit
# (--base-sha, github.event.merge_group.base_sha) and the carrying PR number
# is parsed from the queue ref, never auto-discovered -- a queue branch is
# not a PR branch, so `gh pr view` cannot resolve it.

QUEUE_REF = "refs/heads/gh-readonly-queue/main/pr-47-deadbeefdeadbeefdeadbeefdeadbeefdeadbee"


def _merge_group_args(
    repo: Path,
    base_sha: str | None = None,
    head_ref: str = QUEUE_REF,
) -> tuple[str, ...]:
    """The CLI shape a merge_group run arrives in: an explicit base commit
    (the fixture's base by default) and the queue ref."""
    if base_sha is None:
        base_sha = _rev_parse(repo, BASE_REF)
    return (
        "--merge-group",
        "--base-sha",
        base_sha,
        "--merge-group-head-ref",
        head_ref,
    )
case_merge_group_base_absent_fails = _flip_case(
    "case_merge_group_base_absent_fails",
    doc="A merge_group run whose base_sha is absent must FAIL, never SKIP.",
    message="flip 0009 to Ratified",
    extra_args=lambda repo: _merge_group_args(repo, base_sha=""),
    code=1,
    contain=("FAIL", "must not SKIP"),
    absent=("SKIP:",),
)
case_merge_group_base_unavailable_fails = _flip_case(
    "case_merge_group_base_unavailable_fails",
    doc="""A merge_group run whose base commit is not in the checkout (shallow
    clone) must FAIL with a named reason.""",
    message="flip 0009 to Ratified",
    extra_args=lambda repo: _merge_group_args(repo, base_sha="0" * 40),
    code=1,
    contain=("is not available",),
    absent=("SKIP:",),
)


def case_merge_group_flip_no_resolvable_pr_fails(repo: Path) -> tuple[bool, str]:
    """A flip whose queue ref carries no parseable PR number fails closed.

    Run WITHOUT `--reviews-file`/`--pr-author`: those supply review context
    directly and would bypass the PR resolution this case exercises (which is
    exactly what happens in a real merge_group run -- the job has review
    context only through the PR the queue ref names). Resolving the PR is
    what fails here, before any forge call, so the run needs no network.
    """
    _flip(repo, "flip 0009 to Ratified")
    result = _run_cli(
        repo,
        *_merge_group_args(
            repo, head_ref="refs/heads/gh-readonly-queue/main/pr-notanumber-deadbee"
        ),
    )
    return _expect(result, 1, contain=("no carrying PR",), absent=("SKIP:",))
case_merge_group_flip_with_valid_keys_passes = _flip_case(
    "case_merge_group_flip_with_valid_keys_passes",
    doc="""A queue run with a real base, a parseable PR ref and two proper keys
    must PASS -- the ordinary two-key evaluation, unchanged.""",
    message="flip 0009 to Ratified",
    reviews=lambda repo: _two_keys(),
    extra_args=lambda repo: _merge_group_args(repo),
    code=0,
    contain=("PASS",),
    absent=("FAIL",),
)
case_merge_group_flip_without_keys_fails = _flip_case(
    "case_merge_group_flip_without_keys_fails",
    doc="""The negative control, replayed on a merge_group run: a flip with zero
    reviews must FAIL on the keys themselves.""",
    message="flip 0009 to Ratified",
    extra_args=lambda repo: _merge_group_args(repo),
    code=1,
    contain=("no ee key", "no market key"),
)


def case_merge_group_non_flip_passes(repo: Path) -> tuple[bool, str]:
    """No flip: a merge_group run passes trivially, exactly as on a PR."""
    (repo / DR_0009).write_text(
        PROPOSED_DR.replace("Something is proposed.", "Something else.")
    )
    _commit(repo, "edit prose")
    result = _run_gate(repo, [], extra_args=_merge_group_args(repo))
    return _expect(result, 0, contain=("no spec/ Status line is flipped",))


FIXTURE_CASES = (
    case_negative_control,
    case_positive_control,
    case_same_reviewer_twice,
    case_key_posted_by_pr_author,
    case_reviewer_field_is_pr_author,
    case_only_one_kind,
    case_non_releasing_verdict,
    case_rereview_after_request_changes,
    case_market_rereview_after_uncompetitive,
    case_decoy_key_cannot_veto,
    case_withdrawn_approval_does_not_release,
    case_dismissed_review,
    case_placeholder_marker,
    case_malformed_marker_missing_field,
    case_prose_edit_to_proposed_record,
    case_reconcile_away_from_ratified,
    case_edit_on_already_ratified_line,
    case_new_file_born_ratified,
    case_new_file_born_proposed,
    case_status_outside_spec_ignored,
    case_gate_self_modification,
    case_lint_wiring_self_modification,
    case_same_login_note_only,
    case_no_base_ref_skips,
    case_merge_group_base_absent_fails,
    case_merge_group_base_unavailable_fails,
    case_merge_group_flip_no_resolvable_pr_fails,
    case_merge_group_flip_with_valid_keys_passes,
    case_merge_group_flip_without_keys_fails,
    case_merge_group_non_flip_passes,
)


def _load_gate():
    """Import the shipped gate module for the in-process cases (path-shimmed
    because `scripts/` is not a package)."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    import check_ratification_gate as gate  # noqa: PLC0415

    return gate


def case_real_spec_status_vocabulary() -> tuple[bool, str]:
    """Every real `Status:` line under spec/ uses the documented vocabulary.

    Exercises the shipped value parser against this repo's actual prose (which
    is markdown-heavy: bold, em-dashes, parentheticals) without pinning any
    file to a particular status -- so a real ratification does not break it,
    but an undocumented status word does.
    """
    gate = _load_gate()

    spec_dir = REPO_ROOT / "spec"
    if not spec_dir.is_dir():
        return True, "SKIP: no spec/ directory in this checkout"
    problems = []
    seen = 0
    for path in sorted(spec_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for match in gate.STATUS_LINE_RE.finditer(text):
            seen += 1
            value = gate.normalize_status_value(match.group("value"))
            if not any(value.startswith(word) for word in STATUS_VOCABULARY):
                problems.append(
                    f"{path.relative_to(REPO_ROOT)}: Status value {value!r} is outside "
                    f"the documented vocabulary {STATUS_VOCABULARY}"
                )
    if seen == 0:
        problems.append("no start-of-line `Status:` line found anywhere under spec/")
    return (not problems), "\n".join(problems) or f"{seen} Status line(s) checked"


def case_pr_number_parsing() -> tuple[bool, str]:
    """The queue-ref parser: PR number out of
    `refs/heads/gh-readonly-queue/<base>/pr-<N>-<sha>`, None otherwise."""
    gate = _load_gate()

    cases = [
        ("refs/heads/gh-readonly-queue/main/pr-47-deadbee", 47),
        ("refs/heads/gh-readonly-queue/gh-readonly-queue/main/pr-7-cafe", 7),
        ("refs/heads/gh-readonly-queue/main/pr-notanumber-deadbee", None),
        ("refs/heads/gh-readonly-queue/main/deadbee", None),
        ("refs/heads/some-regular-branch", None),
        ("", None),
        (None, None),
    ]
    problems = []
    for head_ref, expected in cases:
        got = gate.pr_number_from_head_ref(head_ref)
        if got != expected:
            problems.append(f"{head_ref!r}: got {got!r}, expected {expected!r}")
    return (not problems), "\n".join(problems) or f"{len(cases)} refs parsed as specified"


STANDALONE_CASES = (
    case_real_spec_status_vocabulary,
    case_pr_number_parsing,
)


def main() -> int:
    failures = 0
    for case in FIXTURE_CASES:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _make_fixture(Path(tmpdir))
            try:
                ok, detail = case(repo)
            except Exception as exc:  # noqa: BLE001 -- report, don't abort the suite
                ok, detail = False, f"raised {type(exc).__name__}: {exc}"
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case.__name__}")
        if not ok:
            failures += 1
            print("        " + detail.replace("\n", "\n        "))

    for case in STANDALONE_CASES:
        ok, detail = case()
        print(f"[{'PASS' if ok else 'FAIL'}] {case.__name__} -- {detail}")
        if not ok:
            failures += 1

    total = len(FIXTURE_CASES) + len(STANDALONE_CASES)
    print(f"\n{total - failures}/{total} cases behaved as specified")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
