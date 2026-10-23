#!/usr/bin/env python3
"""Validate the artifact-store manifests under manifests/artifacts/ (issue #344).

New sim and signoff evidence bytes live in the fleet's common artifact store;
git keeps only a manifest per run (written by `klt artifact put --manifest`)
and a Markdown summary. This check fails closed on:

  * a manifest that is not valid JSON, lacks `schema_version` 1, or has no
    entries;
  * an entry without `sha256` (64 lowercase hex), `size` (integer >= 0),
    `kind` (`evidence`), `name` or a `uri`;
  * a `uri` that does not start with `artifact:` (and end in the entry's
    sha256);
  * a manifest that names a storage bucket, cloud account or `s3://` URI;
  * a tracked file whose bytes are a stored object (same size and sha256), so
    the same evidence cannot be committed alongside its manifest;
  * any tracked file under the git-ignored staging directory.

Run: python3 scripts/check_artifact_manifests.py [--repo PATH]
Zero dependencies beyond the Python 3 standard library and `git`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_DIR = "manifests/artifacts"
SCRATCH_DIR = "verification/.artifact-scratch"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_RE = re.compile(r"s3://|arn:aws:")


def tracked_files(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True
    ).stdout
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]


def entry_errors(entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    errs = []
    sha = entry.get("sha256")
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        errs.append("`sha256` must be 64 lowercase hex digits")
    size = entry.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        errs.append("`size` must be an integer >= 0")
    if entry.get("kind") != "evidence":
        errs.append("`kind` must be `evidence`")
    if not isinstance(entry.get("name"), str) or not entry.get("name"):
        errs.append("`name` must be a non-empty string")
    uri = entry.get("uri")
    if not isinstance(uri, str) or not uri.startswith("artifact:"):
        errs.append("`uri` must be a string starting with `artifact:`")
    elif isinstance(sha, str) and not uri.endswith("/" + sha):
        errs.append("`uri` must end in the entry's sha256")
    return errs


def manifest_errors(text: str) -> tuple[list[str], list[dict]]:
    """Return (errors, well-formed entries) for one manifest's text."""
    if FORBIDDEN_RE.search(text):
        return ["names a storage bucket or cloud account (`s3://` / `arn:aws:`)"], []
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return [f"not valid JSON: {exc}"], []
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        return ["`schema_version` must be 1"], []
    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        return ["`entries` must be a non-empty list"], []
    errs, good = [], []
    for i, entry in enumerate(entries):
        bad = entry_errors(entry)
        errs.extend(f"entries[{i}]: {e}" for e in bad)
        if not bad:
            good.append(entry)
    return errs, good


def check(repo: Path) -> list[str]:
    errors: list[str] = []
    files = tracked_files(repo)
    stored: dict[int, dict[str, str]] = {}
    for rel in files:
        if rel.startswith(SCRATCH_DIR + "/"):
            errors.append(f"{rel}: tracked file under the git-ignored staging dir {SCRATCH_DIR}/")
        if not (rel.startswith(MANIFEST_DIR + "/") and rel.endswith(".manifest.json")):
            continue
        errs, entries = manifest_errors((repo / rel).read_text(encoding="utf-8"))
        errors.extend(f"{rel}: {e}" for e in errs)
        for entry in entries:
            if entry["size"] > 0:
                stored.setdefault(entry["size"], {})[entry["sha256"]] = f"{rel} ({entry['name']})"
    if stored:
        for rel in files:
            path = repo / rel
            if not path.is_file() or path.is_symlink():
                continue
            if path.stat().st_size not in stored:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            owner = stored[path.stat().st_size].get(digest)
            if owner:
                errors.append(f"{rel}: bytes are also committed; stored object of {owner}")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args(argv)
    errors = check(Path(args.repo))
    for e in errors:
        print(f"FAIL: {e}")
    if errors:
        return 1
    print("artifact manifests: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
