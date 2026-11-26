#!/usr/bin/env python3
"""Self-test for `verification/check_records.py`.

The record linter is the only thing standing between "append-only evidence"
as a documented intention and append-only evidence as an enforced property.
A linter that silently stops catching a violation class is worse than no
linter, so each violation class the convention names in
`verification/README.md` gets an executable negative test here.

Method: build a throwaway git repo in a temp dir, copy the *real*
`check_records.py` into its `verification/` directory (the linter resolves
its repo root from `__file__`, so the copy lints the fixture repo), and run
it as a subprocess exactly the way `npm run lint` and CI do. Nothing is
monkeypatched, so this exercises the shipped entry point rather than a
stand-in.

Zero dependencies beyond the Python 3 standard library and `git`.

Usage:
    python3 verification/test_check_records.py
Exit codes: 0 all cases behave as specified, 1 at least one did not.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LINTER = SCRIPT_DIR / "check_records.py"
REPO_UTILS = SCRIPT_DIR / "_repo_utils.py"

BASE_REF = "refs/heads/fixture-base"

DUMMY_RTL = "module dut(input wire clk); endmodule\n"


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=record-linter-selftest",
            "-c",
            "user.email=selftest@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo}: {result.stderr.strip()}"
        )
    return result.stdout


def make_record(
    record_id: str,
    experiment: str,
    *,
    inputs: list[tuple],
    supersedes=None,
    omit_field: str | None = None,
    omit_provenance_key: str | None = None,
    links: str | None = None,
    prose_extra: str = "",
) -> str:
    """Render a record that satisfies the convention in
    `verification/README.md`, optionally omitting one required prose field
    so a negative case can be built from it. `links` overrides the default
    **Links** value and `prose_extra` appends extra prose (e.g. indented
    sub-bullets) after the field bullets, for the artifact-link cases
    (#545)."""
    meta = {
        "record_id": record_id,
        "experiment": experiment,
        "supersedes": supersedes,
        "git_revision": "0" * 40,
        "provenance": {
            "klt_version": "0.0.0-selftest",
            "pdk": {"name": "n/a", "version": "n/a"},
            "deck": {"content_hash": "n/a"},
            "inputs": [
                {"path": path, "content_hash": content_hash}
                for path, content_hash in inputs
            ],
        },
    }
    if omit_provenance_key is not None:
        meta["provenance"].pop(omit_provenance_key)
    if isinstance(supersedes, list):
        supersedes_prose = ", ".join(str(s) for s in supersedes)
    elif isinstance(supersedes, str):
        supersedes_prose = supersedes
    else:
        supersedes_prose = "none"
    fields = [
        ("Record ID", record_id),
        ("Claim", "`docs/baseline.md#the-measurement` -- fixture claim"),
        ("Design provenance", "rtl (`rtl/dut.v` @ `" + "0" * 40 + "`)"),
        ("Run configuration", "fixture run, no real simulator invoked"),
        ("Statistical convention", "N/A (fixture)"),
        ("Result", "**Overall: PASS** (fixture)"),
        ("klt provenance", "klt 0.0.0-selftest; PDK: n/a; deck content_hash: n/a"),
        ("Links", links if links is not None else "Design under test: `rtl/dut.v`"),
        ("Timestamp / author", "2026-01-01T00:00:00Z, selftest"),
        ("Supersedes", supersedes_prose),
    ]
    bullets = "\n".join(
        f"- **{name}**: {value}" for name, value in fields if name != omit_field
    )
    return (
        "<!-- record-meta\n"
        + json.dumps(meta, indent=2)
        + "\n-->\n\n"
        + f"# Record {record_id}\n\n"
        + bullets
        + "\n"
        + prose_extra
    )


def build_fixture_repo(tmp: Path) -> Path:
    """A minimal repo with one valid record committed, and `BASE_REF`
    pointing at that commit so the append-only check has a base to diff."""
    repo = tmp / "fixture"
    (repo / "rtl").mkdir(parents=True)
    (repo / "verification" / "records" / "demo" / "records").mkdir(parents=True)

    (repo / "rtl" / "dut.v").write_text(DUMMY_RTL, encoding="utf-8")
    shutil.copyfile(LINTER, repo / "verification" / "check_records.py")
    shutil.copyfile(REPO_UTILS, repo / "verification" / "_repo_utils.py")

    record = make_record(
        "20260101-000000-abc1234",
        "demo",
        inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
    )
    (
        repo / "verification" / "records" / "demo" / "records" / "20260101-000000-abc1234.md"
    ).write_text(record, encoding="utf-8")

    _git(repo, "init", "--quiet")
    _commit(repo, "fixture: initial record")
    _git(repo, "update-ref", BASE_REF, "HEAD")
    return repo


def run_linter(repo: Path, *extra_args: str) -> tuple[int, str]:
    result = subprocess.run(
        [
            sys.executable,
            str(repo / "verification" / "check_records.py"),
            "--base-ref",
            BASE_REF,
            "--require-append-only",
            *extra_args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def record_path(repo: Path, experiment: str, record_id: str) -> Path:
    return (
        repo / "verification" / "records" / experiment / "records" / f"{record_id}.md"
    )


NEW_ID = "20260102-000000-abc1234"  # the id a case mints its "new" record under


def _commit(repo: Path, msg: str) -> None:
    """Stage everything and commit -- the fixture cases' shared epilogue."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", msg)


def _commit_record(
    repo: Path,
    record_id: str = NEW_ID,
    *,
    experiment: str = "demo",
    meta_experiment: str | None = None,
    inputs: list[tuple] | None = None,
    msg: str = "fixture: add record",
    **make_kwargs,
) -> None:
    """Render a record with `make_record` (inputs default to the fixture's
    `rtl/dut.v`; `meta_experiment` overrides the experiment baked into the
    record so it can disagree with the directory it lands in), write it under
    `experiment`'s records directory, and commit it (#565)."""
    record = make_record(
        record_id,
        meta_experiment if meta_experiment is not None else experiment,
        inputs=(
            inputs if inputs is not None else [("rtl/dut.v", _sha256_text(DUMMY_RTL))]
        ),
        **make_kwargs,
    )
    path = record_path(repo, experiment, record_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record, encoding="utf-8")
    _commit(repo, msg)


def _update_rtl(repo: Path, suffix: str = "// v2\n") -> list[tuple]:
    """Overwrite the fixture's dummy Verilog with `DUMMY_RTL + suffix` and
    return the record-inputs pair citing the new content."""
    new_rtl = DUMMY_RTL + suffix
    (repo / "rtl" / "dut.v").write_text(new_rtl, encoding="utf-8")
    return [("rtl/dut.v", _sha256_text(new_rtl))]


# --- cases -----------------------------------------------------------------
# Each case mutates a fresh fixture repo and returns nothing; the harness
# asserts the expected exit code and a substring of the linter's output.


def case_valid(repo: Path) -> None:
    """Control: an untouched fixture must pass, or every negative case below
    would pass for the wrong reason."""


def case_missing_required_field(repo: Path) -> None:
    _commit_record(repo, omit_field="Claim", msg="fixture: record missing Claim")


def case_missing_required_meta_key(repo: Path) -> None:
    _commit_record(repo, omit_provenance_key="klt_version",
                   msg="fixture: record missing klt_version")


def case_edited_existing_record(repo: Path) -> None:
    path = record_path(repo, "demo", "20260101-000000-abc1234")
    path.write_text(
        path.read_text(encoding="utf-8").replace("fixture claim", "edited claim"),
        encoding="utf-8",
    )
    _commit(repo, "fixture: edit an existing record")


def case_deleted_existing_record(repo: Path) -> None:
    _git(
        repo,
        "rm",
        "--quiet",
        "verification/records/demo/records/20260101-000000-abc1234.md",
    )
    _commit(repo, "fixture: delete an existing record")


def case_stale_provenance_hash(repo: Path) -> None:
    _update_rtl(repo, "// the RTL changed after the record was minted\n")
    _commit(repo, "fixture: change the cited source")


def case_superseded_record_exempt_from_freshness(repo: Path) -> None:
    """A superseded record is frozen history: it may legitimately cite a
    source that has since changed. Only the live record must be fresh."""
    _commit_record(repo, "20260103-000000-abc1234", inputs=_update_rtl(repo),
                   supersedes="20260101-000000-abc1234",
                   msg="fixture: supersede the first record")


def case_shared_id_superseded_elsewhere_still_checked(repo: Path) -> None:
    """Record IDs are `<timestamp>-<sha>` and are NOT unique across
    experiments: a batch mint gives every experiment the same ID. The
    freshness exemption must be keyed on (experiment, record_id), so that
    superseding experiment A's copy of an ID does not also exempt experiment
    B's still-live copy of that ID (#157)."""
    shared_id = "20260101-000000-abc1234"
    _commit_record(repo, shared_id, experiment="other",
                   msg="fixture: second experiment, same id")
    # Supersede only `demo`'s copy, then change the cited source.
    case_superseded_record_exempt_from_freshness(repo)


ZEROED_HASH = "sha256:" + "0" * 64


def case_nested_copy_not_exempted_by_leaf_name(repo: Path) -> None:
    """The Judge's repro on #183: a tampered copy of a superseded record
    (every input hash zeroed) planted under a NESTED directory whose leaf name
    matches a real experiment, `verification/records/zz/demo/records/`. The
    genuine `demo` supersession must not exempt it -- and nested experiment
    directories are rejected outright, so the leaf name can never alias."""
    case_superseded_record_exempt_from_freshness(repo)  # demo: B supersedes A
    old_id = "20260101-000000-abc1234"
    nested = repo / "verification" / "records" / "zz" / "demo" / "records"
    nested.mkdir(parents=True)
    (nested / f"{old_id}.md").write_text(
        make_record(old_id, "demo", inputs=[("rtl/dut.v", ZEROED_HASH)]),
        encoding="utf-8",
    )
    _commit(repo, "fixture: tampered nested copy")


def case_self_supersession_rejected(repo: Path) -> None:
    """A record that lists its own ID in `supersedes` must not exempt itself
    from the freshness check (#183 review)."""
    _commit_record(repo, experiment="selfsup", inputs=[("rtl/dut.v", ZEROED_HASH)],
                   supersedes=NEW_ID, msg="fixture: record supersedes itself")


def case_supersession_cycle_rejected(repo: Path) -> None:
    """Two records that supersede each other (A -> B -> A) would each exempt
    the other. A record may only supersede a strictly earlier ID, so a cycle
    cannot be expressed (#183 review)."""
    a, b = "20260102-000000-abc1234", "20260103-000000-abc1234"
    _commit_record(repo, a, experiment="cyc",
                   inputs=[("rtl/dut.v", ZEROED_HASH)], supersedes=b,
                   msg="fixture: supersession cycle")
    _commit_record(repo, b, experiment="cyc",
                   inputs=[("rtl/dut.v", ZEROED_HASH)], supersedes=a,
                   msg="fixture: supersession cycle")


def case_bad_record_id_grammar(repo: Path) -> None:
    _commit_record(repo, "not-a-record-id", msg="fixture: malformed record id")


def case_dangling_supersedes(repo: Path) -> None:
    _commit_record(repo, "20260104-000000-abc1234",
                   supersedes="20250101-000000-deadbee",
                   msg="fixture: supersedes a nonexistent record")


def case_new_record_is_a_pure_addition(repo: Path) -> None:
    """Adding a record must NOT trip the append-only check -- otherwise the
    convention would forbid the very thing it exists to allow."""
    _commit_record(repo, "20260105-000000-abc1234", msg="fixture: add a new record")


# --- #183 second review: symlinks, degenerate inputs, crash cases ----------


# --- #371 / 2AMLogic/2am#7038: the exempt toolchain input path -------------

TOOLCHAIN_PATH = "layout/toolchain.json"
TOOLCHAIN_PINNED = '{"klt_install": "klayout-tools==0.8.0"}\n'
TOOLCHAIN_FLEET = '{"klt_install": "klayout-tools (fleet version)"}\n'


def case_stale_toolchain_hash_is_exempt(repo: Path) -> None:
    """The 2026-11-09 fleet-version ruling (2AMLogic/2am#7038, issue #371):
    editing `layout/toolchain.json` must NOT stale a live record that cites
    it. The recorded hash stays as frozen provenance -- a record keeps the
    toolchain version that produced it -- rather than forcing a repo-wide
    re-mint on every fleet bump."""
    (repo / "layout").mkdir(exist_ok=True)
    (repo / "layout" / "toolchain.json").write_text(TOOLCHAIN_PINNED, encoding="utf-8")
    _commit_record(
        repo,
        inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL)),
                (TOOLCHAIN_PATH, _sha256_text(TOOLCHAIN_PINNED))],
        msg="fixture: live record citing the toolchain pin",
    )
    (repo / "layout" / "toolchain.json").write_text(TOOLCHAIN_FLEET, encoding="utf-8")
    _commit(repo, "fixture: drop the per-repo klt pin")


def case_other_input_still_checked_on_exempt_record(repo: Path) -> None:
    """The exemption is per-PATH, never a per-record opt-out: a record that
    cites the exempt toolchain file must still fail on a stale hash for any
    other input it cites."""
    case_stale_toolchain_hash_is_exempt(repo)
    case_stale_provenance_hash(repo)


def case_exempt_input_must_still_be_tracked(repo: Path) -> None:
    """Exempt from the hash *comparison* only, not from check 7: a live
    record's toolchain input must still name a git-tracked regular file, so a
    record citing a path that does not exist is still an error."""
    _commit_record(
        repo,
        inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL)),
                (TOOLCHAIN_PATH, _sha256_text(TOOLCHAIN_PINNED))],
        msg="fixture: cite a toolchain file that was never committed",
    )


def case_exempt_input_hash_must_still_be_wellformed(repo: Path) -> None:
    """Exempt from the comparison, not from check 7's grammar: an empty
    content_hash on the toolchain input is still an error, so the exemption
    cannot be used to smuggle in an unverifiable entry."""
    (repo / "layout").mkdir(exist_ok=True)
    (repo / "layout" / "toolchain.json").write_text(TOOLCHAIN_PINNED, encoding="utf-8")
    _commit_record(repo, inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL)),
                                 (TOOLCHAIN_PATH, "")],
                   msg="fixture: toolchain input with an empty content_hash")


def case_symlinked_record_file(repo: Path) -> None:
    """The Judge's A2: a record file that is a symlink to a file outside
    `verification/records/`. git versions only the link text, so the target
    could be edited after merge with no append-only violation."""
    (repo / "docs").mkdir()
    (repo / "docs" / "evil-record.md").write_text(
        make_record(NEW_ID, "demo", inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))]),
        encoding="utf-8",
    )
    record_path(repo, "demo", NEW_ID).symlink_to("../../../../docs/evil-record.md")
    _commit(repo, "fixture: symlinked record file")


def case_symlinked_experiment_dir(repo: Path) -> None:
    """The Judge's A1: an experiment directory that is a symlink to a real
    one, committed together with a change that makes the real record stale."""
    (repo / "verification" / "records" / "evil").symlink_to("demo")
    case_stale_provenance_hash(repo)


def case_empty_content_hash(repo: Path) -> None:
    _commit_record(repo, inputs=[("rtl/dut.v", "")], msg="fixture: empty hash")


def case_null_content_hash(repo: Path) -> None:
    _commit_record(repo, inputs=[("rtl/dut.v", None)], msg="fixture: null hash")


def case_empty_input_path(repo: Path) -> None:
    _commit_record(repo, inputs=[("", ZEROED_HASH)], msg="fixture: empty path")


def case_dev_null_input_path(repo: Path) -> None:
    _commit_record(repo, inputs=[("/dev/null", _sha256_text(""))],
                   msg="fixture: /dev/null input")


def case_absolute_input_path(repo: Path) -> None:
    """An absolute path to a real file with the right hash: it passed the
    freshness check before, but it is not a repo-relative input."""
    _commit_record(
        repo,
        inputs=[(str((repo / "rtl" / "dut.v").resolve()), _sha256_text(DUMMY_RTL))],
        msg="fixture: absolute input path",
    )


def case_dotdot_escape_input_path(repo: Path) -> None:
    """A `..` path to a real file outside the repo, with the right hash."""
    outside = "outside the repo\n"
    (repo.parent / "outside.txt").write_text(outside, encoding="utf-8")
    _commit_record(repo, inputs=[("../outside.txt", _sha256_text(outside))],
                   msg="fixture: .. escape")


def case_unicode_lookalike_experiment(repo: Path) -> None:
    """The Judge's A9c: an experiment named with a Cyrillic look-alike letter.
    It used to crash the linter (git octal-quotes non-ASCII paths)."""
    name = "d\u0435mo"  # Cyrillic small ie, not Latin e
    _commit_record(repo, experiment=name, msg="fixture: unicode look-alike experiment")


def case_supersedes_list_non_string_entry(repo: Path) -> None:
    """The Judge's A8g revisited for the list form (#472): a list is legal,
    but only of record-id strings -- a non-string entry must fail cleanly,
    not crash or be silently accepted."""
    _commit_record(repo, supersedes=["20260101-000000-abc1234", 123],
                   msg="fixture: supersedes list with a non-string entry")


# --- #472: the list form of `supersedes` -------------------------------------
# One record may supersede several earlier leaves at once (a collapse
# re-mint), so parallel branches stop doubling the live-leaf count. Every
# entry obeys the same rules as the scalar form, judged per entry.


LEAF_1 = "20260101-000000-abc1234"  # the fixture repo's initial record
LEAF_2 = "20260101-000005-abc1234"
LATER = "20260103-000000-abc1234"
COLLAPSER = "20260102-000000-abc1234"


def case_supersedes_list_valid(repo: Path) -> None:
    """A list naming two existing, strictly earlier records is valid."""
    _commit_record(repo, LEAF_2)
    _commit_record(repo, COLLAPSER, supersedes=[LEAF_1, LEAF_2],
                   msg="fixture: one record superseding two leaves")


def case_supersedes_list_exempts_both_from_freshness(repo: Path) -> None:
    """Every listed id is superseded: both stale leaves are frozen history,
    only the live collapsing record must be fresh (#472)."""
    _commit_record(repo, LEAF_2)
    _commit_record(repo, COLLAPSER, inputs=_update_rtl(repo),
                   supersedes=[LEAF_1, LEAF_2],
                   msg="fixture: collapse a stale leaf pair")


def case_supersedes_list_missing_id(repo: Path) -> None:
    _commit_record(repo, LEAF_2)
    _commit_record(repo, COLLAPSER, supersedes=[LEAF_1, "20250101-000000-deadbee"],
                   msg="fixture: list names a nonexistent record")


def case_supersedes_list_self_id(repo: Path) -> None:
    _commit_record(repo, LEAF_2)
    _commit_record(repo, COLLAPSER, supersedes=[LEAF_1, COLLAPSER],
                   msg="fixture: list names its own record")


def case_supersedes_list_later_id(repo: Path) -> None:
    """A list entry naming a LATER record (which must therefore exist) does
    not sort strictly earlier -- rejected, and it exempts nothing."""
    _commit_record(repo, LEAF_2)
    _commit_record(repo, LATER)
    _commit_record(repo, COLLAPSER, supersedes=[LEAF_1, LATER],
                   msg="fixture: list names a later record")


def case_supersedes_list_duplicate_id(repo: Path) -> None:
    _commit_record(repo, LEAF_2)
    _commit_record(repo, COLLAPSER, supersedes=[LEAF_1, LEAF_1],
                   msg="fixture: list names the same record twice")


def _stale_leaf_with_sibling_list(repo: Path, siblings: list) -> None:
    """LEAF_1 is stale (rtl changed) and listed beside invalid `siblings`
    by a fresh collapser: LEAF_1's supersession must still take effect."""
    if LEAF_2 in siblings:
        _commit_record(repo, LEAF_2)
    _commit_record(repo, COLLAPSER, inputs=_update_rtl(repo),
                   supersedes=[LEAF_1, *siblings],
                   msg="fixture: list with a valid entry beside invalid ones")


def case_supersedes_list_valid_beside_int(repo: Path) -> None:
    _stale_leaf_with_sibling_list(repo, [7])


def case_supersedes_list_valid_beside_nulls(repo: Path) -> None:
    _stale_leaf_with_sibling_list(repo, [None, None])


def case_supersedes_list_valid_beside_duplicates(repo: Path) -> None:
    _stale_leaf_with_sibling_list(repo, [LEAF_1, LEAF_2])


def case_supersedes_empty_list(repo: Path) -> None:
    _commit_record(repo, COLLAPSER, supersedes=[], msg="fixture: empty supersedes list")


def case_scalar_and_list_supersede_mixed(repo: Path) -> None:
    """Scalar and list supersessions coexist in one experiment, and a list
    may name a record another record already supersedes (#472 test-plan
    edge): the double-naming exempts nothing beyond the named ids, and the
    stale leaves are exempt while both naming records stay live and fresh."""
    inputs = _update_rtl(repo)
    _commit_record(repo, LEAF_2)
    _commit_record(repo, "20260104-000000-abc1234", inputs=inputs,
                   supersedes=LEAF_1, msg="fixture: scalar supersession of leaf 1")
    _commit_record(repo, "20260105-000000-abc1234", inputs=inputs,
                   supersedes=[LEAF_1, LEAF_2],
                   msg="fixture: list supersession naming an already-superseded record")


def case_gitlink_record(repo: Path) -> None:
    """A tracked mode-160000 entry matching the record pathspec used to
    crash with FileNotFoundError / IsADirectoryError (#187)."""
    _git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{'1' * 40},verification/records/demo/records/{NEW_ID}.md",
    )
    _git(repo, "commit", "--quiet", "-m", "fixture: gitlink record")


def case_gitlink_record_empty_dir(repo: Path) -> None:
    """Uninitialised-submodule shape: an empty directory on disk."""
    case_gitlink_record(repo)
    record_path(repo, "demo", NEW_ID).mkdir()


def case_experiment_mismatch(repo: Path) -> None:
    _commit_record(repo, meta_experiment="other",
                   msg="fixture: experiment disagrees with directory")


# --- #545: a record's artifact links must resolve -----------------------------
#
# PR #455 shipped a record whose **Links** row cited `test_icarus.log`
# alongside two tracked sibling files, with the log itself absent from the
# tree; the linter passed it. The cases below pin the regression: the mixed
# row (so a dangling destination cannot hide behind siblings that resolve),
# the untracked-local-file loophole, the directory / shared-run / external
# pass forms, indented links outside **Links**, and superseded records.

LINK_ID = "20260106-000000-abc1234"  # the record under test's own run
SHARED_ID = "20260105-000000-abc1234"  # a sibling run sharing the artifacts tree


def _artifact_dir(repo: Path, experiment: str, run_id: str) -> Path:
    d = repo / "verification" / "records" / experiment / "artifacts" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mixed_links_row(run_id: str) -> str:
    return (
        f"[envelope](../artifacts/{run_id}/klt-functional-verification.json), "
        f"[results](../artifacts/{run_id}/results_icarus.xml), "
        f"[pad measurements](../artifacts/{run_id}/test_icarus.log)"
    )


def case_artifact_link_missing_log_fails(repo: Path) -> None:
    """The PR #455 shape: a mixed **Links** row citing two tracked sibling
    artifacts and one log that is not in the tree at all."""
    art = _artifact_dir(repo, "demo", LINK_ID)
    (art / "klt-functional-verification.json").write_text("{}\n", encoding="utf-8")
    (art / "results_icarus.xml").write_text("<results/>\n", encoding="utf-8")
    _commit_record(repo, LINK_ID, links=_mixed_links_row(LINK_ID),
                   msg="fixture: record citing a missing artifact log")


def case_artifact_link_untracked_log_fails(repo: Path) -> None:
    """The log exists on disk but was never committed: an untracked local
    file cannot substantiate the citation (the linter reads the git
    inventory, not the working tree)."""
    case_artifact_link_missing_log_fails(repo)
    (
        _artifact_dir(repo, "demo", LINK_ID) / "test_icarus.log"
    ).write_text("pad measurements\n", encoding="utf-8")  # deliberately untracked


def case_artifact_link_tracked_log_passes(repo: Path) -> None:
    art = _artifact_dir(repo, "demo", LINK_ID)
    (art / "klt-functional-verification.json").write_text("{}\n", encoding="utf-8")
    (art / "results_icarus.xml").write_text("<results/>\n", encoding="utf-8")
    (art / "test_icarus.log").write_text("pad measurements\n", encoding="utf-8")
    _commit_record(repo, LINK_ID, links=_mixed_links_row(LINK_ID),
                   msg="fixture: record with every cited artifact tracked")


def case_artifact_link_valid_forms_pass(repo: Path) -> None:
    """The legitimate forms a strict checker must not reject: a
    whole-run-directory link (`[run artifacts](../artifacts/<id>/)`, the
    `firmware-nec-ir` shape), a shared artifact under a sibling record id,
    an indented link outside **Links**, an external URL, a fragment-only
    link, a non-artifact link that does not resolve, and a would-be-dangling
    artifact path that appears only as inline code."""
    own = _artifact_dir(repo, "demo", LINK_ID)
    (own / "klt-functional-verification.json").write_text("{}\n", encoding="utf-8")
    (own / "test_icarus.log").write_text("pad measurements\n", encoding="utf-8")
    shared = _artifact_dir(repo, "demo", SHARED_ID)
    (shared / "results_icarus.xml").write_text("<results/>\n", encoding="utf-8")
    links = (
        f"[run artifacts](../artifacts/{LINK_ID}/), "
        f"[shared results](../artifacts/{SHARED_ID}/results_icarus.xml), "
        f"[spec](https://example.com/target-spec), [this record](#record), "
        f"[unrelated](../../../../README-not-committed)"
    )
    prose_extra = (
        f"  - indented bullet: [log](../artifacts/{LINK_ID}/test_icarus.log)\n"
        f"  - code span, not a link: `../artifacts/{LINK_ID}/never-committed.log`\n"
    )
    _commit_record(repo, LINK_ID, links=links, prose_extra=prose_extra,
                   msg="fixture: every legitimate artifact-link form")


def case_artifact_link_indented_dangling_fails(repo: Path) -> None:
    """Indented links outside the **Links** field are citations too: a
    dangling artifact link in a sub-bullet must fail, not hide."""
    _commit_record(repo, LINK_ID, links="Design under test: `rtl/dut.v`",
                   msg="fixture: indented bullet cites a missing artifact log",
                   prose_extra=(
                       f"  - indented bullet: [log](../artifacts/{LINK_ID}/test_icarus.log)\n"
                   ))


def case_superseded_record_artifact_link_checked(repo: Path) -> None:
    """Supersession freezes a record's provenance hashes, not its
    citations: a superseded record's dangling artifact link still fails."""
    case_artifact_link_missing_log_fails(repo)
    _commit_record(repo, "20260107-000000-abc1234", supersedes=LINK_ID,
                   msg="fixture: supersede the record with the dangling artifact link")


CASES = [
    (
        "a gitlink record entry fails cleanly",
        case_gitlink_record,
        1,
        "has git mode 160000",
    ),
    (
        "a gitlink over an empty directory fails cleanly",
        case_gitlink_record_empty_dir,
        1,
        "has git mode 160000",
    ),
    (
        "a record whose experiment disagrees with its directory fails",
        case_experiment_mismatch,
        1,
        "experiment `other` disagrees with its directory `demo`",
    ),
    # --- #545: artifact links must resolve ---
    (
        "a mixed Links row with one missing artifact fails",
        case_artifact_link_missing_log_fails,
        1,
        "demo/records/20260106-000000-abc1234.md: artifact link "
        "`(../artifacts/20260106-000000-abc1234/test_icarus.log)` does not resolve",
    ),
    (
        "an untracked local log does not satisfy the citation",
        case_artifact_link_untracked_log_fails,
        1,
        "demo/records/20260106-000000-abc1234.md: artifact link "
        "`(../artifacts/20260106-000000-abc1234/test_icarus.log)` does not resolve",
    ),
    (
        "a mixed Links row with every artifact tracked passes",
        case_artifact_link_tracked_log_passes,
        0,
        "PASS: all records valid",
    ),
    (
        "every legitimate artifact-link form passes",
        case_artifact_link_valid_forms_pass,
        0,
        "PASS: all records valid",
    ),
    (
        "a dangling artifact link in an indented bullet fails",
        case_artifact_link_indented_dangling_fails,
        1,
        "demo/records/20260106-000000-abc1234.md: artifact link "
        "`(../artifacts/20260106-000000-abc1234/test_icarus.log)` does not resolve",
    ),
    (
        "a superseded record's artifact links are still checked",
        case_superseded_record_artifact_link_checked,
        1,
        "demo/records/20260106-000000-abc1234.md: artifact link "
        "`(../artifacts/20260106-000000-abc1234/test_icarus.log)` does not resolve",
    ),
    # (name, mutation, expected_exit, expected_substring)
    ("valid record passes", case_valid, 0, "PASS: all records valid"),
    (
        "record missing a required prose field fails",
        case_missing_required_field,
        1,
        "missing required field bullet `- **Claim**:`",
    ),
    (
        "record missing a required provenance key fails",
        case_missing_required_meta_key,
        1,
        "provenance missing required key `klt_version`",
    ),
    (
        "edited existing record fails (append-only)",
        case_edited_existing_record,
        1,
        "append-only violation",
    ),
    (
        "deleted existing record fails (append-only)",
        case_deleted_existing_record,
        1,
        "append-only violation",
    ),
    (
        "stale provenance hash fails",
        case_stale_provenance_hash,
        1,
        "is stale",
    ),
    (
        "superseded record is exempt from hash freshness",
        case_superseded_record_exempt_from_freshness,
        0,
        "PASS: all records valid",
    ),
    (
        "same id superseded in another experiment does not exempt a live record",
        case_shared_id_superseded_elsewhere_still_checked,
        1,
        "other/records/20260101-000000-abc1234.md: provenance hash for `rtl/dut.v` is stale",
    ),
    (
        "nested copy of a superseded record is not exempted by its leaf name",
        case_nested_copy_not_exempted_by_leaf_name,
        1,
        "nested experiment directories are not allowed",
    ),
    (
        "nested copy is also checked for freshness",
        case_nested_copy_not_exempted_by_leaf_name,
        1,
        "zz/demo/records/20260101-000000-abc1234.md: provenance hash for `rtl/dut.v` is stale",
    ),
    (
        "a record superseding itself fails",
        case_self_supersession_rejected,
        1,
        "supersedes itself",
    ),
    (
        "a self-superseding record is not exempt from freshness",
        case_self_supersession_rejected,
        1,
        "selfsup/records/20260102-000000-abc1234.md: provenance hash for `rtl/dut.v` is stale",
    ),
    (
        "a supersession cycle fails",
        case_supersession_cycle_rejected,
        1,
        "does not sort strictly earlier",
    ),
    (
        "malformed record id fails",
        case_bad_record_id_grammar,
        1,
        "is not a valid record-id",
    ),
    (
        "supersedes naming a nonexistent record fails",
        case_dangling_supersedes,
        1,
        "which has no record",
    ),
    (
        "adding a new record is allowed",
        case_new_record_is_a_pure_addition,
        0,
        "no append-only violations",
    ),
    (
        "a symlinked record file fails",
        case_symlinked_record_file,
        1,
        "demo/records/20260102-000000-abc1234.md: is a symlink",
    ),
    (
        "a symlinked experiment directory fails",
        case_symlinked_experiment_dir,
        1,
        "verification/records/evil: is a symlink",
    ),
    (
        "a symlinked experiment directory does not hide a stale record",
        case_symlinked_experiment_dir,
        1,
        "demo/records/20260101-000000-abc1234.md: provenance hash for `rtl/dut.v` is stale",
    ),
    (
        "an empty input content_hash fails",
        case_empty_content_hash,
        1,
        "has content_hash ''",
    ),
    (
        "a null input content_hash fails",
        case_null_content_hash,
        1,
        "has content_hash None",
    ),
    (
        "an empty input path fails",
        case_empty_input_path,
        1,
        "has an empty or non-string path ''",
    ),
    (
        "a /dev/null input path fails",
        case_dev_null_input_path,
        1,
        "path `/dev/null` is absolute",
    ),
    (
        "an absolute input path fails",
        case_absolute_input_path,
        1,
        "is absolute; inputs must be repo-relative",
    ),
    (
        "a `..` input path escaping the repo fails",
        case_dotdot_escape_input_path,
        1,
        "path `../outside.txt` must be a repo-relative POSIX path with no `..` component",
    ),
    (
        "a unicode look-alike experiment name fails cleanly",
        case_unicode_lookalike_experiment,
        1,
        "must match `[a-z0-9][a-z0-9._-]*`",
    ),
    (
        "a supersedes list with a non-string entry fails cleanly",
        case_supersedes_list_non_string_entry,
        1,
        "list entries must be record-id strings, not int",
    ),
    # --- #472: the list form of `supersedes` ---
    (
        "a list of a valid id and nulls reports the nulls without crashing",
        case_supersedes_list_valid_beside_nulls,
        1,
        "list entries must be record-id strings, not NoneType",
    ),
    (
        "a valid id beside a non-string entry is still superseded (no stale error)",
        case_supersedes_list_valid_beside_int,
        1,
        "not int",
    ),
    (
        "a supersedes list of two valid earlier records passes",
        case_supersedes_list_valid,
        0,
        "PASS: all records valid",
    ),
    (
        "every id in a supersedes list is exempt from freshness",
        case_supersedes_list_exempts_both_from_freshness,
        0,
        "PASS: all records valid",
    ),
    (
        "a supersedes list entry naming a nonexistent record fails",
        case_supersedes_list_missing_id,
        1,
        "which has no record",
    ),
    (
        "a supersedes list entry naming its own record fails",
        case_supersedes_list_self_id,
        1,
        "supersedes itself",
    ),
    (
        "a supersedes list entry naming a later record fails",
        case_supersedes_list_later_id,
        1,
        "does not sort strictly earlier",
    ),
    (
        "a supersedes list naming the same record twice fails",
        case_supersedes_list_duplicate_id,
        1,
        "names duplicate id(s)",
    ),
    (
        "an empty supersedes list fails",
        case_supersedes_empty_list,
        1,
        "must not be an empty list",
    ),
    (
        "scalar and list supersessions coexist; double-naming is harmless",
        case_scalar_and_list_supersede_mixed,
        0,
        "PASS: all records valid",
    ),
    (
        "a stale layout/toolchain.json hash is exempt from freshness",
        case_stale_toolchain_hash_is_exempt,
        0,
        "PASS: all records valid",
    ),
    (
        "a stale non-exempt input still fails on a record citing the toolchain",
        case_other_input_still_checked_on_exempt_record,
        1,
        "demo/records/20260102-000000-abc1234.md: provenance hash for `rtl/dut.v` is stale",
    ),
    (
        "the exempt toolchain input must still be a tracked file",
        case_exempt_input_must_still_be_tracked,
        1,
        "input `layout/toolchain.json` no longer exists in the working tree",
    ),
    (
        "the exempt toolchain input must still carry a well-formed hash",
        case_exempt_input_hash_must_still_be_wellformed,
        1,
        "`layout/toolchain.json` has content_hash ''",
    ),
]

# --- --base-sha: the merge queue's entry point (issue #432) ----------------
# The workflow passes github.event.merge_group.base_sha as an explicit base
# commit; the linter must diff directly against it and fail explicitly when
# it is absent or unavailable. Each entry adds a base resolver run against
# the fixture repo before the linter is invoked.

BASE_SHA_UNAVAILABLE = "0" * 40


def _base_sha_of_fixture(repo: Path) -> str:
    return _git(repo, "rev-parse", BASE_REF).strip()


BASE_SHA_CASES = [
    (
        "an unavailable --base-sha commit fails explicitly",
        case_valid,
        lambda repo: BASE_SHA_UNAVAILABLE,
        1,
        "append-only check: base commit `" + BASE_SHA_UNAVAILABLE + "` is not available",
    ),
    (
        "an empty --base-sha fails explicitly (a payload without a base)",
        case_valid,
        lambda repo: "",
        1,
        "append-only check: base commit `` is not available",
    ),
    (
        "a record modified relative to --base-sha fails (append-only)",
        case_edited_existing_record,
        _base_sha_of_fixture,
        1,
        "append-only violation",
    ),
    (
        "adding a new record is allowed against --base-sha",
        case_new_record_is_a_pure_addition,
        _base_sha_of_fixture,
        0,
        "no append-only violations",
    ),
]


def _linter_problems(
    exit_code: int, output: str, expected_exit: int, expected_substring: str = ""
) -> list[str]:
    """Problems with one linter run; empty means it behaved as specified."""
    problems = []
    if exit_code != expected_exit:
        problems.append(f"exit {exit_code}, expected {expected_exit}")
    if expected_substring and expected_substring not in output:
        problems.append(f"output missing {expected_substring!r}")
    if "Traceback (most recent call last)" in output:
        problems.append("linter crashed with a traceback")
    return problems


def _report_case(name: str, problems: list[str], output: str) -> bool:
    """Report one self-test case; False when it did not behave as specified."""
    if problems:
        print(f"FAIL: {name}")
        for problem in problems:
            print(f"  - {problem}")
        print("  --- linter output ---")
        for line in output.splitlines():
            print(f"  | {line}")
        return False
    print(f"OK:   {name}")
    return True


def _run_fixture(mutate, extra_args_fn=None) -> tuple[int, str]:
    """Build a fresh throwaway fixture repo, apply `mutate`, and run the
    linter on it (`extra_args_fn`, when given, returns the extra argv to
    append, e.g. `("--base-sha", <sha>)`). Returns (exit_code, output)."""
    with tempfile.TemporaryDirectory(prefix="record-linter-selftest-") as tmpdir:
        repo = build_fixture_repo(Path(tmpdir))
        mutate(repo)
        extra_args = extra_args_fn(repo) if extra_args_fn is not None else ()
        return run_linter(repo, *extra_args)


def main() -> int:
    if not LINTER.exists():
        print(f"FATAL: {LINTER} not found", file=sys.stderr)
        return 1
    if not REPO_UTILS.exists():
        print(f"FATAL: {REPO_UTILS} not found", file=sys.stderr)
        return 1

    # Per-entry rule (#472): an invalid sibling is reported but never makes
    # the valid entry's target look live (stale) again. These cases keep
    # their specialized per-record stale-ID comparisons (#542) and count in
    # the banner and summary totals.
    stale_cases = (
        ("valid id beside an int stays superseded", case_supersedes_list_valid_beside_int, set()),
        ("valid id beside nulls stays superseded", case_supersedes_list_valid_beside_nulls, set()),
        ("duplicate list leaves the uniquely named sibling superseded",
         case_supersedes_list_valid_beside_duplicates, {LEAF_1}),
    )
    total = len(stale_cases) + len(CASES) + len(BASE_SHA_CASES)
    failures = 0

    print(f"== check_records.py self-test ({total} cases) ==")

    for name, mutate, expected_stale in stale_cases:
        exit_code, output = _run_fixture(mutate)
        stale_ids = {rid for rid in (LEAF_1, LEAF_2) for line in output.splitlines()
                     if f"{rid}.md:" in line and "is stale" in line}
        problems = []
        if stale_ids != expected_stale:
            problems.append(
                f"stale records {sorted(stale_ids)}, expected {sorted(expected_stale)}")
        problems.extend(_linter_problems(exit_code, output, expected_exit=1))
        if not _report_case(name, problems, output):
            failures += 1

    for name, mutate, expected_exit, expected_substring in CASES:
        exit_code, output = _run_fixture(mutate)
        problems = _linter_problems(exit_code, output, expected_exit, expected_substring)
        if not _report_case(name, problems, output):
            failures += 1

    for name, mutate, base_sha_of, expected_exit, expected_substring in BASE_SHA_CASES:
        exit_code, output = _run_fixture(
            mutate, lambda repo, b=base_sha_of: ("--base-sha", b(repo)))
        problems = _linter_problems(exit_code, output, expected_exit, expected_substring)
        if not _report_case(name, problems, output):
            failures += 1

    print()
    if failures:
        print(f"FAIL: {failures}/{total} self-test case(s) did not behave as specified")
        return 1
    print(f"PASS: all {total} self-test cases behaved as specified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
