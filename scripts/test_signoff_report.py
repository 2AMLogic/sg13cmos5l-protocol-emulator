#!/usr/bin/env python3
"""Self-test for scripts/signoff-report.sh --check-latest's reporting of the
optional doc_drift / doc_drift_fields check-envelope keys (issue #502) and
--diff-vs baseline selection and output protection (issue #403). Drives
the shell entry point with a fixture klt whose responses are scripted per
case; the repo's own latest committed signoff-baseline record supplies the
--check target (the fixture ignores it). Standard library only.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(__file__).resolve().parent / "signoff-report.sh"

# The fixture stands in for every klt invocation the runner makes. The
# --check envelope is fully scripted from the environment per test case, so
# the wrapper's envelope handling is what is under test, not klt.
FIXTURE_KLT = r'''#!/usr/bin/env python3
import json, os, sys

args = sys.argv[1:]
if args[:1] == ["version"]:
    print(json.dumps({
        "version": "0.9.3.selftest",
        "git_commit": "0000000000000000000000000000000000000000",
        "git_tag": None,
        "is_release": False,
        "grading_ruleset_id": "sha256:self-test",
    }))
    raise SystemExit(0)
if args[:1] == ["--help"]:
    print("usage: klt [--help] {version,signoff,...}  (signoff: grade/compare)")
    raise SystemExit(0)
if args[:1] == ["signoff"]:
    if "--check" in args:
        expected = os.environ.get("KLT_FIXTURE_CHECK_PATH")
        if expected and not os.path.samefile(expected, args[args.index("--check") + 1]):
            sys.exit("unexpected --check artifact")
        sys.stdout.write(os.environ["KLT_FIXTURE_CHECK_STDOUT"])
        raise SystemExit(int(os.environ.get("KLT_FIXTURE_CHECK_RC", "0")))
    sys.stdout.write(os.environ.get(
        "KLT_FIXTURE_RENDER_STDOUT",
        '{"schema_version": 1, "status": "self-test render", "items": []}'))
    raise SystemExit(int(os.environ.get("KLT_FIXTURE_RENDER_RC", "0")))
sys.stderr.write("klt fixture: unexpected argv %r\n" % (args,))
raise SystemExit(2)
'''

RENDER_REPORT = '{"schema_version": 1, "status": "self-test render", "items": []}'


def run_wrapper(envelope, check_rc, render_rc=0, *, args=("--check-latest",),
                script=SCRIPT, check_path=""):
    """Run the signoff wrapper against a scripted klt."""
    with tempfile.TemporaryDirectory() as d:
        klt = Path(d) / "klt-fixture"
        klt.write_text(FIXTURE_KLT)
        klt.chmod(0o755)
        env = dict(
            os.environ,
            KLT_BIN=str(klt),
            KLT_FIXTURE_CHECK_STDOUT=json.dumps(envelope),
            KLT_FIXTURE_CHECK_RC=str(check_rc),
            KLT_FIXTURE_CHECK_PATH=str(check_path),
            KLT_FIXTURE_RENDER_STDOUT=RENDER_REPORT,
            KLT_FIXTURE_RENDER_RC=str(render_rc),
        )
        return subprocess.run(
            [str(script), *map(str, args)],
            cwd=str(REPO_ROOT), env=env, capture_output=True,
            text=True, timeout=300)


class CheckLatestTests(unittest.TestCase):
    def assert_doc_entry(self, err, field, committed, fresh):
        self.assertIn(
            f"checklist wording moved: {field}: "
            f"committed={committed!r} fresh={fresh!r}", err)

    def test_doc_only_match_reports_every_entry_and_exits_zero(self):
        envelope = {
            "status": "match",
            "doc_drift": True,
            "doc_drift_fields": [
                {"field": "items.0.text",
                 "committed": "wording v1", "fresh": "wording v2"},
                {"field": "items.2.text",
                 "committed": "other v1", "fresh": "other v2"},
            ],
            "drift": [],
        }
        res = run_wrapper(envelope, check_rc=0)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("graded fields match", res.stderr)
        self.assertNotIn("-- no drift (", res.stderr)
        self.assertNotIn("drifted:", res.stderr)
        self.assert_doc_entry(res.stderr, "items.0.text", "wording v1", "wording v2")
        self.assert_doc_entry(res.stderr, "items.2.text", "other v1", "other v2")
        report = json.loads(res.stdout)
        self.assertEqual(report["status"], "self-test render")

    def test_mixed_drift_reports_both_categories_and_exits_one(self):
        envelope = {
            "status": "drifted",
            "doc_drift": True,
            "doc_drift_fields": [
                {"field": "items.0.text", "committed": "a", "fresh": "b"},
            ],
            "drift": [
                {"field": "t1_met_count", "committed": 1, "fresh": 2},
            ],
        }
        res = run_wrapper(envelope, check_rc=3)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("no longer reproduces", res.stderr)
        self.assertIn(
            "drifted: t1_met_count: committed=1 fresh=2", res.stderr)
        self.assert_doc_entry(res.stderr, "items.0.text", "a", "b")

    def test_graded_only_drift_without_optional_keys_keeps_diagnostic(self):
        envelope = {
            "status": "drifted",
            "drift": [
                {"field": "t1_met_count", "committed": 1, "fresh": 2},
            ],
        }
        res = run_wrapper(envelope, check_rc=3)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("no longer reproduces", res.stderr)
        self.assertIn(
            "drifted: t1_met_count: committed=1 fresh=2", res.stderr)
        self.assertNotIn("checklist wording moved", res.stderr)

    def test_clean_modern_match_with_empty_doc_fields(self):
        envelope = {
            "status": "match", "doc_drift": False,
            "doc_drift_fields": [], "drift": [],
        }
        res = run_wrapper(envelope, check_rc=0)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("-- no drift (", res.stderr)
        self.assertNotIn("checklist wording moved", res.stderr)
        self.assertEqual(json.loads(res.stdout)["status"], "self-test render")

    def test_legacy_match_without_optional_keys(self):
        envelope = {"status": "match", "drift": []}
        res = run_wrapper(envelope, check_rc=0)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("-- no drift (", res.stderr)
        self.assertNotIn("checklist wording moved", res.stderr)
        self.assertEqual(json.loads(res.stdout)["status"], "self-test render")

    def test_doc_drift_flag_without_field_details_still_acknowledged(self):
        envelope = {"status": "match", "doc_drift": True, "drift": []}
        res = run_wrapper(envelope, check_rc=0)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("graded fields match", res.stderr)
        self.assertNotIn("-- no drift (", res.stderr)
        self.assertIn(
            "checklist wording moved: grader set doc_drift "
            "but supplied no field details", res.stderr)


class ComparisonInputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        self.script = scripts / SCRIPT.name
        shutil.copy2(SCRIPT, self.script)
        shutil.copy2(SCRIPT.with_name("signoff_movement_diff.py"), scripts)
        baseline = self.root / "verification/records/signoff-baseline"
        self.record_id = "20261120-110738-b5f7c15"
        artifact_id = "20261119-090000-abcdef0"
        self.report = baseline / "artifacts" / artifact_id / "signoff-report.json"
        self.report.parent.mkdir(parents=True)
        self.original = b'{"items": [], "source_doc": "older checklist"}'
        self.report.write_bytes(self.original)
        records = baseline / "records"
        records.mkdir()
        (records / (self.record_id + ".md")).write_text(
            f"- **Links**: [Rendered verdict](../artifacts/{artifact_id}/signoff-report.json)\n")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)

    def invoke(self, *args):
        return run_wrapper({"status": "match"}, 0, args=args, script=self.script,
                           check_path=self.report)

    def test_record_id_and_default_compare_the_linked_shared_report(self):
        path = self.invoke("--diff-vs", self.report)
        self.assertEqual(path.returncode, 0, path.stderr)
        self.assertIn("moved source_doc: older checklist", path.stdout)
        for args in [("--diff-vs", self.record_id), ("--diff-vs",),
                     ("--check-latest", "--diff-vs")]:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, path.stdout)

    def test_distinct_output_receives_the_fresh_render(self):
        out = self.root / "new.json"
        result = self.invoke("--diff-vs", self.record_id, "--out", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("moved source_doc: older checklist", result.stdout)
        self.assertEqual(out.read_text(), RENDER_REPORT)
        self.assertEqual(self.report.read_bytes(), self.original)

    def test_out_cannot_overwrite_a_comparison_input(self):
        symlink = self.root / "report-symlink"
        symlink.symlink_to(self.report)
        hardlink = self.root / "report-hardlink"
        os.link(self.report, hardlink)
        for args, out in [(("--diff-vs", self.report), self.report),
                          (("--diff-vs", self.report), symlink),
                          (("--diff-vs", self.record_id), hardlink),
                          (("--check-latest",), hardlink)]:
            with self.subTest(args=args, out=out):
                result = self.invoke(*args, "--out", out)
                self.assertEqual(self.report.read_bytes(), self.original)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("--out", result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
