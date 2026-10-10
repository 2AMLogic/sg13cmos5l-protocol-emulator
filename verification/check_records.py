#!/usr/bin/env python3
"""Evidence-record linter for `verification/records/`.

This is the enforcement half of the convention documented in
`verification/README.md` -- **that document is authoritative**; if this
script and the README ever disagree, fix the script.

Zero dependencies beyond the Python 3 standard library and `git`. Reads
tracked files only (`git ls-files`), so untracked scratch runs are never
linted.

Checks, per record `verification/records/<experiment>/records/<record-id>.md`:

1. **Filename / Record ID grammar** -- the filename stem and the metadata
   block's `record_id` must both match `YYYYMMDD-HHMMSS-<7-40 hex chars>`
   and must agree with each other.
2. **Required fields present** -- the `<!-- record-meta ... -->` JSON block
   must be valid JSON with the required keys (see `REQUIRED_META_KEYS`), and
   every field in `REQUIRED_PROSE_FIELDS` must appear as a non-empty
   top-level markdown bullet (`- **Field**: <non-empty value>`).
0. **Layout** -- a record must sit at exactly
   `verification/records/<experiment>/records/<record-id>.md`. The tracked
   pathspec (`**`) also matches nested directories, so a nested path such as
   `verification/records/zz/<experiment>/records/<id>.md` is rejected
   outright: a nested copy must never alias a real experiment (#157).
   Experiments are identified everywhere by their path relative to
   `verification/records/`, never by a directory's leaf name. The experiment
   directory name must match `[a-z0-9][a-z0-9._-]*`, so a Unicode look-alike
   cannot pose as a real experiment (#183 review).
3. **Supersedes integrity** -- a non-null `supersedes` value must name a
   record that exists in the same experiment directory, must not be the
   record's own ID, and must sort strictly earlier than the record's own ID
   (IDs lead with a timestamp). The ordering rule makes supersession cycles
   (A supersedes B, B supersedes A) impossible. A supersession that breaks
   any of these rules is an error and exempts nothing (#157).
4. **Provenance hash freshness** -- for every record that is *not*
   superseded by another record (a "live" record), every
   `provenance.inputs[].content_hash` is recomputed from the working tree
   and must match. A live record whose cited source has since changed is a
   stale record -- exactly the case this check exists to catch. Superseded
   records are exempt (they are frozen history, not a claim about current
   sources). "Superseded" means superseded by a record in the SAME
   experiment directory: record IDs are not unique across experiments (a
   batch mint stamps one ID on many), so the exemption is keyed on
   `(experiment, record_id)`, never on the ID alone (#157).
5. **Append-only** -- every path under `verification/records/` must be
   either untracked-before (a pure addition) or unchanged, relative to the
   merge-base with `origin/main` (or `--base-ref`). Any modification,
   rename, or deletion fails. If the base ref cannot be resolved, this
   check prints SKIP unless `--require-append-only` is given.
6. **No symlinks** -- no tracked entry under `verification/records/` may
   be a symlink (git mode `120000`), and no record may be reached through a
   symlinked file or directory on disk. git stores only a symlink's link
   text, so editing its target never shows in the append-only diff while
   the linter would read the edited target as the record (#183 review).
7. **Inputs are re-checkable** -- every `provenance.inputs[]` entry needs a
   `content_hash` of the form `sha256:<64 lowercase hex>` and a `path` that
   is a non-empty, repo-relative POSIX path with no `..` component (no
   absolute paths such as `/dev/null`). For a live record the path must also
   name a git-tracked regular file inside the repo. An empty or null hash or
   path would otherwise skip freshness forever (#183 review). Superseded
   records are frozen history: their inputs must still be well-formed, but
   the file may since have been deleted.

Usage:
    python3 verification/check_records.py
    python3 verification/check_records.py --require-append-only
    python3 verification/check_records.py --base-ref origin/main

Exit codes: 0 pass, 1 a check failed.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import sys
from pathlib import Path

from _repo_utils import REPO_ROOT, run_git, sha256_of

RECORDS_ROOT = REPO_ROOT / "verification" / "records"

RECORD_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7,40}$")
EXPERIMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
CONTENT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

REQUIRED_META_KEYS = (
    "record_id",
    "experiment",
    "supersedes",
    "git_revision",
    "provenance",
)
REQUIRED_PROVENANCE_KEYS = ("klt_version", "pdk", "deck", "inputs")

REQUIRED_PROSE_FIELDS = (
    "Record ID",
    "Claim",
    "Design provenance",
    "Run configuration",
    "Statistical convention",
    "Result",
    "klt provenance",
    "Links",
    "Timestamp / author",
    "Supersedes",
)

_PLACEHOLDER_VALUES = {"", "tbd", "todo", "fixme", "(fill in)", "(fill me in)"}


class LintError(Exception):
    pass


def experiment_key(path: Path) -> str:
    """The experiment a record belongs to, as its directory path relative
    to `RECORDS_ROOT` (e.g. `die-area-baseline`). Never the leaf name alone:
    `zz/die-area-baseline` and `die-area-baseline` are different keys, so a
    nested copy cannot alias a real experiment (#157)."""
    return path.parent.parent.relative_to(RECORDS_ROOT).as_posix()


def layout_error(path: Path) -> str | None:
    """Records must sit at exactly `<experiment>/records/<id>.md` under
    `RECORDS_ROOT`. Anything deeper (or shallower) is rejected (#157)."""
    try:
        parts = path.relative_to(RECORDS_ROOT).parts
    except ValueError:
        return f"{path}: record is not under {RECORDS_ROOT}"
    if len(parts) != 3 or parts[1] != "records":
        return (
            f"{path}: record must sit at "
            f"`verification/records/<experiment>/records/<record-id>.md`; "
            f"nested experiment directories are not allowed"
        )
    if not EXPERIMENT_RE.match(parts[0]):
        return (
            f"{path}: experiment directory {parts[0]!r} must match "
            f"`[a-z0-9][a-z0-9._-]*` (ASCII only, so a look-alike name such "
            f"as a Cyrillic letter or zero-width space cannot pose as a real "
            f"experiment)"
        )
    return None


def supersession_error(path: Path, supersedes, known_ids: set) -> str | None:
    """Why `path`'s `supersedes` value is invalid, or None if it is a
    valid supersession that may exempt its target from freshness."""
    stem = path.stem
    experiment = experiment_key(path)
    if supersedes not in known_ids:
        return (
            f"{path}: supersedes `{supersedes}`, which has no record "
            f"in `{experiment}/records/`"
        )
    if supersedes == stem:
        return f"{path}: supersedes itself (`{supersedes}`); a record cannot supersede its own ID"
    if not str(supersedes) < stem:
        return (
            f"{path}: supersedes `{supersedes}`, which does not sort strictly "
            f"earlier than this record's ID `{stem}`; a record may only supersede "
            f"an earlier record (this also rules out supersession cycles)"
        )
    return None


def _tracked_record_files() -> list[Path]:
    # `-z`: without it git octal-quotes non-ASCII paths (core.quotePath), and
    # a look-alike directory name would crash the linter instead of being
    # linted (#183 review).
    out = run_git("ls-files", "-z", "--", "verification/records/**/records/*.md")
    return sorted(REPO_ROOT / name for name in out.split("\0") if name)


def tracked_symlink_errors() -> list[str]:
    """Every tracked entry under `verification/records/` with git mode
    `120000` (a symlink). git versions only the link text, so the target can
    be edited after merge with no append-only violation (#183 review)."""
    out = run_git("ls-files", "-s", "-z", "--", "verification/records/")
    errors = []
    for entry in out.split("\0"):
        if not entry:
            continue
        info, _, name = entry.partition("\t")
        mode = info.split(" ")[0]
        if mode == "120000":
            errors.append(
                f"{REPO_ROOT / name}: is a symlink; nothing under "
                f"verification/records/ may be a symlink (its target could be "
                f"edited with no append-only violation)"
            )
        elif mode != "100644":
            errors.append(
                f"{REPO_ROOT / name}: has git mode {mode}; every tracked entry "
                f"under verification/records/ must be a regular file (mode "
                f"100644), not a gitlink, executable or other special entry"
            )
    return errors


def symlink_error(path: Path) -> str | None:
    """Reject a record that is, or is reached through, a symlink on disk
    anywhere below `RECORDS_ROOT` (file or directory)."""
    try:
        rel = path.relative_to(RECORDS_ROOT)
    except ValueError:
        return None
    current = RECORDS_ROOT
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return (
                f"{path}: `{current.relative_to(REPO_ROOT)}` is a symlink; "
                f"records must not be, or sit under, a symlink"
            )
    return None


def _is_tracked(rel_path: str) -> bool:
    try:
        return bool(run_git("ls-files", "-z", "--error-unmatch", "--", rel_path))
    except subprocess.CalledProcessError:
        return False


def input_error(path: Path, item) -> str | None:
    """Why a `provenance.inputs[]` entry is not re-checkable, or None. Applies
    to every record, superseded or live (#183 review)."""
    prefix = f"{path}: record-meta.provenance.inputs entry"
    if not isinstance(item, dict) or "path" not in item or "content_hash" not in item:
        return f"{prefix} needs `path` and `content_hash`"
    rel_path = item["path"]
    content_hash = item["content_hash"]
    if not isinstance(content_hash, str) or not CONTENT_HASH_RE.match(content_hash):
        return (
            f"{prefix} `{rel_path}` has content_hash {content_hash!r}; "
            f"expected `sha256:` followed by 64 lowercase hex digits"
        )
    if not isinstance(rel_path, str) or not rel_path.strip():
        return f"{prefix} has an empty or non-string path {rel_path!r}"
    if rel_path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel_path):
        return f"{prefix} path `{rel_path}` is absolute; inputs must be repo-relative"
    if "\\" in rel_path or ".." in rel_path.split("/") or "\0" in rel_path:
        return (
            f"{prefix} path `{rel_path}` must be a repo-relative POSIX path "
            f"with no `..` component"
        )
    return None


def live_input_error(path: Path, rel_path: str) -> str | None:
    """A live record's (already well-formed) input must name a git-tracked
    regular file that resolves inside the repo."""
    src = REPO_ROOT / rel_path
    try:
        resolved = src.resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError):
        return f"{path}: input `{rel_path}` no longer exists in the working tree"
    if not resolved.is_relative_to(REPO_ROOT.resolve()):
        return f"{path}: input `{rel_path}` resolves outside the repo ({resolved})"
    if not stat.S_ISREG(resolved.stat().st_mode):
        return f"{path}: input `{rel_path}` is not a regular file"
    if not _is_tracked(rel_path):
        return f"{path}: input `{rel_path}` is not tracked by git"
    return None


def _extract_meta_block(text: str, path: Path) -> dict:
    match = re.search(r"<!--\s*record-meta\s*(.*?)-->", text, re.DOTALL)
    if not match:
        raise LintError(f"{path}: missing `<!-- record-meta ... -->` block")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise LintError(f"{path}: record-meta block is not valid JSON: {exc}") from exc


def _extract_prose_fields(text: str) -> dict:
    """Map required-field name -> value of its top-level bullet
    (`- **Field**: value`). A field is "present" if either the bullet line
    itself has content after the colon, or -- for fields whose detail lives
    in an indented sub-list (e.g. `Result`, `Links`) -- at least one
    indented, non-blank line follows before the next top-level bullet or a
    blank line breaks the block."""
    lines = text.splitlines()
    fields: dict[str, str] = {}
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        m = re.match(r"^-\s+\*\*(.+?)\*\*:\s*(.*)$", stripped)
        if not m:
            i += 1
            continue
        name = m.group(1).strip()
        value = m.group(2).strip()
        j = i + 1
        sub_content = []
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                break  # blank line ends this field's block
            if re.match(r"^-\s+\*\*.+?\*\*:", nxt.strip()) and not nxt.startswith((" ", "\t")):
                break  # next top-level bullet
            if nxt.startswith((" ", "\t")):
                sub_content.append(nxt.strip())
                j += 1
                continue
            break
        if not value and sub_content:
            value = " ".join(sub_content)
        fields[name] = value
        i = j if j > i + 1 else i + 1
    return fields


def lint_record(path: Path, all_record_ids_by_experiment: dict) -> list[str]:
    errors = []
    link = symlink_error(path)
    if link:
        return [link]  # never read through a symlink
    stem = path.stem

    layout = layout_error(path)
    if layout:
        errors.append(layout)
        return errors  # experiment identity is meaningless off-layout
    text = path.read_text(encoding="utf-8")

    experiment = experiment_key(path)  # .../<experiment>/records/<id>.md

    if not RECORD_ID_RE.match(stem):
        errors.append(f"{path}: filename `{path.name}` is not a valid record-id")

    try:
        meta = _extract_meta_block(text, path)
    except LintError as exc:
        errors.append(str(exc))
        return errors  # nothing further to check without metadata

    for key in REQUIRED_META_KEYS:
        if key not in meta:
            errors.append(f"{path}: record-meta missing required key `{key}`")

    if "experiment" in meta and meta["experiment"] != experiment:
        errors.append(
            f"{path}: record-meta experiment `{meta['experiment']}` "
            f"disagrees with its directory `{experiment}`"
        )

    if meta.get("record_id") != stem:
        errors.append(
            f"{path}: record-meta record_id `{meta.get('record_id')}` "
            f"disagrees with filename `{stem}`"
        )

    provenance = meta.get("provenance", {})
    if not isinstance(provenance, dict):
        errors.append(f"{path}: record-meta `provenance` must be an object")
        provenance = {}
    for key in REQUIRED_PROVENANCE_KEYS:
        if key not in provenance:
            errors.append(f"{path}: record-meta.provenance missing required key `{key}`")

    inputs = provenance.get("inputs")
    if not inputs or not isinstance(inputs, list):
        errors.append(f"{path}: record-meta.provenance.inputs is missing, empty or not a list")
        inputs = []
    for item in inputs:
        problem = input_error(path, item)
        if problem:
            errors.append(problem)

    prose = _extract_prose_fields(text)
    for field in REQUIRED_PROSE_FIELDS:
        value = prose.get(field)
        if value is None:
            errors.append(f"{path}: missing required field bullet `- **{field}**:`")
        elif value.strip().lower() in _PLACEHOLDER_VALUES:
            errors.append(f"{path}: required field `{field}` is empty/placeholder")

    supersedes = meta.get("supersedes")
    if supersedes is not None and not isinstance(supersedes, str):
        errors.append(
            f"{path}: record-meta `supersedes` must be a record-id string or null, "
            f"not {type(supersedes).__name__}"
        )
    elif supersedes not in (None, "none"):
        known_ids = all_record_ids_by_experiment.get(experiment, set())
        problem = supersession_error(path, supersedes, known_ids)
        if problem:
            errors.append(problem)

    return errors


def check_hash_freshness(path: Path, superseded: set) -> list[str]:
    """`superseded` holds `(experiment, record_id)` pairs, where
    `experiment` is the experiment's path relative to `RECORDS_ROOT`
    (`experiment_key`). Record IDs are not unique across experiments (a batch
    mint stamps one ID on many), and leaf directory names are not unique
    across nesting, so the exemption is keyed on the full relative path plus
    the ID: superseding one record never exempts any other (#157)."""
    errors = []
    if symlink_error(path):
        return errors  # already reported by lint_record; never read through it
    text = path.read_text(encoding="utf-8")
    try:
        meta = _extract_meta_block(text, path)
    except LintError:
        return errors  # already reported by lint_record

    if layout_error(path) is None and (experiment_key(path), path.stem) in superseded:
        return errors  # frozen history, exempt from freshness

    provenance = meta.get("provenance")
    inputs = provenance.get("inputs") if isinstance(provenance, dict) else None
    for item in inputs if isinstance(inputs, list) else []:
        if input_error(path, item):
            continue  # malformed input: already an error from lint_record
        rel_path = item["path"]
        recorded_hash = item["content_hash"]
        problem = live_input_error(path, rel_path)
        if problem:
            errors.append(problem)
            continue
        src = REPO_ROOT / rel_path
        current_hash = sha256_of(src)
        if current_hash != recorded_hash:
            errors.append(
                f"{path}: provenance hash for `{rel_path}` is stale -- "
                f"recorded {recorded_hash}, current {current_hash} "
                f"(source changed since this record; mint a new record)"
            )
    return errors


def check_append_only(base_ref: str, require: bool) -> list[str]:
    try:
        merge_base = run_git("merge-base", base_ref, "HEAD")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip()
        msg = f"append-only check: could not resolve base ref `{base_ref}` ({detail})"
        if require:
            return [msg]
        print(f"SKIP: {msg}")
        return []

    try:
        diff = run_git(
            "diff", "--name-status", merge_base, "HEAD", "--", "verification/records/"
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or str(exc)).strip()
        msg = f"append-only check: `git diff` failed ({detail})"
        if require:
            return [msg]
        print(f"SKIP: {msg}")
        return []

    errors = []
    for line in diff.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("A"):
            continue  # pure addition -- allowed
        paths = parts[1:]
        errors.append(
            f"append-only violation: `{status}` on {', '.join(paths)} "
            f"relative to {base_ref} -- records/artifacts must only be added"
        )
    if not errors:
        print(f"OK: no append-only violations relative to {base_ref} ({merge_base[:12]})")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="ref to diff against for the append-only check (default: origin/main)",
    )
    parser.add_argument(
        "--require-append-only",
        action="store_true",
        help="fail (instead of SKIP) if the append-only base ref cannot be resolved",
    )
    args = parser.parse_args()

    all_errors: list[str] = []

    # NOTE: an empty/absent records tree must NOT short-circuit -- deleting
    # every record is itself the most severe append-only violation there is,
    # and reporting only "the directory is gone" would let it through with a
    # misleading diagnosis. Record it as an error and keep going so the
    # append-only check below still runs and names the deleted paths.
    record_files = _tracked_record_files() if RECORDS_ROOT.exists() else []
    if not RECORDS_ROOT.exists():
        all_errors.append(f"{RECORDS_ROOT.relative_to(REPO_ROOT)} does not exist")
    elif not record_files:
        all_errors.append(
            "no tracked records under verification/records/**/records/*.md"
        )

    if RECORDS_ROOT.exists():
        all_errors.extend(tracked_symlink_errors())

    print(f"== linting {len(record_files)} record(s) ==")
    for error in all_errors:
        print(f"  - {error}")

    # A tracked gitlink / special entry is already reported above by mode;
    # never read it (it may be an empty directory or absent on disk).
    # Symlinks stay in: lint_record reports them without reading through.
    record_files = [p for p in record_files if p.is_file() or p.is_symlink()]

    all_ids_by_experiment: dict[str, set] = {}
    metas_by_path: dict[Path, dict] = {}
    for path in record_files:
        if layout_error(path):
            continue  # reported by lint_record; never a supersession target
        if symlink_error(path):
            continue  # reported by lint_record; never a supersession target
        experiment = experiment_key(path)
        stem = path.stem
        all_ids_by_experiment.setdefault(experiment, set()).add(stem)
        try:
            metas_by_path[path] = _extract_meta_block(
                path.read_text(encoding="utf-8"), path
            )
        except LintError:
            metas_by_path[path] = {}

    # Only a VALID supersession exempts its target: an on-layout record that
    # names an existing, strictly earlier record in its own experiment. A
    # self-supersession, a cycle, or a nested record exempts nothing (#157).
    superseded = set()
    for path, meta in metas_by_path.items():
        target = meta.get("supersedes")
        if not isinstance(target, str) or target == "none" or layout_error(path):
            continue
        experiment = experiment_key(path)
        known_ids = all_ids_by_experiment.get(experiment, set())
        if supersession_error(path, target, known_ids) is None:
            superseded.add((experiment, target))

    for path in record_files:
        errors = lint_record(path, all_ids_by_experiment)
        errors += check_hash_freshness(path, superseded)
        if errors:
            print(f"FAIL: {path.relative_to(REPO_ROOT)}")
            for e in errors:
                print(f"  - {e}")
        else:
            print(f"OK:   {path.relative_to(REPO_ROOT)}")
        all_errors.extend(errors)

    print()
    print("== append-only check ==")
    append_errors = check_append_only(args.base_ref, args.require_append_only)
    for e in append_errors:
        print(f"  - {e}")
    all_errors.extend(append_errors)

    print()
    if all_errors:
        print(f"FAIL: {len(all_errors)} record-lint error(s)")
        return 1
    print("PASS: all records valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
