#!/usr/bin/env python3
"""Self-test for scripts/check_lint_inventory.py (issue #296): runs it against a
temporary git repo. Standard library only."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "check_lint_inventory.py"
LAST = "python3 scripts/check_ratification_gate.py --base-ref origin/main"


def make_repo(d, manifest, exempt, files):
    root = Path(d)
    files = dict(files)
    files["scripts/lint-manifest.txt"] = manifest
    files["scripts/lint-self-test-exemptions.txt"] = exempt
    for p, t in files.items():
        (root / p).parent.mkdir(parents=True, exist_ok=True)
        (root / p).write_text(t)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def run(root):
    return subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(root)],
                          capture_output=True, text=True)


BASE = {"scripts/test_run_lint.py": "", "scripts/check_ratification_gate.py": ""}
MAN = "python3 scripts/test_run_lint.py\n"


class T(unittest.TestCase):
    def test_pass(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(make_repo(d, MAN + LAST + "\n", "", BASE))
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_unwired_stdlib_fails_but_cocotb_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            files = dict(BASE, **{"v/test_new.py": "import unittest\n",
                                  "v/test_bench.py": "import cocotb\n"})
            r = run(make_repo(d, MAN + LAST + "\n", "", files))
            self.assertEqual(r.returncode, 1)
            self.assertIn("v/test_new.py", r.stderr)
            self.assertNotIn("test_bench", r.stderr)

    def test_exemption_needs_reason(self):
        with tempfile.TemporaryDirectory() as d:
            files = dict(BASE, **{"v/test_new.py": ""})
            r = run(make_repo(d, MAN + LAST + "\n", "v/test_new.py ::\n", files))
            self.assertEqual(r.returncode, 1)
            r = run(make_repo(d, MAN + LAST + "\n", "v/test_new.py :: why\n", files))
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
