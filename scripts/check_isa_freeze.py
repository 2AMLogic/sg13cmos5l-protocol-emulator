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
    2. DR 0017 and the manifest agree: every pin's path and hash appear
       together on one line of the record's pin table. Editing one without
       the other fails.
    3. Each pinned path is a tracked regular file (not a symlink) whose
       sha256 equals its expected hash. The expected hash is the pin, or, if
       amendments name the path, the `sha256_after` of the last of them.
    4. Every amendment cites a decision record numbered at least
       `first_amending_dr` (18) that exists under `spec/decision-records/`,
       is not itself pinned, and names the amended path. Amendments for one
       path form a chain: each `sha256_before` is the previous expected hash.
       Each says what kind of change it is and whether it invalidates row 13
       evidence (a boolean, never omitted).
    5. If the freeze commit is present in the local clone, every pin equals
       the hash of that path at that commit. A shallow clone without the
       commit prints a NOTE and skips only this step.

Fixing a failure
    A pinned file changed. If the change is intended, write a decision
    record numbered 0018 or above that says what changed, whether it alters
    ISA-visible behaviour (or is a fix that brings the RTL in line with the
    frozen records), and whether it invalidates row 13 evidence; then append
    an entry to `amendments` in `spec/isa-freeze.json`. Do not edit a pin.

Usage
    python3 scripts/check_isa_freeze.py

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


def check(repo: Path) -> tuple[list[str], list[str]]:
    """Return (errors, notes)."""
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
    expected: dict[str, str] = {}
    pin_order: list[str] = []
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
        if rel in expected:
            errors.append(f"pins: {rel} is pinned twice")
            continue
        expected[rel] = sha
        pin_order.append(rel)

    # 2. The record's pin table agrees with the manifest.
    if record_rel:
        lines = (repo / record_rel).read_text(encoding="utf-8").splitlines()
        if MANIFEST_REL not in "\n".join(lines):
            errors.append(f"{record_rel} does not reference {MANIFEST_REL}")
        for rel, sha in expected.items():
            if not any(f"`{rel}`" in ln and sha in ln for ln in lines):
                errors.append(
                    f"{record_rel} has no pin-table line with `{rel}` and its hash {sha[:12]}...; "
                    "the record and the manifest disagree"
                )

    # 4. Amendments, applied in order.
    amendments = m.get("amendments")
    if not isinstance(amendments, list):
        errors.append("amendments must be a list (empty until the first amendment)")
        amendments = []
    pinned_set = set(expected)
    for i, a in enumerate(amendments):
        where = f"amendments[{i}]"
        if not isinstance(a, dict):
            errors.append(f"{where} must be an object")
            continue
        rel = a.get("path")
        if rel not in expected:
            errors.append(f"{where}: path {rel!r} is not a pinned file")
            continue
        where = f"{where} ({rel})"
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
            elif found[0] in pinned_set:
                errors.append(f"{where}: the amending record {found[0]} is itself pinned")
            elif rel not in (repo / found[0]).read_text(encoding="utf-8"):
                errors.append(f"{where}: {found[0]} does not name the amended path")
        if a.get("kind") not in AMENDMENT_KINDS:
            errors.append(f"{where}: kind must be one of {', '.join(AMENDMENT_KINDS)}")
        if not isinstance(a.get("invalidates_row13_evidence"), bool):
            errors.append(f"{where}: invalidates_row13_evidence must be true or false")
        before, after = a.get("sha256_before"), a.get("sha256_after")
        if not (isinstance(before, str) and SHA_RE.match(before)
                and isinstance(after, str) and SHA_RE.match(after)):
            errors.append(f"{where}: sha256_before and sha256_after must be 64 lowercase hex")
            continue
        if before != expected[rel]:
            errors.append(
                f"{where}: sha256_before {before[:12]}... does not continue the chain "
                f"(expected {expected[rel][:12]}...)"
            )
        expected[rel] = after

    # 3. The working tree matches.
    for rel in pin_order:
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
        if actual != expected[rel]:
            errors.append(
                f"{rel}: sha256 {actual[:12]}... differs from the frozen {expected[rel][:12]}... "
                "and no amendment by a decision record numbered "
                f"{first_dr:04d} or later accounts for it (see DR 0017, 'Change control')"
            )

    # 5. The pins describe the freeze commit, when it is available.
    if base:
        if git(repo, "cat-file", "-e", f"{base}^{{commit}}").returncode != 0:
            notes.append(f"freeze commit {base[:12]} is not in this clone; pins not re-derived from it")
        else:
            for pin in pins:
                if not isinstance(pin, dict) or pin.get("path") not in pinned_set:
                    continue
                rel = pin["path"]
                proc = git(repo, "show", f"{base}:{rel}")
                if proc.returncode != 0:
                    errors.append(f"{rel}: not present at freeze commit {base[:12]}")
                elif sha256_bytes(proc.stdout) != pin.get("sha256"):
                    errors.append(f"{rel}: pin does not match the file at freeze commit {base[:12]}")

    return errors, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        errors, notes = check(args.repo)
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
        f"OK: {len(m['pins'])} ISA-defining file(s) match the freeze at "
        f"{m['freeze_base_commit'][:12]} with {len(m['amendments'])} amendment(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
