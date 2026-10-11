#!/usr/bin/env python3
"""Fail when a file that defines the frozen submission ISA changes without a record.

DR 0017 (`spec/decision-records/0017-submission-isa-freeze.md`) freezes the
ISA a programmer sees, so that target-spec row 13's protocol, chosen after
the freeze, cannot have shaped it. The machine-readable half of that record
is `spec/isa-freeze.json`: one sha256 pin per file that defines the ISA, and
an append-only amendment list.

What it checks
    1. The manifest is well formed: schema, a full 40-hex freeze commit, the
       record path, and a non-empty pin list with unique, repo-relative
       paths and 64-hex hashes.
    2. The pinned set cannot shrink or move quietly.
       * DR 0017's whole pin table (every `| `path` | `sha256` |` row) and
         the manifest's `pins` are the same path-to-hash mapping, compared
         in both directions: a row on either side alone fails, and so does a
         duplicate row.
       * `pins`, `schema`, `record`, `freeze_base_commit` and
         `first_amending_dr` equal the manifest as first committed (the
         earliest commit that added it), and as on the merge-base with
         `--base-ref` (default `origin/main`). So deleting a pin from both
         the manifest and the record, or re-hashing it in both, fails even
         once committed. A shallow clone, or an unresolvable base ref,
         prints a NOTE and skips only that comparison.
       * Amendments already on the base ref are append-only.
       * The set changes only by an amendment with `op` `unpin` (the file is
         no longer checked) or `pin` (a new file is), and either needs a
         decision record numbered 0018 or later, whatever its kind.
    3. Each file still pinned is a tracked regular file (not a symlink)
       whose sha256 equals its expected hash: the pin, or the `sha256_after`
       of the last amendment that names it.
    4. Amendments for one path form a chain: each `sha256_before` is the
       previous expected hash. Each gives its `kind` and whether it
       invalidates row 13 evidence (a boolean, never omitted). What it must
       cite depends on the kind:
       * `isa-change` and `conformance-fix` cite a decision record (`dr`)
         numbered at least `first_amending_dr` (18) that exists under
         `spec/decision-records/`, is not itself pinned, and names the
         amended path. An issue or PR reference alone is refused.
       * `no-behaviour-change` (a dated note, a Status line, a typo, a
         cross-reference) cites either such a record or an issue/PR
         reference (`ref`, `#N` or `owner/repo#N`), says what changed in
         `summary`, and must have `invalidates_row13_evidence: false`. The
         reference is checked for form only; the lint never calls GitHub.
    5. If the freeze commit is present in the local clone, every pin equals
       the hash of that path at that commit. A shallow clone without the
       commit prints a NOTE and skips only this step.

Fixing a failure
    A pinned file changed. If the change is intended, append an entry to
    `amendments` in `spec/isa-freeze.json`. Do not edit a pin. A change to
    ISA-visible behaviour, or a fix that brings the RTL in line with the
    frozen records, needs a decision record numbered 0018 or above that says
    so and whether it invalidates row 13 evidence. A change nothing can
    observe (a dated note, a Status line, a typo) may cite its issue or PR
    instead (DR 0017, "Change control").

Usage
    python3 scripts/check_isa_freeze.py [--base-ref origin/main]

Zero dependencies beyond the Python 3 standard library and `git`.
Exit codes: 0 pass, 1 a check failed, 2 the manifest could not be read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_REL = "spec/isa-freeze.json"
DR_DIR_REL = "spec/decision-records"

SCHEMA = "isa-freeze/v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DR_FILE_RE = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
AMENDMENT_KINDS = ("isa-change", "conformance-fix", "no-behaviour-change")
AMENDMENT_OPS = ("modify", "pin", "unpin")
# A row of DR 0017's pin table: | `path` | `64-hex` | why |
RECORD_PIN_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|")
DR_REQUIRED_KINDS = ("isa-change", "conformance-fix")
# `#218` or `2AMLogic/sg13cmos5l-protocol-emulator#218`. Form only: no API call.
REF_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+)?#[1-9][0-9]*$")


class ManifestError(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True)


def tracked_mode(repo: Path, rel: str) -> str | None:
    """Git index mode of `rel` (`100644`, `120000`, ...), or None if untracked."""
    proc = git(repo, "ls-files", "-s", "--", rel)
    out = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not out:
        return None
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        if path == rel:
            return meta.split()[0]
    return None


def valid_rel_path(rel: object) -> bool:
    if not isinstance(rel, str) or not rel:
        return False
    p = PurePosixPath(rel)
    return not p.is_absolute() and ".." not in p.parts and "\\" not in rel


def load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"{MANIFEST_REL} not found") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{MANIFEST_REL} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{MANIFEST_REL} must be a JSON object")
    return data


def find_dr(repo: Path, number: int) -> list[str]:
    """Repo-relative paths of decision records numbered `number`."""
    d = repo / DR_DIR_REL
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.iterdir()):
        m = DR_FILE_RE.match(f.name)
        if m and int(m.group(1)) == number and f.is_file():
            out.append(f"{DR_DIR_REL}/{f.name}")
    return out


def check(repo: Path, base_ref: str | None = "origin/main") -> tuple[list[str], list[str], int]:
    """Return (errors, notes, number of files still pinned)."""
    errors: list[str] = []
    notes: list[str] = []
    m = load_manifest(repo / MANIFEST_REL)

    # 1. Shape.
    if m.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}, got {m.get('schema')!r}")
    base = m.get("freeze_base_commit")
    if not isinstance(base, str) or not COMMIT_RE.match(base):
        errors.append("freeze_base_commit must be a full 40-hex commit SHA")
        base = None
    record_rel = m.get("record")
    if not valid_rel_path(record_rel) or not (repo / record_rel).is_file():
        errors.append(f"record {record_rel!r} must name an existing file")
        record_rel = None
    first_dr = m.get("first_amending_dr")
    if not isinstance(first_dr, int) or isinstance(first_dr, bool) or first_dr < 18:
        errors.append("first_amending_dr must be an integer >= 18")
        first_dr = 18

    pins = m.get("pins")
    if not isinstance(pins, list) or not pins:
        errors.append("pins must be a non-empty list")
        pins = []
    frozen: dict[str, str] = {}  # the pin set as frozen; never changes
    for i, pin in enumerate(pins):
        if not isinstance(pin, dict):
            errors.append(f"pins[{i}] must be an object")
            continue
        rel, sha = pin.get("path"), pin.get("sha256")
        if not valid_rel_path(rel):
            errors.append(f"pins[{i}].path {rel!r} must be a repo-relative POSIX path")
            continue
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            errors.append(f"pins[{i}] ({rel}): sha256 must be 64 lowercase hex")
            continue
        if not isinstance(pin.get("why"), str) or not pin["why"].strip():
            errors.append(f"pins[{i}] ({rel}): 'why' must say what the file defines")
        if rel in frozen:
            errors.append(f"pins: {rel} is pinned twice")
            continue
        frozen[rel] = sha

    # 2. The record's whole pin table equals the manifest's pins, both ways.
    if record_rel:
        text = (repo / record_rel).read_text(encoding="utf-8")
        if MANIFEST_REL not in text:
            errors.append(f"{record_rel} does not reference {MANIFEST_REL}")
        table: dict[str, str] = {}
        for ln in text.splitlines():
            row = RECORD_PIN_ROW_RE.match(ln)
            if not row:
                continue
            rel, sha = row.group(1), row.group(2)
            if rel in table:
                errors.append(f"{record_rel}: `{rel}` appears twice in the pin table")
            table[rel] = sha
        if not table:
            errors.append(f"{record_rel}: no pin table rows (| `path` | `sha256` | ...) found")
        for rel in sorted(set(table) - set(frozen)):
            errors.append(
                f"{rel}: pinned in {record_rel} but not in {MANIFEST_REL} pins; "
                "a pin is never removed, only unpinned by an amendment (DR 0017, 'Change control')"
            )
        for rel in sorted(set(frozen) - set(table)):
            errors.append(f"{rel}: pinned in {MANIFEST_REL} but missing from {record_rel}'s pin table")
        for rel in sorted(set(frozen) & set(table)):
            if frozen[rel] != table[rel]:
                errors.append(f"{rel}: {record_rel} and {MANIFEST_REL} pin different hashes")

    # 2b. The frozen fields equal the manifest as first committed, and as on
    #     the base ref; there, amendments are append-only.
    errors.extend(compare_with_history(repo, m, base_ref, notes))

    # 4. Amendments, applied in order, give the expected hash of every file
    #    still pinned. `op` pin/unpin are the only way the set changes.
    amendments = m.get("amendments")
    if not isinstance(amendments, list):
        errors.append("amendments must be a list (empty until the first amendment)")
        amendments = []
    expected: dict[str, str] = dict(frozen)
    for i, a in enumerate(amendments):
        where = f"amendments[{i}]"
        if not isinstance(a, dict):
            errors.append(f"{where} must be an object")
            continue
        rel = a.get("path")
        op = a.get("op", "modify")
        if op not in AMENDMENT_OPS:
            errors.append(f"{where}: op must be one of {', '.join(AMENDMENT_OPS)}")
            continue
        if not valid_rel_path(rel):
            errors.append(f"{where}: path {rel!r} must be a repo-relative POSIX path")
            continue
        if op == "pin":
            if rel in expected:
                errors.append(f"{where}: op pin names {rel}, which is already pinned")
                continue
        elif rel not in expected:
            errors.append(f"{where}: path {rel!r} is not a pinned file")
            continue
        where = f"{where} ({rel})"
        kind = a.get("kind")
        if kind not in AMENDMENT_KINDS:
            errors.append(f"{where}: kind must be one of {', '.join(AMENDMENT_KINDS)}")
        inval = a.get("invalidates_row13_evidence")
        if not isinstance(inval, bool):
            errors.append(f"{where}: invalidates_row13_evidence must be true or false")
        elif kind == "no-behaviour-change" and inval:
            errors.append(
                f"{where}: a no-behaviour-change amendment cannot invalidate row 13 evidence; "
                "if it does, it changes behaviour and needs kind isa-change or conformance-fix"
            )
        has_dr, has_ref = "dr" in a, "ref" in a
        if has_ref:
            ref = a.get("ref")
            if not isinstance(ref, str) or not REF_RE.match(ref):
                errors.append(f"{where}: ref {ref!r} must be an issue or PR reference, '#N' or 'owner/repo#N'")
        if op != "modify" and not has_dr:
            errors.append(
                f"{where}: op {op} changes the pinned set and needs a decision record numbered "
                f"{first_dr:04d} or later (dr), whatever its kind"
            )
        elif kind in DR_REQUIRED_KINDS and not has_dr:
            errors.append(
                f"{where}: kind {kind} needs a decision record numbered {first_dr:04d} or later (dr); "
                "an issue or PR reference is accepted only for no-behaviour-change"
            )
        elif kind == "no-behaviour-change" and not (has_dr or has_ref):
            errors.append(f"{where}: cite a decision record (dr) or an issue/PR reference (ref)")
        if kind == "no-behaviour-change" and not has_dr:
            summary = a.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                errors.append(f"{where}: an amendment citing only a ref must say what changed in 'summary'")
        if has_dr:
            dr = a.get("dr")
            if not isinstance(dr, int) or isinstance(dr, bool):
                errors.append(f"{where}: dr must be the amending record's number, an integer")
            elif dr < first_dr:
                errors.append(f"{where}: dr {dr:04d} is below {first_dr:04d}; only a later record may amend the freeze")
            else:
                found = find_dr(repo, dr)
                if not found:
                    errors.append(f"{where}: no decision record {dr:04d}-*.md under {DR_DIR_REL}/")
                elif len(found) > 1:
                    errors.append(f"{where}: decision record number {dr:04d} is used by {len(found)} files")
                elif found[0] in expected or found[0] in frozen:
                    errors.append(f"{where}: the amending record {found[0]} is itself pinned")
                elif rel not in (repo / found[0]).read_text(encoding="utf-8"):
                    errors.append(f"{where}: {found[0]} does not name the amended path")
        before, after = a.get("sha256_before"), a.get("sha256_after")
        before_ok = isinstance(before, str) and bool(SHA_RE.match(before))
        after_ok = isinstance(after, str) and bool(SHA_RE.match(after))
        if op == "pin":
            if before is not None or not after_ok:
                errors.append(f"{where}: op pin takes sha256_after (64 hex) and no sha256_before")
                continue
            expected[rel] = after
            continue
        if not before_ok:
            errors.append(f"{where}: sha256_before must be 64 lowercase hex")
            continue
        if before != expected[rel]:
            errors.append(
                f"{where}: sha256_before {before[:12]}... does not continue the chain "
                f"(expected {expected[rel][:12]}...)"
            )
        if op == "unpin":
            if after is not None:
                errors.append(f"{where}: op unpin takes no sha256_after")
            del expected[rel]
            continue
        if not after_ok:
            errors.append(f"{where}: sha256_after must be 64 lowercase hex")
            continue
        expected[rel] = after

    # 3. The working tree matches every file still pinned.
    for rel, want in expected.items():
        mode = tracked_mode(repo, rel)
        path = repo / rel
        if mode is None:
            errors.append(f"{rel}: pinned but not tracked by git")
            continue
        if mode == "120000" or path.is_symlink():
            errors.append(f"{rel}: pinned path is a symlink; pin the file it points to")
            continue
        if not path.is_file():
            errors.append(f"{rel}: pinned file is missing from the working tree")
            continue
        actual = sha256_bytes(path.read_bytes())
        if actual != want:
            errors.append(
                f"{rel}: sha256 {actual[:12]}... differs from the frozen {want[:12]}... "
                "and no amendment by a decision record numbered "
                f"{first_dr:04d} or later (or, for a change nothing can observe, an issue/PR "
                "reference) accounts for it (see DR 0017, 'Change control')"
            )

    # 5. The pins describe the freeze commit, when it is available.
    if base:
        if git(repo, "cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
            notes.append(f"freeze commit {base[:12]} is not in this clone; pins not re-derived from it")
        else:
            for rel, sha in frozen.items():
                proc = git(repo, "show", f"{base}:{rel}")
                if proc.returncode != 0:
                    errors.append(f"{rel}: not present at freeze commit {base[:12]}")
                elif sha256_bytes(proc.stdout) != sha:
                    errors.append(f"{rel}: pin does not match the file at freeze commit {base[:12]}")

    return errors, notes, len(expected)


FROZEN_FIELDS = ("schema", "record", "freeze_base_commit", "first_amending_dr")


def frozen_view(m: dict) -> dict:
    """The parts of a manifest that may never change after the freeze."""
    pins = m.get("pins") if isinstance(m.get("pins"), list) else []
    return {
        **{k: m.get(k) for k in FROZEN_FIELDS},
        "pins": sorted(
            (p.get("path"), p.get("sha256")) for p in pins if isinstance(p, dict)
        ),
    }


def manifest_at(repo: Path, rev: str) -> dict | None:
    proc = git(repo, "show", f"{rev}:{MANIFEST_REL}")
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def compare_with_history(repo: Path, m: dict, base_ref: str | None, notes: list[str]) -> list[str]:
    """The pinned set and the freeze fields can only be what they were first
    committed as; amendments already on the base ref are append-only."""
    errors: list[str] = []
    now = frozen_view(m)

    # Against the manifest as first committed.
    shallow = git(repo, "rev-parse", "--is-shallow-repository").stdout.decode().strip() == "true"
    adds = git(repo, "log", "--diff-filter=A", "--format=%H", "--reverse", "--", MANIFEST_REL)
    first = adds.stdout.decode().split()[:1] if adds.returncode == 0 else []
    if shallow:
        notes.append("shallow clone: the manifest is not compared with its first committed version")
    elif not first:
        notes.append(f"{MANIFEST_REL} is not committed yet; nothing to compare it with")
    else:
        orig = manifest_at(repo, first[0])
        if orig is None:
            errors.append(f"{MANIFEST_REL} as first committed ({first[0][:12]}) cannot be read")
        else:
            errors.extend(diff_frozen(frozen_view(orig), now, f"as first committed ({first[0][:12]})"))

    # Against the base ref (merge-base), where amendments are append-only.
    if base_ref:
        mb = git(repo, "merge-base", "HEAD", base_ref)
        if mb.returncode != 0:
            notes.append(f"base ref {base_ref} not resolvable; amendments not checked as append-only")
        else:
            rev = mb.stdout.decode().strip()
            old = manifest_at(repo, rev)
            if old is not None:
                errors.extend(diff_frozen(frozen_view(old), now, f"on {base_ref} ({rev[:12]})"))
                old_am = old.get("amendments") if isinstance(old.get("amendments"), list) else []
                new_am = m.get("amendments") if isinstance(m.get("amendments"), list) else []
                if new_am[: len(old_am)] != old_am:
                    errors.append(
                        f"amendments: entries already on {base_ref} ({rev[:12]}) were edited or "
                        "removed; amendments are append-only"
                    )
    return errors


def diff_frozen(old: dict, new: dict, where: str) -> list[str]:
    errors = []
    for k in FROZEN_FIELDS:
        if old[k] != new[k]:
            errors.append(f"{k}: changed from {old[k]!r} {where}; the freeze's own fields never change")
    if old["pins"] != new["pins"]:
        o, n = dict(old["pins"]), dict(new["pins"])
        gone = sorted(set(o) - set(n))
        added = sorted(set(n) - set(o))
        changed = sorted(p for p in set(o) & set(n) if o[p] != n[p])
        detail = "; ".join(
            part for part in (
                f"removed {', '.join(map(str, gone))}" if gone else "",
                f"added {', '.join(map(str, added))}" if added else "",
                f"re-hashed {', '.join(map(str, changed))}" if changed else "",
            ) if part
        )
        errors.append(
            f"pins differ from the manifest {where} ({detail}); pins are never edited: "
            "change the set with an amendment of op pin or unpin citing a decision record"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    parser.add_argument(
        "--base-ref", default="origin/main",
        help="ref whose merge-base holds amendments that must stay unchanged (default: origin/main)",
    )
    args = parser.parse_args(argv)
    try:
        errors, notes, n_pinned = check(args.repo, args.base_ref)
    except ManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for n in notes:
        print(f"NOTE: {n}")
    if errors:
        print(f"FAIL: submission ISA freeze ({MANIFEST_REL}, DR 0017):", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    m = load_manifest(args.repo / MANIFEST_REL)
    print(
        f"OK: {n_pinned} ISA-defining file(s) match the freeze at "
        f"{m['freeze_base_commit'][:12]} with {len(m['amendments'])} amendment(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
