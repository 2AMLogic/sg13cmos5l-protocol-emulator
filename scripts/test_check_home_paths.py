#!/usr/bin/env python3
"""Self-test for scripts/check_home_paths.py.

Each case builds a throwaway git repository, so nothing here depends on the
state of this one. The home-directory paths used as fixtures are assembled
at run time: a literal one in this file would make the file fail the very
check it tests.

Run: python3 scripts/test_check_home_paths.py
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_home_paths as chp  # noqa: E402

SLASH = "/"
MAC_HOME = SLASH + "Users" + SLASH + "someone"
LINUX_HOME = SLASH + "home" + SLASH + "someone"
BASELINE = "verification/home-path-baseline.txt"


def container_home(name: str) -> str:
    return SLASH + "home" + SLASH + name


class HomePathCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.git("init", "-q", "-b", "main")

    def tearDown(self) -> None:
        self._tmp.cleanup()

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

    def run_main(self, *args: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = chp.main(["--repo", str(self.repo), *args])
        return code, out.getvalue() + err.getvalue()

    # --- negative cases: the check must fail -------------------------------

    def test_added_dirty_record_fails(self) -> None:
        rel = "verification/records/x/artifacts/20270101-000000-abcdef0/run.json"
        self.write(rel, '{"input": "%s/work/design.gds"}\n' % MAC_HOME)
        self.commit()
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn(rel + ": line 1", output)

    def test_linux_home_fails(self) -> None:
        self.write("docs/notes.md", "ran in %s/build\n" % LINUX_HOME)
        self.commit()
        self.assertEqual(self.run_main()[0], 1)

    def test_path_without_trailing_component_fails(self) -> None:
        self.write("a.log", "cwd=%s\n" % MAC_HOME)
        self.commit()
        self.assertEqual(self.run_main()[0], 1)

    def test_dirty_file_outside_records_fails(self) -> None:
        self.write("layout/config.json", '{"pdk_root": "%s/pdk"}\n' % MAC_HOME)
        self.commit()
        self.assertEqual(self.run_main()[0], 1)

    def test_failure_does_not_echo_the_name(self) -> None:
        self.write("a.log", "x\ncwd=%s/y\n" % MAC_HOME)
        self.commit()
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("a.log: line 2", output)
        self.assertNotIn("someone", output)

    def test_baseline_covers_only_listed_files(self) -> None:
        self.write("old.json", "%s/a\n" % MAC_HOME)
        self.write("new.json", "%s/a\n" % MAC_HOME)
        self.write(BASELINE, "# reason\nold.json\n")
        self.commit()
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("new.json", output)
        self.assertNotIn("old.json", output)

    def test_allowed_name_does_not_excuse_another_hit_in_the_file(self) -> None:
        self.write("a.log", "%s/a\n%s/b\n" % (container_home("runner"), MAC_HOME))
        self.commit()
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("a.log: line 2", output)

    def test_rev_scans_the_committed_tree(self) -> None:
        self.write("clean.txt", "ok\n")
        self.commit()
        self.git("checkout", "-q", "-b", "dirty")
        self.write("a.log", "%s/a\n" % MAC_HOME)
        self.commit()
        self.git("checkout", "-q", "main")
        self.assertEqual(self.run_main()[0], 0)
        code, output = self.run_main("--rev", "dirty")
        self.assertEqual(code, 1)
        self.assertIn("a.log: line 1", output)

    def test_bad_rev_is_an_error_not_a_pass(self) -> None:
        self.write("clean.txt", "ok\n")
        self.commit()
        self.assertEqual(self.run_main("--rev", "no-such-ref")[0], 2)

    # --- positive cases: the check must pass -------------------------------

    def test_added_clean_record_passes(self) -> None:
        self.write(
            "verification/records/x/artifacts/20270101-000000-abcdef0/run.json",
            '{"input": "layout/design.gds"}\n',
        )
        self.commit()
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("OK", output)

    def test_preexisting_dirty_file_in_baseline_passes(self) -> None:
        self.write("verification/records/x/artifacts/old/run.json", "%s/a\n" % MAC_HOME)
        self.write(BASELINE, "# reason\n\nverification/records/x/artifacts/old/run.json\n")
        self.commit()
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("1 baselined", output)

    def test_container_accounts_pass(self) -> None:
        self.write("a.log", "".join("%s/work\n" % container_home(n) for n in sorted(chp.ALLOWED_NAMES)))
        self.commit()
        self.assertEqual(self.run_main()[0], 0)

    def test_relative_paths_and_urls_pass(self) -> None:
        self.write(
            "a.md",
            "docs" + LINUX_HOME + "/index.md\n"
            "https://example.invalid" + LINUX_HOME + "\n"
            "see " + SLASH + "Users" + SLASH + "<name>" + SLASH + " or ~" + SLASH + "work\n",
        )
        self.commit()
        self.assertEqual(self.run_main()[0], 0)

    def test_vendored_tooling_is_not_scanned(self) -> None:
        for d in chp.EXCLUDED_DIRS:
            self.write(d + "/docs/example.md", "e.g. %s/repo\n" % MAC_HOME)
        self.commit()
        self.assertEqual(self.run_main()[0], 0)

    def test_stale_baseline_entry_is_a_note_not_a_failure(self) -> None:
        self.write("clean.txt", "ok\n")
        self.write(BASELINE, "clean.txt\n")
        self.commit()
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("NOTE", output)


if __name__ == "__main__":
    unittest.main(verbosity=1)
