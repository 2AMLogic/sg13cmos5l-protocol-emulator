#!/usr/bin/env python3
"""Self-test for scripts/check_artifact_manifests.py.

Run: python3 scripts/test_check_artifact_manifests.py
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_artifact_manifests as cam  # noqa: E402

PAYLOAD = b"raw simulation output\n"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def entry(**over) -> dict:
    e = {
        "sha256": SHA,
        "size": len(PAYLOAD),
        "kind": "evidence",
        "producer": {"tool": "klt"},
        "uri": f"artifact:evidence/owner__repo/{SHA[:2]}/{SHA}",
        "name": "out.log",
    }
    e.update(over)
    return e


class ArtifactManifestCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        (self.repo / "manifests" / "artifacts").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def add(self, rel: str, data: bytes | str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        subprocess.run(["git", "add", "-f", rel], cwd=self.repo, check=True)

    def manifest(self, entries: list, name: str = "bench-run.manifest.json", **top) -> None:
        doc = {"schema_version": 1, "entries": entries}
        doc.update(top)
        self.add(f"manifests/artifacts/{name}", json.dumps(doc))

    def errors(self) -> list[str]:
        return cam.check(self.repo)

    def test_good_manifest_passes(self) -> None:
        self.manifest([entry()])
        self.assertEqual(self.errors(), [])

    def test_no_manifests_passes(self) -> None:
        self.assertEqual(self.errors(), [])

    def test_non_artifact_uri_fails(self) -> None:
        self.manifest([entry(uri="https://example.invalid/x/" + SHA)])
        self.assertTrue(any("artifact:" in e for e in self.errors()))

    def test_bucket_uri_fails(self) -> None:
        self.manifest([entry(uri="s3://bucket/" + SHA)])
        self.assertTrue(any("s3://" in e for e in self.errors()))

    def test_bad_schema_fails(self) -> None:
        self.manifest([entry(sha256="XYZ"), entry(size=-1, kind="x", name="")])
        errs = self.errors()
        self.assertTrue(any("sha256" in e for e in errs))
        self.assertTrue(any("size" in e for e in errs))
        self.assertTrue(any("kind" in e for e in errs))
        self.assertTrue(any("name" in e for e in errs))

    def test_wrong_schema_version_and_empty_fail(self) -> None:
        self.add("manifests/artifacts/a.manifest.json", json.dumps({"schema_version": 2, "entries": [entry()]}))
        self.add("manifests/artifacts/b.manifest.json", json.dumps({"schema_version": 1, "entries": []}))
        self.add("manifests/artifacts/c.manifest.json", "{not json")
        self.assertEqual(len(self.errors()), 3)

    def test_uri_not_ending_in_sha_fails(self) -> None:
        self.manifest([entry(uri="artifact:evidence/other")])
        self.assertTrue(any("end in" in e for e in self.errors()))

    def test_committed_stored_bytes_fail(self) -> None:
        self.manifest([entry()])
        self.add("verification/records/x/artifacts/r/out.log", PAYLOAD)
        errs = self.errors()
        self.assertEqual(len(errs), 1)
        self.assertIn("bytes are also committed", errs[0])

    def test_same_size_different_bytes_passes(self) -> None:
        self.manifest([entry()])
        self.add("other.log", b"x" * len(PAYLOAD))
        self.assertEqual(self.errors(), [])

    def test_tracked_file_in_scratch_fails(self) -> None:
        self.add(cam.SCRATCH_DIR + "/r/a.log", "anything")
        self.assertTrue(any("staging dir" in e for e in self.errors()))

    def test_main_exit_codes(self) -> None:
        self.manifest([entry()])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cam.main(["--repo", str(self.repo)]), 0)
            self.manifest([entry(uri="s3://b/" + SHA)], name="bad.manifest.json")
            self.assertEqual(cam.main(["--repo", str(self.repo)]), 1)


if __name__ == "__main__":
    unittest.main()
