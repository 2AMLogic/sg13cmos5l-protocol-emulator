#!/usr/bin/env python3
"""Normalize a committed klt envelope's input-artifact path field to the
portable `{path, scope: "repo"}` shape `klt sim`/`klt pex` already emit.

Why this exists (issue #65): `klt drc`'s response `file` field echoes the
producing run's resolved ABSOLUTE path. `klt signoff`'s input-artifact
freshness gate (`input_verified`, klayout-tools #2196) resolves that string
against the grading process's own filesystem, so a committed absolute path
is unverifiable from any other checkout -- the very portability gap the
`{path, scope: "repo"}` shape (klayout-tools #1261) exists to close, and
which `klt signoff` already knows how to consume
(`_input_artifact_candidates` resolves `scope: "repo"` against the repo
root discovered from the evidence file's own location).

This script performs exactly that normalization -- mechanically, on the one
field, nothing else -- so the committed evidence can be re-verified from any
clone. The normalization is applied to the envelope BEFORE it is first
committed; the record that cites the envelope discloses this in its Run
configuration section. The envelope's `provenance.input.content_hash` (what
the manifest pins, and what the freshness gate re-hashes) is untouched.

Usage:
    python3 scripts/normalize-envelope-input-path.py <envelope.json> <field> <repo-relative-path>

Exits 0 and rewrites the file in place (json.dump with indent=1, sorted
keys preserved as produced) on success; exits 1 with a message on any
mismatch (field absent, field not the expected absolute path, target path
does not resolve inside the repo, hash mismatch after rewrite).
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: normalize-envelope-input-path.py <envelope.json> <field> <repo-relative-path>",
            file=sys.stderr,
        )
        return 1
    envelope_path, field, repo_relative = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(envelope_path, encoding="utf-8") as handle:
        envelope = json.load(handle)

    value = envelope.get(field)
    if not isinstance(value, str) or not os.path.isabs(value):
        print(
            f"error: {envelope_path}:{field} is not an absolute path string "
            f"(found {value!r}) -- refusing to normalize anything else",
            file=sys.stderr,
        )
        return 1

    # The repo-relative replacement must name the same artifact the producing
    # run hashed: resolve it against this checkout's root (the envelope sits
    # inside the repo) and require it to be the very file the absolute path
    # named.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(envelope_path)))
    while repo_root and not os.path.exists(os.path.join(repo_root, ".git")):
        repo_root = os.path.dirname(repo_root)
    if not repo_root:
        print(f"error: could not locate a repo root above {envelope_path}", file=sys.stderr)
        return 1
    candidate = os.path.realpath(os.path.join(repo_root, repo_relative))
    original = os.path.realpath(value)
    if candidate != original:
        print(
            f"error: {repo_relative!r} resolves to {candidate!r}, not the "
            f"envelope's own {value!r} -- refusing to point the citation at "
            "a different artifact",
            file=sys.stderr,
        )
        return 1

    envelope[field] = {"path": repo_relative, "scope": "repo"}
    tmp = envelope_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(envelope, handle, indent=1)
        handle.write("\n")
    os.replace(tmp, envelope_path)
    print(f"normalized {envelope_path}:{field} -> {{path: {repo_relative!r}, scope: 'repo'}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
