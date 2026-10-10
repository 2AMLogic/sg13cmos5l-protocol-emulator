#!/usr/bin/env python3
"""Freshness checker for the T1 item 1/2/9/10 attestations (issue #83).

`klt signoff` grades items 1, 2, 9 and 10 from artifact-anchored `generic`
envelopes under `manifests/evidence/` (klayout-tools#2718): each envelope
names one audited file and its sha256, the manifest pins the same hash, and
the grader re-hashes that one file. It does NOT read the file. So for an
inventory (a text file listing other files), the grader only notices an edit
to the inventory itself -- an RTL change that leaves `design-sources.txt`
untouched would still grade item 1 `met` while the inventory describes bytes
that no longer exist. That is the gap this script closes: it reads every
inventory and checks that what it says is still true of the tree.

Inventory directives (one per line, at column 0; every other line is prose):

    sha256:<64 hex>  <path>       the file's bytes are exactly these
    link  <path> -> <target>      <path> is a symlink to <target>
    file  <path>                  the file exists (content not pinned)
    heading  <path> :: <line>     the file has a line equal to <line>
                                  (leading/trailing blanks ignored)
    experiment  <name>            (testbenches.txt) a bench line for the
                                  evidence directory verification/records/<name>

Checks:

1. Every directive in every `manifests/evidence/*.txt` holds.
2. The `experiment` lines of `testbenches.txt` name exactly the experiment
   directories under `verification/records/` -- a new kind of recorded
   measurement cannot land without a bench line, and a line cannot outlive
   its directory.
3. Every `manifests/evidence/*.json` is a passing `generic` envelope with an
   integer `t1_item` in {1, 2, 9, 10}, whose `provenance.input` names a file
   that re-hashes to its `content_hash`, and the manifest cites that envelope
   for that item with the same pin.
4. The manifest cites items 1, 2, 9 and 10 only through such envelopes (no
   native envelope, which would carry no information about the item).

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 scripts/check_evidence_inventories.py [--repo-root DIR]

Exit codes: 0 pass, 1 a check failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = "manifests/evidence"
MANIFEST = "manifests/sg13cmos5l-protocol-emulator.json"
RECORDS_DIR = "verification/records"
BOUND_ITEMS = {1, 2, 9, 10}

SHA_LINE = re.compile(r"^sha256:([0-9a-f]{64})\s+(\S+)\s*$")
LINK_LINE = re.compile(r"^link\s+(\S+)\s+->\s+(\S+)\s*$")
FILE_LINE = re.compile(r"^file\s+(\S+)\s*$")
HEADING_LINE = re.compile(r"^heading\s+(\S+)\s+::\s+(.+?)\s*$")
EXPERIMENT_LINE = re.compile(r"^experiment\s+(\S+)")
DIRECTIVE_START = re.compile(r"^(sha256:|link\s|file\s|heading\s|experiment\s)")


def sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root: Path, rel: str) -> Path | None:
    """`root/rel` if it is a repo-relative path that stays inside root."""
    if rel.startswith("/") or ".." in rel.split("/"):
        return None
    return root / rel


def check_inventory(root: Path, inv: Path) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    experiments: set[str] = set()
    name = inv.relative_to(root).as_posix()
    for n, line in enumerate(inv.read_text(encoding="utf-8").splitlines(), 1):
        where = f"{name}:{n}"
        if not DIRECTIVE_START.match(line):
            continue
        if m := SHA_LINE.match(line):
            want, rel = m.groups()
            p = inside(root, rel)
            if p is None or not p.is_file():
                errors.append(f"{where}: `{rel}` is not a file in the tree")
            elif (got := sha256_hex(p)) != want:
                errors.append(
                    f"{where}: `{rel}` changed since the inventory was written "
                    f"(listed sha256:{want[:12]}..., now sha256:{got[:12]}...)"
                )
        elif m := LINK_LINE.match(line):
            rel, target = m.groups()
            p = inside(root, rel)
            if p is None or not p.is_symlink():
                errors.append(f"{where}: `{rel}` is not a symlink")
            elif (got := p.readlink().as_posix()) != target:
                errors.append(f"{where}: `{rel}` points at `{got}`, inventory says `{target}`")
        elif m := FILE_LINE.match(line):
            rel = m.group(1)
            p = inside(root, rel)
            if p is None or not p.is_file():
                errors.append(f"{where}: `{rel}` is not a file in the tree")
        elif m := HEADING_LINE.match(line):
            rel, heading = m.groups()
            p = inside(root, rel)
            if p is None or not p.is_file():
                errors.append(f"{where}: `{rel}` is not a file in the tree")
            elif heading.strip() not in (
                ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
            ):
                errors.append(f"{where}: `{rel}` no longer has the line `{heading}`")
        elif m := EXPERIMENT_LINE.match(line):
            experiments.add(m.group(1))
        else:
            errors.append(f"{where}: malformed directive: {line!r}")
    return errors, experiments


def recorded_experiments(root: Path) -> set[str]:
    base = root / RECORDS_DIR
    if not base.is_dir():
        return set()
    return {d.name for d in base.iterdir() if (d / "records").is_dir()}


def envelope_input(root: Path, env_path: Path, inp) -> Path | None:
    path = inp.get("path") if isinstance(inp, dict) else None
    if isinstance(path, str):
        return inside(env_path.parent, path) if not path.startswith("/") else None
    if isinstance(path, dict) and path.get("scope") == "repo" and isinstance(path.get("path"), str):
        return inside(root, path["path"])
    return None


def check_envelopes(root: Path, manifest: dict) -> tuple[list[str], set[int]]:
    errors: list[str] = []
    bound: set[int] = set()
    evidence = manifest.get("evidence", {}) if isinstance(manifest, dict) else {}
    for env_path in sorted((root / EVIDENCE_DIR).glob("*.json")):
        rel = env_path.relative_to(root).as_posix()
        try:
            env = json.loads(env_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{rel}: not readable JSON ({exc})")
            continue
        item = env.get("t1_item")
        if env.get("kind") != "generic" or env.get("status") != "pass":
            errors.append(f"{rel}: expected kind `generic`, status `pass`")
        if not isinstance(item, int) or isinstance(item, bool) or item not in BOUND_ITEMS:
            errors.append(f"{rel}: t1_item must be one of {sorted(BOUND_ITEMS)}, got {item!r}")
            continue
        inp = (env.get("provenance") or {}).get("input") or {}
        target = envelope_input(root, env_path, inp)
        want = inp.get("content_hash")
        if target is None or not target.is_file():
            errors.append(f"{rel}: provenance.input.path does not name a file in the tree")
        elif want != f"sha256:{sha256_hex(target)}":
            errors.append(
                f"{rel}: `{target.relative_to(root).as_posix()}` no longer hashes to the "
                f"envelope's content_hash -- refresh the envelope, the manifest pin and the "
                f"signoff record together"
            )
        cite = evidence.get(str(item))
        if not isinstance(cite, dict) or cite.get("file") != rel:
            errors.append(f"{rel}: the manifest does not cite this envelope for item {item}")
        elif cite.get("content_hash") != want:
            errors.append(
                f"{rel}: the manifest pins {cite.get('content_hash')} for item {item}, "
                f"the envelope records {want}"
            )
        else:
            bound.add(item)
    for item in sorted(BOUND_ITEMS):
        cite = evidence.get(str(item))
        if cite is not None and item not in bound:
            errors.append(
                f"{MANIFEST}: item {item} is cited, but not through a valid envelope under "
                f"{EVIDENCE_DIR}/ (a native envelope says nothing about this item)"
            )
    return errors, bound


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo-root", type=Path, default=DEFAULT_ROOT)
    args = ap.parse_args(argv)
    root = args.repo_root.resolve()

    errors: list[str] = []
    inventories = sorted((root / EVIDENCE_DIR).glob("*.txt"))
    tb_experiments: set[str] | None = None
    for inv in inventories:
        errs, exps = check_inventory(root, inv)
        errors += errs
        if inv.name == "testbenches.txt":
            tb_experiments = exps
    if tb_experiments is not None:
        on_disk = recorded_experiments(root)
        for missing in sorted(on_disk - tb_experiments):
            errors.append(
                f"{EVIDENCE_DIR}/testbenches.txt: no `experiment {missing}` line for "
                f"{RECORDS_DIR}/{missing}/ -- name its bench and cold-start command"
            )
        for extra in sorted(tb_experiments - on_disk):
            errors.append(
                f"{EVIDENCE_DIR}/testbenches.txt: `experiment {extra}` names no directory "
                f"under {RECORDS_DIR}/"
            )

    try:
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{MANIFEST}: not readable JSON ({exc})")
        manifest = {}
    env_errors, bound = check_envelopes(root, manifest)
    errors += env_errors

    if errors:
        print("FAIL: evidence inventories do not describe the tree:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(
        f"PASS: {len(inventories)} inventories hold; items "
        f"{', '.join(str(i) for i in sorted(bound)) or 'none'} bound through "
        f"{EVIDENCE_DIR}/"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
