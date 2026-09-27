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
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
GATE = SCRIPT_DIR / "check_ratification_gate.py"
REPO_ROOT = SCRIPT_DIR.parent

BASE_REF = "refs/heads/fixture-base"

AUTHOR = "carrying-pr-author[bot]"

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
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(PROPOSED_DR)
    (repo / "scripts" / "check_ratification_gate.py").write_text("# stand-in\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture base")
    _git(repo, "update-ref", BASE_REF, "HEAD")
    return repo


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", message)


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


def _run_gate(
    repo: Path,
    reviews: list[dict],
    *,
    extra_args: tuple[str, ...] = (),
    pr_author: str = AUTHOR,
) -> subprocess.CompletedProcess:
    reviews_file = repo / "reviews.json"
    reviews_file.write_text(json.dumps(reviews))
    return subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--repo-root",
            str(repo),
            "--base-ref",
            BASE_REF,
            "--pr-author",
            pr_author,
            "--reviews-file",
            str(reviews_file),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


# --------------------------------------------------------------------- cases


def case_negative_control(repo: Path) -> tuple[bool, str]:
    """A Status flip to Ratified with zero reviews must FAIL."""
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip 0009 to Ratified")
    result = _run_gate(repo, [])
    ok = (
        result.returncode == 1
        and "no ee key" in result.stdout
        and "no market key" in result.stdout
        and "0009-a-record.md" in result.stdout
    )
    return ok, result.stdout


def case_positive_control(repo: Path) -> tuple[bool, str]:
    """The same flip, carried by two proper keys, must PASS."""
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip 0009 to Ratified")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(), login="ee-key-holder"),
            _review(MARKET_OK(), login="market-key-holder"),
        ],
    )
    ok = result.returncode == 0 and "PASS" in result.stdout
    return ok, result.stdout


def case_same_reviewer_twice(repo: Path) -> tuple[bool, str]:
    """Two keys naming the same reviewer= is one holder wearing two hats."""
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(EE_OK("solo-agent"), login="a"),
            _review(MARKET_OK("solo-agent"), login="b"),
        ],
    )
    return (result.returncode == 1 and "same reviewer" in result.stdout), result.stdout


def case_key_posted_by_pr_author(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(), login=AUTHOR),
            _review(MARKET_OK(), login="market-key-holder"),
        ],
    )
    return (
        result.returncode == 1 and "posted by the PR author" in result.stdout
    ), result.stdout


def case_reviewer_field_is_pr_author(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(AUTHOR), login="ee-key-holder"),
            _review(MARKET_OK(), login="market-key-holder"),
        ],
    )
    return (
        result.returncode == 1 and "is the PR author" in result.stdout
    ), result.stdout


def case_only_one_kind(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(repo, [_review(EE_OK(), login="ee-key-holder")])
    return (
        result.returncode == 1 and "no market key" in result.stdout
    ), result.stdout


def case_non_releasing_verdict(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(_marker("ee", "request-changes", "ee-agent-7"), login="ee"),
            _review(MARKET_OK(), login="market"),
        ],
    )
    return (
        result.returncode == 1 and "does not release" in result.stdout
    ), result.stdout


def case_rereview_after_request_changes(repo: Path) -> tuple[bool, str]:
    """The ordinary review cycle must not deadlock the gate.

    GitHub's review list is **append-only**: when the ee key-holder posts
    `request-changes`, the author fixes the finding, and the same holder then
    posts `approve`, both reviews are in `/pulls/<N>/reviews` forever. The
    superseded `request-changes` is a review that happened; it is not a veto
    over the later `approve`, so the flip must be released.
    """
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(
                _marker("ee", "request-changes", "ee-agent-7"), login="ee-key-holder"
            ),
            _review(EE_OK(), login="ee-key-holder"),
            _review(MARKET_OK(), login="market-key-holder"),
        ],
    )
    ok = (
        result.returncode == 0
        and "PASS" in result.stdout
        and "FAIL" not in result.stdout
        and "ee key: reviewer=ee-agent-7 verdict=approve" in result.stdout
        and "superseded" in result.stdout
    )
    return ok, result.stdout


def case_market_rereview_after_uncompetitive(repo: Path) -> tuple[bool, str]:
    """The same shape on the market side: uncompetitive -> competitive."""
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(), login="ee-key-holder"),
            _review(
                _marker("market", "uncompetitive", "market-agent-3"),
                login="market-key-holder",
            ),
            _review(MARKET_OK(), login="market-key-holder"),
        ],
    )
    ok = (
        result.returncode == 0
        and "PASS" in result.stdout
        and "FAIL" not in result.stdout
        and "market key: reviewer=market-agent-3 verdict=competitive" in result.stdout
        and "superseded" in result.stdout
    )
    return ok, result.stdout


def case_decoy_key_cannot_veto(repo: Path) -> tuple[bool, str]:
    """A junk RATIFY-KEY review must not make ratification unpassable.

    Two genuine, usable keys are present. Alongside them sit two unusable
    candidates of the same kinds -- one `ee` marker posted by the PR author
    (rejected by requirement 4) and one non-releasing `market` marker from an
    unrelated login (rejected by requirement 2). Neither is a key, and neither
    may deny the keys that are: otherwise anyone who can post a review on the
    PR -- including the author -- holds a permanent veto over the act.
    """
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(), login="ee-key-holder"),
            _review(MARKET_OK(), login="market-key-holder"),
            _review(_marker("ee", "approve", "decoy-agent"), login=AUTHOR),
            _review(
                _marker("market", "uncompetitive", "drive-by-agent"),
                login="random-passerby",
            ),
        ],
    )
    ok = (
        result.returncode == 0
        and "PASS" in result.stdout
        and "FAIL" not in result.stdout
        and "ee key: reviewer=ee-agent-7 verdict=approve" in result.stdout
        and "market key: reviewer=market-agent-3 verdict=competitive" in result.stdout
        # the rejected candidates are still reported, as audit notes
        and "posted by the PR author" in result.stdout
        and "does not release" in result.stdout
    )
    return ok, result.stdout


def case_withdrawn_approval_does_not_release(repo: Path) -> tuple[bool, str]:
    """The converse of the re-review cases: a holder may take a key back.

    `approve` followed by `request-changes` from the *same* `reviewer=` is a
    withdrawn key, not a standing one. Only a reviewer's latest marker of a
    given kind is operative, so this must FAIL -- otherwise "supersede" would
    only ever work in the direction that releases.
    """
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(), login="ee-key-holder"),
            _review(
                _marker("ee", "request-changes", "ee-agent-7"), login="ee-key-holder"
            ),
            _review(MARKET_OK(), login="market-key-holder"),
        ],
    )
    ok = (
        result.returncode == 1
        and "does not release" in result.stdout
        and "ee key: reviewer=ee-agent-7 verdict=approve" not in result.stdout
    )
    return ok, result.stdout


def case_dismissed_review(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(), login="ee"),
            _review(MARKET_OK(), login="market", state="DISMISSED"),
        ],
    )
    return (
        result.returncode == 1
        and "DISMISSED" in result.stdout
        and "no market key" in result.stdout
    ), result.stdout


def case_placeholder_marker(repo: Path) -> tuple[bool, str]:
    """A marker still carrying the skill's <agent-id> template is not a key."""
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review(_marker("ee", "approve", "<agent-id>"), login="ee"),
            _review(MARKET_OK(), login="market"),
        ],
    )
    return (
        result.returncode == 1 and "placeholder" in result.stdout
    ), result.stdout


def case_malformed_marker_missing_field(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = _run_gate(
        repo,
        [
            _review("<!-- RATIFY-KEY: ee verdict=approve -->\nbody\n", login="ee"),
            _review(MARKET_OK(), login="market"),
        ],
    )
    return (
        result.returncode == 1 and "missing field" in result.stdout
    ), result.stdout


def case_prose_edit_to_proposed_record(repo: Path) -> tuple[bool, str]:
    """Editing a Proposed record is not a flip -- zero reviews must PASS."""
    path = repo / "spec" / "decision-records" / "0009-a-record.md"
    path.write_text(PROPOSED_DR.replace("Something is proposed.", "Something else."))
    _commit(repo, "edit prose")
    result = _run_gate(repo, [])
    return (
        result.returncode == 0 and "no spec/ Status line is flipped" in result.stdout
    ), result.stdout


def case_reconcile_away_from_ratified(repo: Path) -> tuple[bool, str]:
    """DR 0006's own repair shape: Ratified -> 'PROPOSED -- not ratified'."""
    path = repo / "spec" / "decision-records" / "0009-a-record.md"
    path.write_text(RATIFIED_DR)
    _commit(repo, "flip")
    _git(repo, "update-ref", BASE_REF, "HEAD")
    path.write_text(
        RATIFIED_DR.replace(
            "Status: **Ratified 2026-09-27** -- two RATIFY-KEY reviews on PR #99.",
            "Status: **PROPOSED -- not ratified.** The act never ran.",
        )
    )
    _commit(repo, "reconcile away from Ratified")
    result = _run_gate(repo, [])
    return (
        result.returncode == 0 and "no spec/ Status line is flipped" in result.stdout
    ), result.stdout


def case_edit_on_already_ratified_line(repo: Path) -> tuple[bool, str]:
    """A typo fix on an already-Ratified line is not a new flip."""
    path = repo / "spec" / "decision-records" / "0009-a-record.md"
    path.write_text(RATIFIED_DR)
    _commit(repo, "flip")
    _git(repo, "update-ref", BASE_REF, "HEAD")
    path.write_text(
        RATIFIED_DR.replace(
            "two RATIFY-KEY reviews on PR #99.",
            "two RATIFY-KEY reviews on PR #99 (merge commit abc1234)."
        )
    )
    _commit(repo, "amend the citation")
    result = _run_gate(repo, [])
    return (
        result.returncode == 0 and "no spec/ Status line is flipped" in result.stdout
    ), result.stdout


def case_new_file_born_ratified(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0010-new.md").write_text(RATIFIED_DR)
    _commit(repo, "add a record born Ratified")
    result = _run_gate(repo, [])
    return (
        result.returncode == 1 and "0010-new.md" in result.stdout
    ), result.stdout


def case_new_file_born_proposed(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0010-new.md").write_text(PROPOSED_DR)
    _commit(repo, "add a Proposed record")
    result = _run_gate(repo, [])
    return (
        result.returncode == 0 and "no spec/ Status line is flipped" in result.stdout
    ), result.stdout


def case_status_outside_spec_ignored(repo: Path) -> tuple[bool, str]:
    """A Ratified Status line outside spec/ is out of the gate's scope."""
    (repo / "docs" / "note.md").write_text("# Note\n\nStatus: Ratified 2026-09-27\n")
    _commit(repo, "add a docs note")
    result = _run_gate(repo, [])
    return (
        result.returncode == 0 and "no spec/ Status line is flipped" in result.stdout
    ), result.stdout


def case_gate_self_modification(repo: Path) -> tuple[bool, str]:
    """A PR may not ratify and rewrite its own gate in one move."""
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    (repo / "scripts" / "check_ratification_gate.py").write_text("# neutered\n")
    _commit(repo, "flip and edit the gate")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(), login="ee-key-holder"),
            _review(MARKET_OK(), login="market-key-holder"),
        ],
    )
    return (
        result.returncode == 1 and "modifies the gate's own files" in result.stdout
    ), result.stdout


def case_lint_wiring_self_modification(repo: Path) -> tuple[bool, str]:
    """`package.json` is guarded too: it is where `npm run lint` calls the gate.

    Deleting the gate's invocation from the lint script in the same diff that
    flips a Status line is the same move as editing the gate itself.
    """
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    (repo / "package.json").write_text('{"scripts": {"lint": "true"}}\n')
    _commit(repo, "flip and rewire lint")
    result = _run_gate(
        repo,
        [
            _review(EE_OK(), login="ee-key-holder"),
            _review(MARKET_OK(), login="market-key-holder"),
        ],
    )
    return (
        result.returncode == 1
        and "modifies the gate's own files" in result.stdout
        and "package.json" in result.stdout
    ), result.stdout


def case_same_login_note_only(repo: Path) -> tuple[bool, str]:
    """Two keys, one forge login: a NOTE by default (DR 0006's open question)."""
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    reviews = [
        _review(EE_OK(), login="shared-bot"),
        _review(MARKET_OK(), login="shared-bot"),
    ]
    lenient = _run_gate(repo, reviews)
    strict = _run_gate(
        repo, reviews, extra_args=("--require-distinct-principals",)
    )
    ok = (
        lenient.returncode == 0
        and "same forge login" in lenient.stdout
        and strict.returncode == 1
        and "require-distinct-principals" in strict.stdout
    )
    return ok, lenient.stdout + "\n--- strict ---\n" + strict.stdout


def case_no_base_ref_skips(repo: Path) -> tuple[bool, str]:
    (repo / "spec" / "decision-records" / "0009-a-record.md").write_text(RATIFIED_DR)
    _commit(repo, "flip")
    result = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--repo-root",
            str(repo),
            "--base-ref",
            "refs/heads/does-not-exist",
            "--pr-author",
            AUTHOR,
            "--reviews-file",
            str(repo / "reviews.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.returncode == 0 and "SKIP" in result.stdout), result.stdout


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
)


def case_real_spec_status_vocabulary() -> tuple[bool, str]:
    """Every real `Status:` line under spec/ uses the documented vocabulary.

    Exercises the shipped value parser against this repo's actual prose (which
    is markdown-heavy: bold, em-dashes, parentheticals) without pinning any
    file to a particular status -- so a real ratification does not break it,
    but an undocumented status word does.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    import check_ratification_gate as gate  # noqa: PLC0415

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

    ok, detail = case_real_spec_status_vocabulary()
    print(f"[{'PASS' if ok else 'FAIL'}] case_real_spec_status_vocabulary -- {detail}")
    if not ok:
        failures += 1

    total = len(FIXTURE_CASES) + 1
    print(f"\n{total - failures}/{total} cases behaved as specified")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
