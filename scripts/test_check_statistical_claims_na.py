#!/usr/bin/env python3
"""Self-test for scripts/check_statistical_claims_na.py.

Each case builds a throwaway tree with the four files the check reads, so
nothing here depends on the state of this repository. Fixtures deliberately
use ids only in spec rows and classes free of the grader's statistical
vocabulary, mirroring what the real companions must look like.

Run: python3 scripts/test_check_statistical_claims_na.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_statistical_claims_na as csc  # noqa: E402


def sha(file: Path) -> str:
    return f"sha256:{hashlib.sha256(file.read_bytes()).hexdigest()}"


class ClaimCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "spec").mkdir()
        self.spec_md = self.root / "spec" / "target-spec.md"
        self.statement_md = self.root / "spec" / "statistical-claims-na.md"
        self.spec_md.write_text("# spec\n\n| row table |\n", encoding="utf-8")
        self.statement_md.write_text("# statement\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_spec_json(
        self, rows: list[object] | None = None, status: str = "ratified"
    ) -> None:
        if rows is None:
            rows = [{"id": "1"}, {"id": "2"}]
        doc = {
            "status": status,
            "source": "spec/target-spec.md",
            "source_content_hash": sha(self.spec_md),
            "rows": rows,
        }
        (self.root / "spec" / "target-spec-ratified.json").write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8"
        )

    def write_statement_json(
        self,
        rows: list[object] | None = None,
        spec_hash: str | None = None,
        statement_hash: str | None = None,
        not_covered: list[object] | None = None,
    ) -> None:
        if rows is None:
            rows = [
                {"id": "1", "class": "functional", "reason": "benches"},
                {"id": "2", "class": "process", "reason": "deadline"},
            ]
        doc = {
            "statement": "spec/statistical-claims-na.md",
            "statement_content_hash": statement_hash or sha(self.statement_md),
            "spec_markdown": "spec/target-spec.md",
            "spec_markdown_content_hash": spec_hash or sha(self.spec_md),
            "rows": rows,
        }
        if not_covered is not None:
            doc["not_covered"] = not_covered
        (self.root / "spec" / "statistical-claims-na.json").write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8"
        )

    def test_good_tree_passes(self) -> None:
        self.write_spec_json()
        self.write_statement_json(
            not_covered=[{"id": "13", "reason": "unratified"}]
        )
        self.assertEqual(csc.check(self.root), [])

    def test_spec_markdown_drift_fails_both_embeds(self) -> None:
        self.write_spec_json()
        self.write_statement_json()
        self.spec_md.write_text("# spec, edited\n", encoding="utf-8")
        errors = csc.check(self.root)
        joined = "\n".join(errors)
        self.assertIn("target-spec-ratified.json", joined)
        self.assertIn("spec_markdown_content_hash", joined)

    def test_statement_markdown_drift_fails(self) -> None:
        self.write_spec_json()
        self.write_statement_json()
        self.statement_md.write_text("# statement, edited\n", encoding="utf-8")
        errors = "\n".join(csc.check(self.root))
        self.assertIn("statement_content_hash", errors)

    def test_embed_disagreement_fails(self) -> None:
        self.write_spec_json()
        self.write_statement_json(spec_hash="sha256:" + "0" * 64)
        errors = "\n".join(csc.check(self.root))
        self.assertIn("disagrees", errors)

    def test_unratified_status_fails(self) -> None:
        self.write_spec_json(status="proposed")
        self.write_statement_json()
        errors = "\n".join(csc.check(self.root))
        self.assertIn("ratified", errors)

    def test_spec_row_with_extra_key_fails(self) -> None:
        self.write_spec_json(
            rows=[{"id": "1", "title": "UART bit-timing accuracy"}]
        )
        self.write_statement_json(
            rows=[{"id": "1", "class": "functional", "reason": "benches"}]
        )
        errors = "\n".join(csc.check(self.root))
        self.assertIn("ids only", errors)

    def test_statistical_class_fails(self) -> None:
        self.write_spec_json()
        self.write_statement_json(
            rows=[{"id": "1", "class": "clock accuracy", "reason": "x"},
                  {"id": "2", "class": "process", "reason": "y"}]
        )
        errors = "\n".join(csc.check(self.root))
        self.assertIn("statistical scan", errors)

    def test_coverage_mismatch_fails(self) -> None:
        self.write_spec_json(rows=[{"id": "1"}, {"id": "2"}])
        self.write_statement_json(
            rows=[{"id": "1", "class": "functional", "reason": "benches"}]
        )
        errors = "\n".join(csc.check(self.root))
        self.assertIn("uncovered ids ['2']", errors)

    def test_unknown_row_fails(self) -> None:
        self.write_spec_json(rows=[{"id": "1"}])
        self.write_statement_json(
            rows=[
                {"id": "1", "class": "functional", "reason": "benches"},
                {"id": "9", "class": "process", "reason": "deadline"},
            ]
        )
        errors = "\n".join(csc.check(self.root))
        self.assertIn("unknown ids ['9']", errors)

    def test_missing_reason_fails(self) -> None:
        self.write_spec_json(rows=[{"id": "1"}])
        self.write_statement_json(
            rows=[{"id": "1", "class": "functional", "reason": ""}]
        )
        errors = "\n".join(csc.check(self.root))
        self.assertIn("class' and 'reason'", errors)

    def test_missing_file_fails(self) -> None:
        errors = "\n".join(csc.check(self.root))
        self.assertIn("missing", errors)

    def test_not_covered_colliding_with_rows_fails(self) -> None:
        self.write_spec_json(rows=[{"id": "1"}])
        self.write_statement_json(
            rows=[{"id": "1", "class": "functional", "reason": "benches"}],
            not_covered=[{"id": "1", "reason": "collides"}],
        )
        errors = "\n".join(csc.check(self.root))
        self.assertIn("belongs in 'rows'", errors)

    def test_scan_mirrors_grader_on_marker_words(self) -> None:
        for text in (
            "3 sigma", "±3σ", "Cpk 1.33", "offset voltage",
            "monte carlo", "Monte_Carlo", "yield 0.9", "matching",
            "bit-timing accuracy", "mismatch",
        ):
            self.assertIsNotNone(
                csc.scan_statistical(text, "x"), text
            )
        # std-dev is key-only in the grader's scan (mirrored here).
        self.assertIsNotNone(csc.scan_statistical({"std_dev": "1.2"}, ""))
        self.assertIsNone(csc.scan_statistical("std dev", "x"))
        for clean in (
            "functional", "deterministic-timing", "corner-bounded-sta",
            "area-budget", "pin-budget", "process",
            "deterministic-cycle-count bound", "phase minimums",
        ):
            self.assertIsNone(csc.scan_statistical(clean, "x"), clean)


if __name__ == "__main__":
    unittest.main()
