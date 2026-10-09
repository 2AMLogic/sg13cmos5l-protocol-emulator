#!/usr/bin/env python3
"""Tests for scripts/check_datasheet.py (issue #110). Stdlib only.

    python3 scripts/test_check_datasheet.py
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_datasheet  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def copy_tree(dst: Path) -> None:
    (dst / "docs").mkdir()
    shutil.copy(REPO / "docs" / "info.md", dst / "docs" / "info.md")
    shutil.copytree(REPO / "firmware" / "asm", dst / "firmware" / "asm")
    shutil.copytree(REPO / "firmware" / "build", dst / "firmware" / "build")
    for rel in ("verification", ):
        # only link targets are needed; copy the files the table cites
        shutil.copytree(REPO / rel, dst / rel,
                        ignore=shutil.ignore_patterns("__pycache__", "artifacts", "formal", "duts"))


class DatasheetDrift(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        copy_tree(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_committed_tree_is_in_step(self):
        self.assertEqual(check_datasheet.check(self.root), [])

    def test_added_image_fails(self):
        (self.root / "firmware/asm/new_proto.asm").write_text("HALT\n")
        errs = check_datasheet.check(self.root)
        self.assertTrue(any("new_proto" in e and "no row" in e for e in errs), errs)

    def test_removed_image_fails(self):
        (self.root / "firmware/asm/uart_tx.asm").unlink()
        errs = check_datasheet.check(self.root)
        self.assertTrue(any("lists `uart_tx`" in e for e in errs), errs)

    def test_missing_build_artefact_fails(self):
        (self.root / "firmware/build/spi_mode0.hex").unlink()
        errs = check_datasheet.check(self.root)
        self.assertTrue(any("spi_mode0.hex missing" in e for e in errs), errs)

    def test_stale_numbers_fail(self):
        p = self.root / "firmware/build/uart_tx.cycles.txt"
        p.write_text(p.read_text().replace("WORDS 34", "WORDS 35"))
        errs = check_datasheet.check(self.root)
        self.assertTrue(any("uart_tx" in e and "Words" in e for e in errs), errs)

    def test_row_deleted_from_table_fails(self):
        p = self.root / "docs/info.md"
        lines = [ln for ln in p.read_text().splitlines(True) if not ln.startswith("| [`i2c_std`]")]
        p.write_text("".join(lines))
        errs = check_datasheet.check(self.root)
        self.assertTrue(any("i2c_std.asm is committed" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
