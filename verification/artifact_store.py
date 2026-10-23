#!/usr/bin/env python3
"""Fail-closed writer around `klt artifact put` for evidence bytes (issue #344).

Raw simulation and signoff outputs for a new run are staged in the git-ignored
`verification/.artifact-scratch/<record-id>/`, stored through the fleet's
artifact broker, and only a manifest (`manifests/artifacts/<experiment>-<record-id>
.manifest.json`) plus a Markdown summary (name, size, sha256 per object) is
committed. There is no fallback to committing bytes: if `$KLT_ARTIFACT_BROKER`
is unset, `klt` has no `artifact put`, or the broker is unreachable, this
raises `ArtifactStoreError` (the CLI exits nonzero) and leaves no manifest.
The broker URL is read from the environment by klt and is never written here.

CLI:
    python3 verification/artifact_store.py EXPERIMENT RECORD-ID FILE [FILE ...]
prints the Markdown summary on success. Library use: `preflight()` before a
long run, then `store(...)`.

Zero dependencies beyond the Python 3 standard library and klt.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from _repo_utils import REPO_ROOT

SCRATCH = REPO_ROOT / "verification" / ".artifact-scratch"
MANIFEST_DIR = REPO_ROOT / "manifests" / "artifacts"


class ArtifactStoreError(RuntimeError):
    """The store is unavailable or refused; nothing was committed or written."""


def preflight(klt: list[str] | None = None) -> None:
    """Raise `ArtifactStoreError` unless the broker env is set and klt can put."""
    klt = klt or ["klt"]
    if not os.environ.get("KLT_ARTIFACT_BROKER"):
        raise ArtifactStoreError("$KLT_ARTIFACT_BROKER is unset; refusing to store or commit evidence")
    try:
        proc = subprocess.run([*klt, "artifact", "put", "--help"], capture_output=True, text=True)
    except OSError as exc:
        raise ArtifactStoreError(f"cannot run klt: {exc}") from exc
    if proc.returncode != 0:
        raise ArtifactStoreError("this klt has no `artifact put`; upgrade klt (klayout-tools 7e3561f or later)")


def scratch_dir(record_id: str) -> Path:
    """A fresh (empty) git-ignored staging directory for one run's raw outputs."""
    path = SCRATCH / record_id
    if path.exists() and any(path.iterdir()):
        raise ArtifactStoreError(f"{path} is not empty; refusing to reuse a staging dir")
    path.mkdir(parents=True, exist_ok=True)
    return path


def manifest_path(experiment: str, record_id: str) -> Path:
    return MANIFEST_DIR / f"{experiment}-{record_id}.manifest.json"


def store(experiment: str, record_id: str, files: list[Path],
          klt: list[str] | None = None) -> tuple[Path, list[dict]]:
    """Store `files`; return (manifest path, manifest entries). On any failure
    raise `ArtifactStoreError` and leave no manifest behind."""
    klt = klt or ["klt"]
    preflight(klt)
    if not files:
        raise ArtifactStoreError("no files to store")
    manifest = manifest_path(experiment, record_id)
    if manifest.exists():
        raise ArtifactStoreError(f"{manifest} already exists; refusing to overwrite")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [*klt, "artifact", "put", "--manifest", str(manifest), "--format", "json",
           *[str(f) for f in files]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
        ok = proc.returncode == 0 and manifest.is_file()
    except OSError as exc:
        proc, ok = None, False
        detail = str(exc)
    if not ok:
        manifest.unlink(missing_ok=True)
        if proc is not None:
            detail = (proc.stderr.strip() or proc.stdout.strip())[-400:]
        raise ArtifactStoreError(f"`klt artifact put` failed ({detail}); nothing stored or committed")
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))["entries"]
    except (ValueError, KeyError) as exc:
        manifest.unlink(missing_ok=True)
        raise ArtifactStoreError(f"unreadable manifest from klt: {exc}") from exc
    return manifest, entries


def summary_markdown(manifest: Path, entries: list[dict]) -> str:
    """A Markdown table (name, size, sha256 per object) for the record body."""
    rel = manifest.relative_to(REPO_ROOT) if manifest.is_relative_to(REPO_ROOT) else manifest
    lines = [f"Stored objects (manifest `{rel}`; bytes are not in git, fetch with "
             f"`klt artifact get`):", "", "| name | size | sha256 |", "|---|---|---|"]
    lines += [f"| `{e['name']}` | {e['size']} | `{e['sha256']}` |" for e in entries]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment")
    ap.add_argument("record_id")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--klt", default="klt", help="klt command (default: klt)")
    args = ap.parse_args(argv)
    try:
        manifest, entries = store(args.experiment, args.record_id, args.files, shlex.split(args.klt))
    except ArtifactStoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(summary_markdown(manifest, entries), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
