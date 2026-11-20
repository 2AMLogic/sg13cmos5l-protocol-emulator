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
) -> str:
    """Render a record that satisfies the convention in
    `verification/README.md`, optionally omitting one required prose field
    so a negative case can be built from it."""
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
        ("Links", "Design under test: `rtl/dut.v`"),
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
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: initial record")
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


# --- cases -----------------------------------------------------------------
# Each case mutates a fresh fixture repo and returns nothing; the harness
# asserts the expected exit code and a substring of the linter's output.


def case_valid(repo: Path) -> None:
    """Control: an untouched fixture must pass, or every negative case below
    would pass for the wrong reason."""


def case_missing_required_field(repo: Path) -> None:
    new_id = "20260102-000000-abc1234"
    path = record_path(repo, "demo", new_id)
    path.write_text(
        make_record(
            new_id,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            omit_field="Claim",
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: record missing Claim")


def case_missing_required_meta_key(repo: Path) -> None:
    new_id = "20260102-000000-abc1234"
    record_path(repo, "demo", new_id).write_text(
        make_record(
            new_id,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            omit_provenance_key="klt_version",
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: record missing klt_version")


def case_edited_existing_record(repo: Path) -> None:
    path = record_path(repo, "demo", "20260101-000000-abc1234")
    path.write_text(
        path.read_text(encoding="utf-8").replace("fixture claim", "edited claim"),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: edit an existing record")


def case_deleted_existing_record(repo: Path) -> None:
    _git(
        repo,
        "rm",
        "--quiet",
        "verification/records/demo/records/20260101-000000-abc1234.md",
    )
    _git(repo, "commit", "--quiet", "-m", "fixture: delete an existing record")


def case_stale_provenance_hash(repo: Path) -> None:
    (repo / "rtl" / "dut.v").write_text(
        DUMMY_RTL + "// the RTL changed after the record was minted\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: change the cited source")


def case_superseded_record_exempt_from_freshness(repo: Path) -> None:
    """A superseded record is frozen history: it may legitimately cite a
    source that has since changed. Only the live record must be fresh."""
    new_rtl = DUMMY_RTL + "// v2\n"
    (repo / "rtl" / "dut.v").write_text(new_rtl, encoding="utf-8")
    new_id = "20260103-000000-abc1234"
    record_path(repo, "demo", new_id).write_text(
        make_record(
            new_id,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(new_rtl))],
            supersedes="20260101-000000-abc1234",
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: supersede the first record")


def case_shared_id_superseded_elsewhere_still_checked(repo: Path) -> None:
    """Record IDs are `<timestamp>-<sha>` and are NOT unique across
    experiments: a batch mint gives every experiment the same ID. The
    freshness exemption must be keyed on (experiment, record_id), so that
    superseding experiment A's copy of an ID does not also exempt experiment
    B's still-live copy of that ID (#157)."""
    shared_id = "20260101-000000-abc1234"
    (repo / "verification" / "records" / "other" / "records").mkdir(parents=True)
    record_path(repo, "other", shared_id).write_text(
        make_record(shared_id, "other", inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))]),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: second experiment, same id")
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
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: tampered nested copy")


def case_self_supersession_rejected(repo: Path) -> None:
    """A record that lists its own ID in `supersedes` must not exempt itself
    from the freshness check (#183 review)."""
    rid = "20260102-000000-abc1234"
    (repo / "verification" / "records" / "selfsup" / "records").mkdir(parents=True)
    record_path(repo, "selfsup", rid).write_text(
        make_record(rid, "selfsup", inputs=[("rtl/dut.v", ZEROED_HASH)], supersedes=rid),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: record supersedes itself")


def case_supersession_cycle_rejected(repo: Path) -> None:
    """Two records that supersede each other (A -> B -> A) would each exempt
    the other. A record may only supersede a strictly earlier ID, so a cycle
    cannot be expressed (#183 review)."""
    a, b = "20260102-000000-abc1234", "20260103-000000-abc1234"
    (repo / "verification" / "records" / "cyc" / "records").mkdir(parents=True)
    record_path(repo, "cyc", a).write_text(
        make_record(a, "cyc", inputs=[("rtl/dut.v", ZEROED_HASH)], supersedes=b),
        encoding="utf-8",
    )
    record_path(repo, "cyc", b).write_text(
        make_record(b, "cyc", inputs=[("rtl/dut.v", ZEROED_HASH)], supersedes=a),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: supersession cycle")


def case_bad_record_id_grammar(repo: Path) -> None:
    bad = record_path(repo, "demo", "not-a-record-id")
    bad.write_text(
        make_record(
            "not-a-record-id",
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: malformed record id")


def case_dangling_supersedes(repo: Path) -> None:
    new_id = "20260104-000000-abc1234"
    record_path(repo, "demo", new_id).write_text(
        make_record(
            new_id,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            supersedes="20250101-000000-deadbee",
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: supersedes a nonexistent record")


def case_new_record_is_a_pure_addition(repo: Path) -> None:
    """Adding a record must NOT trip the append-only check -- otherwise the
    convention would forbid the very thing it exists to allow."""
    new_id = "20260105-000000-abc1234"
    record_path(repo, "demo", new_id).write_text(
        make_record(
            new_id, "demo", inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))]
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: add a new record")


# --- #183 second review: symlinks, degenerate inputs, crash cases ----------

NEW_ID = "20260102-000000-abc1234"


def _add_record(repo: Path, experiment: str, record_id: str, text: str, msg: str) -> None:
    path = record_path(repo, experiment, record_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", msg)


def _add_record_with_inputs(repo: Path, inputs: list[tuple], msg: str) -> None:
    _add_record(repo, "demo", NEW_ID, make_record(NEW_ID, "demo", inputs=inputs), msg)


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
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "fixture: symlinked record file")


def case_symlinked_experiment_dir(repo: Path) -> None:
    """The Judge's A1: an experiment directory that is a symlink to a real
    one, committed together with a change that makes the real record stale."""
    (repo / "verification" / "records" / "evil").symlink_to("demo")
    case_stale_provenance_hash(repo)


def case_empty_content_hash(repo: Path) -> None:
    _add_record_with_inputs(repo, [("rtl/dut.v", "")], "fixture: empty hash")


def case_null_content_hash(repo: Path) -> None:
    _add_record_with_inputs(repo, [("rtl/dut.v", None)], "fixture: null hash")


def case_empty_input_path(repo: Path) -> None:
    _add_record_with_inputs(repo, [("", ZEROED_HASH)], "fixture: empty path")


def case_dev_null_input_path(repo: Path) -> None:
    _add_record_with_inputs(
        repo, [("/dev/null", _sha256_text(""))], "fixture: /dev/null input"
    )


def case_absolute_input_path(repo: Path) -> None:
    """An absolute path to a real file with the right hash: it passed the
    freshness check before, but it is not a repo-relative input."""
    _add_record_with_inputs(
        repo,
        [(str((repo / "rtl" / "dut.v").resolve()), _sha256_text(DUMMY_RTL))],
        "fixture: absolute input path",
    )


def case_dotdot_escape_input_path(repo: Path) -> None:
    """A `..` path to a real file outside the repo, with the right hash."""
    outside = "outside the repo\n"
    (repo.parent / "outside.txt").write_text(outside, encoding="utf-8")
    _add_record_with_inputs(
        repo, [("../outside.txt", _sha256_text(outside))], "fixture: .. escape"
    )


def case_unicode_lookalike_experiment(repo: Path) -> None:
    """The Judge's A9c: an experiment named with a Cyrillic look-alike letter.
    It used to crash the linter (git octal-quotes non-ASCII paths)."""
    name = "d\u0435mo"  # Cyrillic small ie, not Latin e
    _add_record(
        repo,
        name,
        NEW_ID,
        make_record(NEW_ID, name, inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))]),
        "fixture: unicode look-alike experiment",
    )


def case_supersedes_list_non_string_entry(repo: Path) -> None:
    """The Judge's A8g revisited for the list form (#472): a list is legal,
    but only of record-id strings -- a non-string entry must fail cleanly,
    not crash or be silently accepted."""
    _add_record(
        repo,
        "demo",
        NEW_ID,
        make_record(
            NEW_ID,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            supersedes=["20260101-000000-abc1234", 123],
        ),
        "fixture: supersedes list with a non-string entry",
    )


# --- #472: the list form of `supersedes` -------------------------------------
# One record may supersede several earlier leaves at once (a collapse
# re-mint), so parallel branches stop doubling the live-leaf count. Every
# entry obeys the same rules as the scalar form, judged per entry.


def _add_demo_leaf(repo: Path, record_id: str) -> None:
    _add_record(
        repo,
        "demo",
        record_id,
        make_record(record_id, "demo", inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))]),
        f"fixture: add leaf {record_id}",
    )


LEAF_1 = "20260101-000000-abc1234"  # the fixture repo's initial record
LEAF_2 = "20260101-000005-abc1234"
LATER = "20260103-000000-abc1234"
COLLAPSER = "20260102-000000-abc1234"


def case_supersedes_list_valid(repo: Path) -> None:
    """A list naming two existing, strictly earlier records is valid."""
    _add_demo_leaf(repo, LEAF_2)
    _add_record(
        repo,
        "demo",
        COLLAPSER,
        make_record(
            COLLAPSER,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            supersedes=[LEAF_1, LEAF_2],
        ),
        "fixture: one record superseding two leaves",
    )


def case_supersedes_list_exempts_both_from_freshness(repo: Path) -> None:
    """Every listed id is superseded: both stale leaves are frozen history,
    only the live collapsing record must be fresh (#472)."""
    new_rtl = DUMMY_RTL + "// v2\n"
    (repo / "rtl" / "dut.v").write_text(new_rtl, encoding="utf-8")
    _add_demo_leaf(repo, LEAF_2)
    _add_record(
        repo,
        "demo",
        COLLAPSER,
        make_record(
            COLLAPSER,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(new_rtl))],
            supersedes=[LEAF_1, LEAF_2],
        ),
        "fixture: collapse a stale leaf pair",
    )


def case_supersedes_list_missing_id(repo: Path) -> None:
    _add_demo_leaf(repo, LEAF_2)
    _add_record(
        repo,
        "demo",
        COLLAPSER,
        make_record(
            COLLAPSER,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            supersedes=[LEAF_1, "20250101-000000-deadbee"],
        ),
        "fixture: list names a nonexistent record",
    )


def case_supersedes_list_self_id(repo: Path) -> None:
    _add_demo_leaf(repo, LEAF_2)
    _add_record(
        repo,
        "demo",
        COLLAPSER,
        make_record(
            COLLAPSER,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            supersedes=[LEAF_1, COLLAPSER],
        ),
        "fixture: list names its own record",
    )


def case_supersedes_list_later_id(repo: Path) -> None:
    """A list entry naming a LATER record (which must therefore exist) does
    not sort strictly earlier -- rejected, and it exempts nothing."""
    _add_demo_leaf(repo, LEAF_2)
    _add_demo_leaf(repo, LATER)
    _add_record(
        repo,
        "demo",
        COLLAPSER,
        make_record(
            COLLAPSER,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            supersedes=[LEAF_1, LATER],
        ),
        "fixture: list names a later record",
    )


def case_supersedes_list_duplicate_id(repo: Path) -> None:
    _add_demo_leaf(repo, LEAF_2)
    _add_record(
        repo,
        "demo",
        COLLAPSER,
        make_record(
            COLLAPSER,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            supersedes=[LEAF_1, LEAF_1],
        ),
        "fixture: list names the same record twice",
    )


def _stale_leaf_with_sibling_list(repo: Path, siblings: list) -> None:
    """LEAF_1 is stale (rtl changed) and listed beside invalid `siblings`
    by a fresh collapser: LEAF_1's supersession must still take effect."""
    new_rtl = DUMMY_RTL + "// v2\n"
    (repo / "rtl" / "dut.v").write_text(new_rtl, encoding="utf-8")
    if LEAF_2 in siblings:
        _add_demo_leaf(repo, LEAF_2)
    _add_record(
        repo,
        "demo",
        COLLAPSER,
        make_record(
            COLLAPSER,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(new_rtl))],
            supersedes=[LEAF_1, *siblings],
        ),
        "fixture: list with a valid entry beside invalid ones",
    )


def case_supersedes_list_valid_beside_int(repo: Path) -> None:
    _stale_leaf_with_sibling_list(repo, [7])


def case_supersedes_list_valid_beside_nulls(repo: Path) -> None:
    _stale_leaf_with_sibling_list(repo, [None, None])


def case_supersedes_list_valid_beside_duplicates(repo: Path) -> None:
    _stale_leaf_with_sibling_list(repo, [LEAF_1, LEAF_2])


def case_supersedes_empty_list(repo: Path) -> None:
    _add_record(
        repo,
        "demo",
        COLLAPSER,
        make_record(
            COLLAPSER,
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))],
            supersedes=[],
        ),
        "fixture: empty supersedes list",
    )


def case_scalar_and_list_supersede_mixed(repo: Path) -> None:
    """Scalar and list supersessions coexist in one experiment, and a list
    may name a record another record already supersedes (#472 test-plan
    edge): the double-naming exempts nothing beyond the named ids, and the
    stale leaves are exempt while both naming records stay live and fresh."""
    new_rtl = DUMMY_RTL + "// v2\n"
    (repo / "rtl" / "dut.v").write_text(new_rtl, encoding="utf-8")
    _add_demo_leaf(repo, LEAF_2)
    _add_record(
        repo,
        "demo",
        "20260104-000000-abc1234",
        make_record(
            "20260104-000000-abc1234",
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(new_rtl))],
            supersedes=LEAF_1,
        ),
        "fixture: scalar supersession of leaf 1",
    )
    _add_record(
        repo,
        "demo",
        "20260105-000000-abc1234",
        make_record(
            "20260105-000000-abc1234",
            "demo",
            inputs=[("rtl/dut.v", _sha256_text(new_rtl))],
            supersedes=[LEAF_1, LEAF_2],
        ),
        "fixture: list supersession naming an already-superseded record",
    )


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
    _add_record(
        repo,
        "demo",
        NEW_ID,
        make_record(NEW_ID, "other", inputs=[("rtl/dut.v", _sha256_text(DUMMY_RTL))]),
        "fixture: experiment disagrees with directory",
    )


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


def main() -> int:
    if not LINTER.exists():
        print(f"FATAL: {LINTER} not found", file=sys.stderr)
        return 1
    if not REPO_UTILS.exists():
        print(f"FATAL: {REPO_UTILS} not found", file=sys.stderr)
        return 1

    # Per-entry rule (#472): an invalid sibling is reported but never makes
    # the valid entry's target look live (stale) again.
    for name, mutate in (
        ("valid id beside an int stays superseded", case_supersedes_list_valid_beside_int),
        ("valid id beside nulls stays superseded", case_supersedes_list_valid_beside_nulls),
        ("duplicate list leaves the uniquely named sibling superseded",
         case_supersedes_list_valid_beside_duplicates),
    ):
        with tempfile.TemporaryDirectory(prefix="record-linter-selftest-") as tmpdir:
            repo = build_fixture_repo(Path(tmpdir))
            mutate(repo)
            exit_code, output = run_linter(repo)
            if "stale" in output.lower() or "Traceback" in output or exit_code != 1:
                print(f"FAIL: {name}\n" + "\n".join("  | " + l for l in output.splitlines()))
                return 1
            print(f"OK:   {name}")

    print(f"== check_records.py self-test ({len(CASES) + len(BASE_SHA_CASES)} cases) ==")
    failures = 0
    for name, mutate, expected_exit, expected_substring in CASES:
        with tempfile.TemporaryDirectory(prefix="record-linter-selftest-") as tmpdir:
            repo = build_fixture_repo(Path(tmpdir))
            mutate(repo)
            exit_code, output = run_linter(repo)

            problems = []
            if exit_code != expected_exit:
                problems.append(f"exit {exit_code}, expected {expected_exit}")
            if expected_substring not in output:
                problems.append(f"output missing {expected_substring!r}")
            if "Traceback (most recent call last)" in output:
                problems.append("linter crashed with a traceback")

            if problems:
                failures += 1
                print(f"FAIL: {name}")
                for problem in problems:
                    print(f"  - {problem}")
                print("  --- linter output ---")
                for line in output.splitlines():
                    print(f"  | {line}")
            else:
                print(f"OK:   {name}")

    for name, mutate, base_sha_of, expected_exit, expected_substring in BASE_SHA_CASES:
        with tempfile.TemporaryDirectory(prefix="record-linter-selftest-") as tmpdir:
            repo = build_fixture_repo(Path(tmpdir))
            mutate(repo)
            exit_code, output = run_linter(repo, "--base-sha", base_sha_of(repo))

            problems = []
            if exit_code != expected_exit:
                problems.append(f"exit {exit_code}, expected {expected_exit}")
            if expected_substring not in output:
                problems.append(f"output missing {expected_substring!r}")
            if "Traceback (most recent call last)" in output:
                problems.append("linter crashed with a traceback")

            if problems:
                failures += 1
                print(f"FAIL: {name}")
                for problem in problems:
                    print(f"  - {problem}")
                print("  --- linter output ---")
                for line in output.splitlines():
                    print(f"  | {line}")
            else:
                print(f"OK:   {name}")

    print()
    total = len(CASES) + len(BASE_SHA_CASES)
    if failures:
        print(f"FAIL: {failures}/{total} self-test case(s) did not behave as specified")
        return 1
    print(f"PASS: all {total} self-test cases behaved as specified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
