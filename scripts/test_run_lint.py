#!/usr/bin/env python3
"""Self-test for scripts/run_lint.py (issue #296). Standard library only."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_lint  # noqa: E402


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()) as out, \
            contextlib.redirect_stderr(io.StringIO()):
        r = fn(*a)
    return r, out.getvalue()


class ParseTests(unittest.TestCase):
    def test_comments_blank_and_order(self):
        cmds, err = run_lint.parse_manifest("# c\n\n  a b  \n# x\nc\n")
        self.assertEqual(cmds, ["a b", "c"])
        self.assertEqual(err, [])

    def test_unparseable_quote(self):
        _, err = run_lint.parse_manifest("echo 'oops\n")
        self.assertEqual(len(err), 1)


class RunTests(unittest.TestCase):
    def test_all_entries_run_after_failure_and_exit_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            m = root / "m.txt"
            m.write_text(
                f"{sys.executable} -c 'import sys; sys.exit(3)'\n"
                f"{sys.executable} -c 'open(\"ran\", \"w\").close()'\n")
            rc, out = quiet(run_lint.main, ["--repo-root", d, "--manifest", str(m)])
            self.assertEqual(rc, 1)
            self.assertTrue((root / "ran").exists(), "later entry must still run")
            self.assertIn("FAIL (", out)
            self.assertIn("PASS (", out)
            self.assertIn("1/2 passed", out)

    def test_all_pass_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m.txt"
            m.write_text(f"{sys.executable} -c 'pass'\n")
            rc, _ = quiet(run_lint.main, ["--repo-root", d, "--manifest", str(m)])
            self.assertEqual(rc, 0)

    def test_missing_executable_is_failure(self):
        res = quiet(run_lint.run_all, ["/nonexistent/prog-296"], Path("."))[0]
        self.assertFalse(res[0][1])

    def test_bad_or_empty_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m.txt"
            m.write_text("# nothing\n")
            self.assertEqual(quiet(run_lint.main, ["--manifest", str(m)])[0], 1)
            self.assertEqual(
                quiet(run_lint.main, ["--manifest", str(Path(d) / "none")])[0], 1)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import check_lint_inventory as inv
        self.inv = inv

    def test_exemption_parsing(self):
        ex, err = self.inv.parse_exemptions("# c\na/test_x.py :: why\nb/test_y.py ::\n")
        self.assertEqual(ex, {"a/test_x.py": "why"})
        self.assertEqual(len(err), 1)

    def test_unwired_is_flagged_and_exempt_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for p in ("scripts/test_run_lint.py", "scripts/check_ratification_gate.py",
                      "x/test_a.py", "x/test_b.py"):
                (root / p).parent.mkdir(parents=True, exist_ok=True)
                (root / p).write_text("")
            tests = ["scripts/test_run_lint.py", "x/test_a.py", "x/test_b.py"]
            cmds = ["python3 scripts/test_run_lint.py", "python3 x/test_a.py",
                    "python3 scripts/check_ratification_gate.py --base-ref origin/main"]
            errs = self.inv.check(tests, cmds, {}, root)
            self.assertEqual(len(errs), 1)
            self.assertIn("x/test_b.py", errs[0])
            self.assertEqual(self.inv.check(tests, cmds, {"x/test_b.py": "r"}, root), [])

    def test_stale_and_ordering(self):
        with tempfile.TemporaryDirectory() as d:
            errs = self.inv.check([], ["python3 gone.py"], {"q/test_z.py": "r"}, Path(d))
            joined = "\n".join(errs)
            self.assertIn("missing file gone.py", joined)
            self.assertIn("stale", joined)
            self.assertIn("first manifest entry", joined)
            self.assertIn("last manifest entry", joined)


if __name__ == "__main__":
    unittest.main()
