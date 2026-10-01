#!/usr/bin/env python3
"""Self-test for `scripts/normalize-envelope-input-path.py`.

The normalization is load-bearing for CI's signoff re-run gate: a wrongly
rewritten path would point `klt signoff`'s `input_verified` freshness check
at a different artifact and silently falsify a met citation. Each case below
is one distinction that property needs: a correct rewrite, a refusal when
the replacement path names a different file, a refusal when the field is not
an absolute path, and the untouched-hash guarantee (`provenance.input` must
survive the rewrite byte-for-byte).

Method (the same shape as `scripts/test_check_test_results.py`): build a
fixture repo tree in a temp dir and run the *real* shipped script as a
subprocess against it. Nothing is monkeypatched or mocked.

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 scripts/test_normalize_envelope_input_path.py
Exit codes: 0 all cases behave as specified, 1 at least one did not.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
NORMALIZER = SCRIPT_DIR / "normalize-envelope-input-path.py"

FAILURES: list[str] = []


def _run_case(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def _fixture_repo(root: Path) -> tuple[Path, Path]:
    """A fake repo root (bare ``.git`` marker file, as a linked worktree has)
    containing one artifacts dir with the input artifact beside the envelope."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")
    artifacts = root / "verification" / "records" / "x" / "artifacts" / "rid"
    artifacts.mkdir(parents=True)
    artifact = artifacts / "design.gds"
    artifact.write_bytes(b"\x00\x06\x00\x02 gds bytes")
    return artifacts, artifact


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # Case 1: a correct rewrite -- absolute -> {path, scope: repo}, hash
        # untouched, and the rewritten field resolves back to the same file.
        artifacts, artifact = _fixture_repo(root / "r1")
        envelope_path = artifacts / "klt-drc.json"
        envelope_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "clean",
                    "file": str(artifact),
                    "provenance": {
                        "input": {
                            "content_hash": "sha256:deadbeef",
                            "role": "layout",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        repo_rel = "verification/records/x/artifacts/rid/design.gds"
        proc = subprocess.run(
            [sys.executable, str(NORMALIZER), str(envelope_path), "file", repo_rel],
            capture_output=True,
            text=True,
        )
        rewritten = json.loads(envelope_path.read_text(encoding="utf-8"))
        _run_case(
            "case_correct_rewrite",
            proc.returncode == 0
            and rewritten["file"] == {"path": repo_rel, "scope": "repo"}
            and rewritten["provenance"]["input"]["content_hash"] == "sha256:deadbeef"
            and rewritten["status"] == "clean",
            f"rc={proc.returncode} stderr={proc.stderr.strip()[:200]}",
        )

        # Case 2: the replacement names a different file -> refuse, envelope
        # left byte-identical.
        artifacts2, _artifact2 = _fixture_repo(root / "r2")
        envelope2 = artifacts2 / "klt-drc.json"
        body2 = json.dumps({"schema_version": 2, "file": str(artifact)})
        envelope2.write_text(body2, encoding="utf-8")
        proc2 = subprocess.run(
            [
                sys.executable,
                str(NORMALIZER),
                str(envelope2),
                "file",
                "verification/records/x/artifacts/rid/other.gds",
            ],
            capture_output=True,
            text=True,
        )
        _run_case(
            "case_wrong_target_refused",
            proc2.returncode == 1 and envelope2.read_text(encoding="utf-8") == body2,
            f"rc={proc2.returncode}",
        )

        # Case 3: the field is not an absolute path string -> refuse.
        artifacts3, _artifact3 = _fixture_repo(root / "r3")
        envelope3 = artifacts3 / "klt-drc.json"
        body3 = json.dumps({"schema_version": 2, "file": "already/relative.gds"})
        envelope3.write_text(body3, encoding="utf-8")
        proc3 = subprocess.run(
            [
                sys.executable,
                str(NORMALIZER),
                str(envelope3),
                "file",
                "verification/records/x/artifacts/rid/design.gds",
            ],
            capture_output=True,
            text=True,
        )
        _run_case(
            "case_non_absolute_refused",
            proc3.returncode == 1 and envelope3.read_text(encoding="utf-8") == body3,
            f"rc={proc3.returncode}",
        )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} case(s) FAILED")
        return 1
    print("all cases behaved as specified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
