#!/usr/bin/env python3
"""Self-test for `scripts/normalize-envelope-input-path.py`.

The normalization is load-bearing for CI's signoff re-run gate: a wrongly
rewritten path would point `klt signoff`'s `input_verified` freshness check
at a different artifact and silently falsify a met citation. Each case below
is one distinction that property needs: a correct rewrite, a refusal when
the replacement path names a different file, a refusal when the field is not
an absolute path, the untouched-hash guarantee (`provenance.input` must
survive the rewrite byte-for-byte), a rewrite for an envelope sitting at the
very top of a checkout, and a prompt refusal when no Git root exists above
the envelope at all.

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


def _fixture_directory() -> tempfile.TemporaryDirectory:
    """Keep the fixture tree outside Git so the missing-root case has no checkout."""
    preferred = Path(tempfile.gettempdir()).resolve()
    system_dirs = (Path("/tmp"), Path("/var/tmp"), Path("/dev/shm"))
    for base in (preferred, *system_dirs, *preferred.parents):
        base = base.resolve()
        if any((ancestor / ".git").exists() for ancestor in (base, *base.parents)):
            continue
        try:
            # A full tmpfs can still allow mkdir but refuse file writes.
            with tempfile.TemporaryFile(dir=base) as probe:
                probe.write(b"x")
            return tempfile.TemporaryDirectory(dir=base)
        except OSError:
            continue
    raise RuntimeError("set TMPDIR to a writable directory outside any Git checkout")


# Every subprocess case gets this budget: an unbounded Git-root search in the
# normalizer would hang forever, and a regression must fail the case promptly
# (issue #491), not stall the suite.
SUBPROCESS_TIMEOUT_S = 10


def _run_normalizer(
    name: str, envelope: Path, field: str, repo_rel: str
) -> subprocess.CompletedProcess | None:
    """Run the real shipped script. On timeout, record the case as failed and
    return None so the caller skips its (unreachable) result checks."""
    try:
        return subprocess.run(
            [sys.executable, str(NORMALIZER), str(envelope), field, repo_rel],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        _run_case(name, False, f"timed out after {SUBPROCESS_TIMEOUT_S}s")
        return None


def main() -> int:
    with _fixture_directory() as tmp:
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
        proc = _run_normalizer("case_correct_rewrite", envelope_path, "file", repo_rel)
        if proc is not None:
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
        proc2 = _run_normalizer(
            "case_wrong_target_refused",
            envelope2,
            "file",
            "verification/records/x/artifacts/rid/other.gds",
        )
        if proc2 is not None:
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
        proc3 = _run_normalizer(
            "case_non_absolute_refused",
            envelope3,
            "file",
            "verification/records/x/artifacts/rid/design.gds",
        )
        if proc3 is not None:
            _run_case(
                "case_non_absolute_refused",
                proc3.returncode == 1 and envelope3.read_text(encoding="utf-8") == body3,
                f"rc={proc3.returncode}",
            )

        # Case 4: an envelope directly at the top of the checkout -- the
        # ancestor walk must start with the envelope's own containing
        # directory, so this is the checkout's root it finds (the old lookup
        # started one level higher and missed it).
        repo4 = root / "r4"
        _artifacts4, artifact4 = _fixture_repo(repo4)
        envelope4 = repo4 / "klt-drc.json"
        envelope4.write_text(
            json.dumps({"schema_version": 2, "file": str(artifact4)}),
            encoding="utf-8",
        )
        repo_rel4 = "verification/records/x/artifacts/rid/design.gds"
        proc4 = _run_normalizer("case_root_level_envelope", envelope4, "file", repo_rel4)
        if proc4 is not None:
            rewritten4 = json.loads(envelope4.read_text(encoding="utf-8"))
            _run_case(
                "case_root_level_envelope",
                proc4.returncode == 0
                and rewritten4["file"] == {"path": repo_rel4, "scope": "repo"},
                f"rc={proc4.returncode} stderr={proc4.stderr.strip()[:200]}",
            )

        # Case 5: no Git root anywhere above the envelope -- the walk must
        # exhaust the ancestors, hit the missing-root diagnostic, and leave
        # the envelope byte-identical (the old lookup looped forever at the
        # filesystem root instead).
        norepo = root / "no-repo" / "sub"
        norepo.mkdir(parents=True)
        envelope5 = norepo / "klt-drc.json"
        body5 = json.dumps({"schema_version": 2, "file": str(artifact)}).encode("utf-8")
        envelope5.write_bytes(body5)
        proc5 = _run_normalizer(
            "case_no_git_ancestor_refused",
            envelope5,
            "file",
            "verification/records/x/artifacts/rid/design.gds",
        )
        if proc5 is not None:
            _run_case(
                "case_no_git_ancestor_refused",
                proc5.returncode == 1
                and "could not locate a repo root" in proc5.stderr
                and envelope5.read_bytes() == body5,
                f"rc={proc5.returncode} stderr={proc5.stderr.strip()[:200]}",
            )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} case(s) FAILED")
        return 1
    print("all cases behaved as specified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
