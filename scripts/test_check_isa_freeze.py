#!/usr/bin/env python3
"""Self-test for scripts/check_isa_freeze.py.

Each case builds a throwaway git repository with a small freeze manifest, a
freeze record and the files they pin, so nothing here depends on the state
of this repository. `npm run lint` runs the check itself on this one.

Run: python3 scripts/test_check_isa_freeze.py
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_isa_freeze as cif  # noqa: E402

RECORD = "spec/decision-records/0017-submission-isa-freeze.md"
CORE = "rtl/core.v"
ISA = "spec/decision-records/0001-isa.md"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IsaFreezeCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.git("init", "-q", "-b", "main")
        self.write(CORE, "module core; endmodule\n")
        self.write(ISA, "# 0001\nopcodes\n")
        self.commit("base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.manifest = {
            "schema": "isa-freeze/v1",
            "record": RECORD,
            "freeze_base_commit": self.base,
            "first_amending_dr": 18,
            "pins": [
                {"path": CORE, "sha256": sha("module core; endmodule\n"), "why": "the core"},
                {"path": ISA, "sha256": sha("# 0001\nopcodes\n"), "why": "the opcodes"},
            ],
            "amendments": [],
        }
        self.write_manifest()
        self.write_record()
        self.commit("freeze")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
             "-c", "commit.gpgsign=false", *args],
            check=True, capture_output=True, text=True,
        ).stdout

    def write(self, rel: str, text: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str = "c") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def write_manifest(self) -> None:
        self.write(cif.MANIFEST_REL, json.dumps(self.manifest, indent=2) + "\n")

    def write_record(self, pins: list[dict] | None = None) -> None:
        rows = "\n".join(f"| `{p['path']}` | `{p['sha256']}` |" for p in (pins or self.manifest["pins"]))
        self.write(RECORD, f"# 0017\n\nMachine-readable: `{cif.MANIFEST_REL}`.\n\n{rows}\n")

    def run_main(self, *extra: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cif.main(["--repo", str(self.repo), "--base-ref", "no-such-ref", *extra])
        return code, out.getvalue() + err.getvalue()

    def amend(self, rel: str, new_text: str, dr: int | None = 18, **over) -> None:
        before = None
        for a in reversed(self.manifest["amendments"]):
            if a["path"] == rel:
                before = a["sha256_after"]
                break
        if before is None:
            before = next(p["sha256"] for p in self.manifest["pins"] if p["path"] == rel)
        entry = {
            "dr": dr, "path": rel, "kind": "isa-change", "invalidates_row13_evidence": False,
            "sha256_before": before, "sha256_after": sha(new_text),
        }
        if dr is None:
            del entry["dr"]
        entry.update(over)
        self.manifest["amendments"].append(entry)
        self.write(rel, new_text)
        self.write_manifest()

    def write_dr(self, number: int, mentions: str) -> None:
        self.write(f"spec/decision-records/{number:04d}-amend.md", f"# {number:04d}\n\nAmends `{mentions}`.\n")

    # -- cases -----------------------------------------------------------
    def test_clean_tree_passes(self) -> None:
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("OK: 2 ISA-defining file(s)", out)

    def test_unamended_edit_fails(self) -> None:
        self.write(CORE, "module core; wire x; endmodule\n")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn(f"{CORE}: sha256", out)
        self.assertIn("0018 or later", out)

    def test_edit_with_later_dr_passes(self) -> None:
        self.write_dr(18, CORE)
        self.amend(CORE, "module core; wire x; endmodule\n")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("1 amendment(s)", out)

    def test_chained_amendments_pass_and_break(self) -> None:
        self.write_dr(18, CORE)
        self.write_dr(19, CORE)
        self.amend(CORE, "v2\n", dr=18)
        self.amend(CORE, "v3\n", dr=19, kind="conformance-fix")
        self.assertEqual(self.run_main()[0], 0)
        self.manifest["amendments"][1]["sha256_before"] = sha("something else\n")
        self.write_manifest()
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("does not continue the chain", out)

    def test_amendment_citing_earlier_dr_fails(self) -> None:
        self.write_dr(16, CORE)
        self.amend(CORE, "v2\n", dr=16)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("below 0018", out)

    def test_amendment_citing_missing_dr_fails(self) -> None:
        self.amend(CORE, "v2\n", dr=18)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("no decision record 0018", out)

    def test_amending_dr_must_name_the_path(self) -> None:
        self.write_dr(18, "some/other/file.v")
        self.amend(CORE, "v2\n", dr=18)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("does not name the amended path", out)

    def test_amendment_needs_row13_answer_and_kind(self) -> None:
        self.write_dr(18, CORE)
        self.amend(CORE, "v2\n", dr=18, kind="tweak", invalidates_row13_evidence="maybe")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("kind must be one of", out)
        self.assertIn("invalidates_row13_evidence must be true or false", out)

    def note(self, ref: str = "#218", **over) -> None:
        """A dated note on a pinned record, amended by an issue/PR ref only."""
        fields = {"kind": "no-behaviour-change", "ref": ref, "summary": "dated note"}
        fields.update(over)
        self.amend(ISA, "# 0001\nopcodes\n\n> Dated note.\n", dr=None, **fields)

    def test_notes_only_change_with_issue_ref_passes(self) -> None:
        self.note("#218")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_notes_only_change_with_cross_repo_ref_passes(self) -> None:
        self.note("2AMLogic/sg13cmos5l-protocol-emulator#84")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_isa_change_with_issue_ref_fails(self) -> None:
        self.amend(CORE, "v2\n", dr=None, kind="isa-change", ref="#218")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("kind isa-change needs a decision record", out)

    def test_conformance_fix_with_issue_ref_fails(self) -> None:
        self.amend(CORE, "v2\n", dr=None, kind="conformance-fix", ref="#218")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("kind conformance-fix needs a decision record", out)

    def test_notes_only_change_cannot_invalidate_row13(self) -> None:
        self.note(invalidates_row13_evidence=True)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("cannot invalidate row 13 evidence", out)

    def test_malformed_ref_fails(self) -> None:
        for bad in ("218", "#0", "https://github.com/o/r/pull/218", "#218 and more", ""):
            with self.subTest(ref=bad):
                self.manifest["amendments"] = []
                self.write(ISA, "# 0001\nopcodes\n")
                self.note(bad)
                code, out = self.run_main()
                self.assertEqual(code, 1)
                self.assertIn("must be an issue or PR reference", out)

    def test_ref_only_amendment_needs_summary(self) -> None:
        self.note(summary=" ")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("'summary'", out)

    def test_notes_only_change_with_no_citation_fails(self) -> None:
        self.amend(ISA, "# 0001\nopcodes\nfix\n", dr=None, kind="no-behaviour-change", summary="typo")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("cite a decision record (dr) or an issue/PR reference (ref)", out)

    def test_editing_a_pin_instead_of_amending_fails(self) -> None:
        # Re-pinning in the manifest and the record together still fails:
        # the pin no longer matches the freeze commit.
        self.write(CORE, "v2\n")
        self.manifest["pins"][0]["sha256"] = sha("v2\n")
        self.write_manifest()
        self.write_record()
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("pin does not match the file at freeze commit", out)

    def test_record_and_manifest_must_agree(self) -> None:
        wrong = [dict(p) for p in self.manifest["pins"]]
        wrong[1]["sha256"] = sha("other\n")
        self.write_record(wrong)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("pin different hashes", out)

    def test_symlink_pin_fails(self) -> None:
        self.write("rtl/real.v", "module core; endmodule\n")
        (self.repo / "src").mkdir()
        os.symlink("../rtl/real.v", self.repo / "src" / "core.v")
        self.git("add", "-A")
        self.manifest["pins"].append({"path": "src/core.v", "sha256": sha("module core; endmodule\n"), "why": "x"})
        self.write_manifest()
        self.write_record()
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("symlink", out)

    def test_untracked_or_missing_pin_fails(self) -> None:
        self.manifest["pins"].append({"path": "rtl/new.v", "sha256": sha("x\n"), "why": "x"})
        self.write_manifest()
        self.write_record()
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("rtl/new.v: pinned but not tracked", out)

    def test_bad_manifest_shapes_fail(self) -> None:
        self.manifest["freeze_base_commit"] = "e74d2b6"
        self.manifest["pins"][0]["path"] = "../escape.v"
        self.write_manifest()
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("full 40-hex commit", out)
        self.assertIn("repo-relative POSIX path", out)

    def test_unreadable_manifest_exits_2(self) -> None:
        self.write(cif.MANIFEST_REL, "{not json")
        code, out = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", out)

    def test_missing_freeze_commit_is_a_note_not_a_failure(self) -> None:
        # Rewrite the freezing commit itself, so the manifest's first
        # committed version already names the absent commit.
        self.manifest["freeze_base_commit"] = "0" * 40
        self.write_manifest()
        self.git("commit", "-q", "-a", "--amend", "-m", "freeze")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("NOTE: freeze commit", out)


    # -- shrinking or rewriting the pinned set (PR #233 review) ----------
    def drop_pin(self, rel: str, *, from_manifest: bool = True, from_record: bool = False) -> None:
        kept = [p for p in self.manifest["pins"] if p["path"] != rel]
        if from_manifest:
            self.manifest["pins"] = kept
            self.write_manifest()
        if from_record:
            self.write_record(kept)

    def test_removing_a_manifest_pin_fails_with_file_unchanged(self) -> None:
        self.drop_pin(CORE)
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn(f"{CORE}: pinned in {RECORD} but not in", out)

    def test_removing_a_manifest_pin_fails_with_file_changed(self) -> None:
        # The reviewer's repro: drop CORE from the manifest, change CORE,
        # leave the record alone.
        self.drop_pin(CORE)
        self.write(CORE, "module core; wire changed; endmodule\n")
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn(f"{CORE}: pinned in {RECORD} but not in", out)

    def test_removing_a_record_row_fails(self) -> None:
        self.drop_pin(CORE, from_manifest=False, from_record=True)
        self.write(CORE, "module core; wire changed; endmodule\n")
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn(f"{CORE}: pinned in {cif.MANIFEST_REL} but missing from {RECORD}", out)

    def test_removing_a_pin_from_both_fails_against_first_commit(self) -> None:
        self.drop_pin(CORE, from_manifest=True, from_record=True)
        self.write(CORE, "module core; wire changed; endmodule\n")
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn(f"removed {CORE}", out)
        # Committing the removal does not move the anchor.
        self.commit("drop the pin")
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn("as first committed", out)

    def test_rehashing_a_pin_in_both_and_committing_fails(self) -> None:
        self.write(CORE, "v2\n")
        self.manifest["pins"][0]["sha256"] = sha("v2\n")
        self.write_manifest()
        self.write_record()
        self.commit("re-pin")
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn(f"re-hashed {CORE}", out)

    def test_changing_the_freeze_commit_fails(self) -> None:
        self.manifest["freeze_base_commit"] = "0" * 40
        self.write_manifest()
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn("freeze_base_commit: changed", out)

    def test_duplicate_record_row_fails(self) -> None:
        self.write_record(self.manifest["pins"] + [self.manifest["pins"][0]])
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn("appears twice in the pin table", out)

    def test_unpin_by_amendment_with_dr_passes(self) -> None:
        self.write_dr(18, CORE)
        self.manifest["amendments"].append({
            "op": "unpin", "dr": 18, "path": CORE, "kind": "isa-change",
            "invalidates_row13_evidence": False, "sha256_before": self.manifest["pins"][0]["sha256"],
        })
        self.write_manifest()
        self.write(CORE, "moved away\n")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("OK: 1 ISA-defining file(s)", out)

    def test_unpin_with_only_a_ref_fails(self) -> None:
        self.manifest["amendments"].append({
            "op": "unpin", "ref": "#218", "summary": "x", "path": CORE, "kind": "no-behaviour-change",
            "invalidates_row13_evidence": False, "sha256_before": self.manifest["pins"][0]["sha256"],
        })
        self.write_manifest()
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn("op unpin changes the pinned set and needs a decision record", out)

    def test_pin_a_new_file_by_amendment_is_then_checked(self) -> None:
        self.write("rtl/new.v", "new\n")
        self.write_dr(18, "rtl/new.v")
        self.manifest["amendments"].append({
            "op": "pin", "dr": 18, "path": "rtl/new.v", "kind": "isa-change",
            "invalidates_row13_evidence": False, "sha256_after": sha("new\n"),
        })
        self.write_manifest()
        self.commit("pin new")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn("OK: 3 ISA-defining file(s)", out)
        self.write("rtl/new.v", "changed\n")
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn("rtl/new.v: sha256", out)

    def test_amendments_on_the_base_ref_are_append_only(self) -> None:
        self.write_dr(18, CORE)
        self.amend(CORE, "v2\n", dr=18)
        self.commit("amend on main")
        self.git("checkout", "-q", "-b", "topic")
        self.assertEqual(self.run_main("--base-ref", "main")[0], 0)
        # Rewrite the landed amendment and the file to match: still refused.
        self.manifest["amendments"][0]["sha256_after"] = sha("v3\n")
        self.write(CORE, "v3\n")
        self.write_manifest()
        code, out = self.run_main("--base-ref", "main")
        self.assertEqual(code, 1, out)
        self.assertIn("amendments are append-only", out)
        # Appending instead passes.
        self.manifest["amendments"][0]["sha256_after"] = sha("v2\n")
        self.amend(CORE, "v3\n", dr=18)
        self.assertEqual(self.run_main("--base-ref", "main")[0], 0)


if __name__ == "__main__":
    unittest.main()
