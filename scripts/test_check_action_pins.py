#!/usr/bin/env python3
"""Self-test for scripts/check_action_pins.py.

Run: python3 scripts/test_check_action_pins.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_action_pins as cap  # noqa: E402

A = "a" * 40
B = "b" * 40
ROOT = "TinyTapeout/tt-gds-action"


class ActionPinCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.wf = self.repo / ".github" / "workflows"
        self.wf.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, *lines: str) -> None:
        (self.wf / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_main(self) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cap.main(["--repo", str(self.repo)])
        return code, out.getvalue() + err.getvalue()

    def one(self, ref_line: str) -> tuple[int, str]:
        self.write("w.yaml", "jobs:", "  j:", "    steps:", ref_line)
        return self.run_main()

    def test_all_pinned_equal_passes(self):
        self.write("a.yaml", f"      - uses: {ROOT}@{A} # ihp-cmos5l",
                   f"        uses: {ROOT}/precheck@{A}")
        self.write("b.yml", f"        uses: {ROOT}/fpga/ice40up5k@{A}")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_bad_refs_fail(self):
        for ref in ("ihp-cmos5l", "v1.2.3", "main", "abcdef1", "abcdef123456",
                    "g" * 40, "A" * 40, "a" * 41, ""):
            with self.subTest(ref=ref):
                code, out = self.one(f"        uses: {ROOT}@{ref}")
                self.assertEqual(code, 1, out)
                self.assertIn("w.yaml:4", out)

    def test_missing_at_fails(self):
        self.assertEqual(self.one(f"        uses: {ROOT}/viewer")[0], 1)

    def test_subpaths_checked(self):
        for sub in ("/precheck", "/fpga/ice40up5k", "/gl_test"):
            with self.subTest(sub=sub):
                self.assertEqual(self.one(f"        uses: {ROOT}{sub}@ihp-cmos5l")[0], 1)
                self.assertEqual(self.one(f"        uses: {ROOT}{sub}@{A}")[0], 0)

    def test_quoted_and_list_item(self):
        self.assertEqual(self.one(f"      - uses: '{ROOT}/viewer@{A}'")[0], 0)
        self.assertEqual(self.one(f'      - uses: "{ROOT}/viewer@main"')[0], 1)

    def test_two_different_shas_fail(self):
        self.write("a.yaml", f"        uses: {ROOT}@{A}", f"        uses: {ROOT}/docs@{B}")
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn("share one SHA", out)

    def test_other_actions_ignored(self):
        self.write("a.yaml", f"        uses: {ROOT}@{A}", "        uses: actions/checkout@v6")
        self.assertEqual(self.run_main()[0], 0)

    def test_commented_line_ignored(self):
        self.write("a.yaml", f"        uses: {ROOT}@{A}", f"        # uses: {ROOT}@main")
        self.assertEqual(self.run_main()[0], 0)

    def test_zero_refs_fails(self):
        self.write("a.yaml", "        uses: actions/checkout@v6")
        code, out = self.run_main()
        self.assertEqual(code, 1, out)

    def test_missing_dir_fails(self):
        self.wf.rmdir()
        self.assertEqual(self.run_main()[0], 1)

    def test_real_repo_passes(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cap.main([])
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
