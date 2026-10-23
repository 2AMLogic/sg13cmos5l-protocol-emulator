# manifests/artifacts/ — manifests for evidence bytes held in the artifact store

One `<experiment>-<record-id>.manifest.json` per stored run, written by
`klt artifact put --manifest` (via `verification/artifact_store.py`). Each
entry names an object by `sha256`, `size`, `name` and an `artifact:<key>` URI.
The bytes are private and live in the fleet's common artifact store; a manifest
is public and safe to commit. A manifest never contains a bucket, account ID,
`s3://` URI or broker URL.

- Check a manifest from a fleet worker: `klt artifact verify <manifest>`.
- Fetch one object: `klt artifact get` (it writes the file only if its sha256 verifies).
- `python3 scripts/check_artifact_manifests.py` (part of `npm run lint`) validates
  the schema, accepts only `artifact:` URIs, and fails if a stored object's bytes
  are also committed.
- Manifest-forward only: records committed before this convention keep their
  bytes in git and are not rewritten.
