# 0022: New Bulk Evidence Bytes Go to the Artifact Store; Git Keeps a Manifest and a Summary

Status: **Proposed 2026-10-23.** Like the other proposed records it is not bound
by the two-key (`RATIFY-KEY`) mechanism (DR [`0006`](0006-two-key-ratification-never-ran.md)).
It changes no RTL, spec value, claim or ratified text.
Date: 2026-10-23
Issues: #344; fleet-wide 2AMLogic/2am#5553.

## Context

`verification/records/` holds about 437 MB of raw run output (DRC/LVS JSON,
netlists, SPICE, SDF and regression logs), mostly under
`librelane-gds-signoff-check`, `post-layout-sdf-regression` and
`random-regression`. The append-only evidence convention
(`verification/README.md`) says a result is superseded by a later record, never
deleted, so every re-mint grows the repository.

## Decision

1. From this record on, a new run of a heavy experiment stores its raw outputs in
   the fleet's common artifact store (`klt artifact put`). Git keeps
   `manifests/artifacts/<experiment>-<record-id>.manifest.json` and the record's
   Markdown summary (name, size, sha256 per object). Evidence bytes are private;
   manifests are public.
2. The writer fails closed. With `$KLT_ARTIFACT_BROKER` unset, no `klt artifact put`
   or an unreachable broker it exits nonzero and commits nothing. Bytes are never
   committed as a fallback.
3. **Manifest-forward only.** No history rewrite and no migration of committed
   records; they stay as they are, so append-only is intact. Small experiments
   and not-yet-run benches keep committing their (small) artifacts until a later
   record moves them.
4. `scripts/check_artifact_manifests.py` (in `npm run lint`, so in CI) accepts
   only `artifact:` URIs, rejects bucket/account names, and fails if a stored
   object's bytes are also committed.

## Consequences

A stored record is verified by `klt artifact verify <manifest>`, which needs
broker access (fleet workers have it); a reader without access sees the manifest
and the summary hashes but not the bytes. That is the intended privacy split and
is a cost for outside reviewers of the new records.

## Not done

Migrating the 437 MB already committed; wiring hand-run flow scripts under
`flow/` (they can call `verification/artifact_store.py`); any evidence-size
ceiling (none exists in this repo).
