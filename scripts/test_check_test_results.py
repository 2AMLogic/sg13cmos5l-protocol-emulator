#!/usr/bin/env python3
"""Self-test for `scripts/check_test_results.py`.

`npm run test` (half of `npm run check:ci`, this repo's own build gate) is
only as trustworthy as this script's ability to tell a passing cocotb run
from a failing one -- exactly the property the line it replaced
(`! grep -q failure results.xml`) never had, in either direction (see the
script's own docstring and the issue it closes). Each fixture case below is
one required distinction from the issue's minimum test list: a genuine
failure, a genuine pass, and a missing file -- plus the fail-closed cases
from issue #215: a zero summary attribute contradicting a nested
failure/error, a zero-test or fully skipped run, and a negative counter.

Method (the same shape as `verification/test_check_records.py` and
`scripts/test_check_ratification_gate.py`): write a fixture `results.xml` to
a temp dir and run the *real* shipped script as a subprocess against it.
Nothing is monkeypatched or mocked.

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 scripts/test_check_test_results.py
Exit codes: 0 all cases behave as specified, 1 at least one did not.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CHECKER = SCRIPT_DIR / "check_test_results.py"

# --------------------------------------------------------------- fixture XML

#: A wholly passing run, cocotb 2.1.0+ shape: the summary attributes are
#: present on <testsuite> and both read zero.
PASSING_ATTRIBUTE_SHAPE = """<testsuites name="results">
  <testsuite name="all" package="all" tests="1" failures="0" errors="0" skipped="0">
    <testcase name="test_project" classname="test" time="0.01" />
  </testsuite>
</testsuites>
"""

#: A failing run, cocotb 2.1.0+ shape: failures="1" is the exact attribute
#: name substring-matched (wrongly) by the line this script replaces.
FAILING_ATTRIBUTE_SHAPE = """<testsuites name="results">
  <testsuite name="all" package="all" tests="1" failures="1" errors="0" skipped="0">
    <testcase name="test_project" classname="test" time="0.01">
      <failure error_type="AssertionError" error_msg="boom" />
    </testcase>
  </testsuite>
</testsuites>
"""

#: A wholly passing run, cocotb 2.0.1 shape (this repo's pinned version, per
#: `test/requirements.txt`): no failures=/errors= summary attribute at all.
PASSING_NO_ATTRIBUTE_SHAPE = """<testsuites name="results">
  <testsuite name="all" package="all">
    <property name="random_seed" value="123" />
    <testcase name="test_project" classname="test" file="test.py" lineno="24" time="0.01" />
  </testsuite>
</testsuites>
"""

#: A failing run, cocotb 2.0.1 shape: no summary attribute, but the failing
#: <testcase> carries a nested <failure> element -- the actual live signal
#: this repo's pinned cocotb writes today (verified against a real run).
FAILING_NO_ATTRIBUTE_SHAPE = """<testsuites name="results">
  <testsuite name="all" package="all">
    <testcase name="test_project" classname="test" time="0.01" />
    <testcase name="test_force_failure" classname="test" time="0.02">
      <failure error_type="AssertionError" error_msg="forced failure" />
    </testcase>
  </testsuite>
</testsuites>
"""

#: An errors="…" (not failures) count must also fail -- errors and failures
#: are independent JUnit fields, both gate the run.
ERROR_ONLY_SHAPE = """<testsuites name="results">
  <testsuite name="all" package="all" tests="1" failures="0" errors="1" skipped="0">
    <testcase name="test_project" classname="test" time="0.01">
      <error error_type="SimulatorCrash" error_msg="boom" />
    </testcase>
  </testsuite>
</testsuites>
"""

#: Two <testsuite> elements: only the second has a failure. The check must
#: look at every testsuite, not just the first.
MULTI_SUITE_ONE_FAILS = """<testsuites name="results">
  <testsuite name="all" tests="1" failures="0" errors="0">
    <testcase name="a" classname="test" time="0.01" />
  </testsuite>
  <testsuite name="other" tests="1" failures="1" errors="0">
    <testcase name="b" classname="test" time="0.01">
      <failure error_type="AssertionError" error_msg="boom" />
    </testcase>
  </testsuite>
</testsuites>
"""

TRUNCATED_XML = """<testsuites name="results">
  <testsuite name="all" package="all" tests="1" failures="0" errors="0">
    <testcase name="test_project" classname="test" time="0.01" />
"""

EMPTY_TESTSUITES = """<testsuites name="results">
</testsuites>
"""

#: Contradictory summary: errors="0" on the suite, but the testcase carries a
#: nested <error>. The nested signal must not be hidden by the zero attribute.
CONTRADICTORY_ERRORS_ATTR = """<testsuite tests="1" failures="0" errors="0"><testcase name="crashed"><error message="crash"/></testcase></testsuite>
"""

#: Same contradiction on the failures axis.
CONTRADICTORY_FAILURES_ATTR = """<testsuites name="results">
  <testsuite name="all" tests="2" failures="0" errors="0" skipped="0">
    <testcase name="a" classname="test" time="0.01" />
    <testcase name="b" classname="test" time="0.01">
      <failure error_type="AssertionError" error_msg="boom" />
    </testcase>
  </testsuite>
</testsuites>
"""

#: A zero-test suite: all counters zero, no testcases. Nothing ran.
ZERO_TEST_SUITE = """<testsuite tests="0" failures="0" errors="0"/>
"""

#: Every testcase skipped: nothing was executed, so nothing was demonstrated.
ALL_SKIPPED = """<testsuites name="results">
  <testsuite name="all" tests="2" failures="0" errors="0" skipped="2">
    <testcase name="a" classname="test" time="0.0"><skipped /></testcase>
    <testcase name="b" classname="test" time="0.0"><skipped /></testcase>
  </testsuite>
</testsuites>
"""

#: A negative counter is malformed and must fail, not be summed into a total
#: that could cancel a real failure elsewhere.
NEGATIVE_FAILURES = """<testsuites name="results">
  <testsuite name="all" tests="1" failures="-1" errors="0">
    <testcase name="a" classname="test" time="0.01" />
  </testsuite>
</testsuites>
"""

NEGATIVE_TESTS = """<testsuites name="results">
  <testsuite name="all" tests="-1" failures="0" errors="0">
    <testcase name="a" classname="test" time="0.01" />
  </testsuite>
</testsuites>
"""

#: An empty auxiliary suite alongside a suite with an executed, passing case
#: (and one skipped case) is a legitimate pass.
MULTI_SUITE_WITH_EMPTY_AUXILIARY = """<testsuites name="results">
  <testsuite name="aux" tests="0" failures="0" errors="0" />
  <testsuite name="all" tests="2" failures="0" errors="0" skipped="1">
    <testcase name="a" classname="test" time="0.01" />
    <testcase name="b" classname="test" time="0.0"><skipped /></testcase>
  </testsuite>
</testsuites>
"""


def _run(results_xml: str | None, *, missing: bool = False, args: tuple[str, ...] = ()):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "results.xml"
        if not missing:
            path.write_text(results_xml or "", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(CHECKER), *(args or (str(path),))],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout + result.stderr


# --------------------------------------------------------------------- cases


def case_passing_attribute_shape() -> tuple[bool, str]:
    code, out = _run(PASSING_ATTRIBUTE_SHAPE)
    return (code == 0 and "PASS" in out), out


def case_failing_attribute_shape() -> tuple[bool, str]:
    """The issue's own minimum fixture: failures="1" must fail."""
    code, out = _run(FAILING_ATTRIBUTE_SHAPE)
    return (code == 1 and "FAIL" in out and "failures=1" in out), out


def case_passing_no_attribute_shape() -> tuple[bool, str]:
    """The issue's own minimum fixture: failures="0" errors="0" must pass.

    Also exercises this repo's actually-installed cocotb 2.0.1 shape, which
    carries no summary attribute at all.
    """
    code, out = _run(PASSING_NO_ATTRIBUTE_SHAPE)
    return (code == 0 and "PASS" in out), out


def case_failing_no_attribute_shape() -> tuple[bool, str]:
    """A failure recorded only via a nested <failure> element (no summary
    attribute) must still be caught -- the fallback signal is load-bearing,
    not decorative, for this repo's pinned cocotb version."""
    code, out = _run(FAILING_NO_ATTRIBUTE_SHAPE)
    return (code == 1 and "FAIL" in out and "failures=1" in out), out


def case_error_only_shape() -> tuple[bool, str]:
    """errors="1" with failures="0" must still fail -- both fields gate."""
    code, out = _run(ERROR_ONLY_SHAPE)
    return (code == 1 and "FAIL" in out and "errors=1" in out), out


def case_multi_suite_one_fails() -> tuple[bool, str]:
    code, out = _run(MULTI_SUITE_ONE_FAILS)
    return (code == 1 and "FAIL" in out and "total: failures=1" in out), out


def case_missing_file() -> tuple[bool, str]:
    """The issue's own minimum fixture: a missing results.xml must fail.

    This is the second bug on the original line: `grep` on a missing file
    exits 2, which `! grep ...` silently turned into exit 0 (a pass).
    """
    code, out = _run(None, missing=True)
    return (code == 1 and "FAIL" in out and "does not exist" in out), out


def case_empty_file() -> tuple[bool, str]:
    code, out = _run("")
    return (code == 1 and "FAIL" in out), out


def case_truncated_xml() -> tuple[bool, str]:
    """A crashed simulator can leave a partially-written file -- unparseable
    XML must fail, not be silently treated as a pass."""
    code, out = _run(TRUNCATED_XML)
    return (code == 1 and "FAIL" in out), out


def case_no_testsuite_element() -> tuple[bool, str]:
    code, out = _run("<notjunit/>\n")
    return (code == 1 and "FAIL" in out and "no <testsuite>" in out), out


def case_empty_testsuites_root() -> tuple[bool, str]:
    """A <testsuites> root with zero <testsuite> children is structurally
    empty and must fail, not silently pass because nothing counted a
    failure."""
    code, out = _run(EMPTY_TESTSUITES)
    return (code == 1 and "FAIL" in out and "no <testsuite>" in out), out


def case_contradictory_errors_attr_fails() -> tuple[bool, str]:
    """errors="0" cannot hide a nested <error> element (issue #215)."""
    code, out = _run(CONTRADICTORY_ERRORS_ATTR)
    return (code == 1 and "FAIL" in out and "total: failures=0 errors=1" in out), out


def case_contradictory_failures_attr_fails() -> tuple[bool, str]:
    """failures="0" cannot hide a nested <failure> element (issue #215)."""
    code, out = _run(CONTRADICTORY_FAILURES_ATTR)
    return (code == 1 and "FAIL" in out and "total: failures=1 errors=0" in out), out


def case_zero_test_suite_fails() -> tuple[bool, str]:
    """A suite with zero counters and no testcases ran nothing (issue #215)."""
    code, out = _run(ZERO_TEST_SUITE)
    return (code == 1 and "FAIL" in out and "no executed" in out), out


def case_all_skipped_fails() -> tuple[bool, str]:
    """A run whose every testcase was skipped demonstrates nothing."""
    code, out = _run(ALL_SKIPPED)
    return (code == 1 and "FAIL" in out and "no executed" in out), out


def case_negative_failures_counter_fails() -> tuple[bool, str]:
    code, out = _run(NEGATIVE_FAILURES)
    return (code == 1 and "FAIL" in out and "negative" in out), out


def case_negative_tests_counter_fails() -> tuple[bool, str]:
    code, out = _run(NEGATIVE_TESTS)
    return (code == 1 and "FAIL" in out and "negative" in out), out


def case_multi_suite_with_empty_auxiliary_passes() -> tuple[bool, str]:
    """An empty auxiliary suite is fine when another suite executed a
    passing testcase; skipped cases do not count as executed."""
    code, out = _run(MULTI_SUITE_WITH_EMPTY_AUXILIARY)
    return (code == 0 and "PASS" in out and "executed=1" in out), out


def case_too_many_arguments_is_a_usage_error() -> tuple[bool, str]:
    """More than one positional argument is a usage error (exit 2), distinct
    from a check failure (exit 1)."""
    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "/definitely/does/not/exist/results.xml",
            "extra-argument",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.returncode == 2), result.stdout + result.stderr


def case_default_path_resolves_to_repo_root() -> tuple[bool, str]:
    """No path argument resolves to `<repo root>/test/results.xml` -- not
    `<cwd>/test/results.xml` -- so the script behaves the same whether
    invoked from `npm run test` (cwd `test/`) or from the repo root."""
    repo_root = CHECKER.resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(CHECKER)],
        capture_output=True,
        text=True,
        check=False,
        cwd=tempfile.gettempdir(),  # a cwd with no test/results.xml of its own
    )
    expected_path = str(repo_root / "test" / "results.xml")
    return (expected_path in result.stdout), result.stdout + result.stderr


CASES = (
    case_passing_attribute_shape,
    case_failing_attribute_shape,
    case_passing_no_attribute_shape,
    case_failing_no_attribute_shape,
    case_error_only_shape,
    case_multi_suite_one_fails,
    case_missing_file,
    case_empty_file,
    case_truncated_xml,
    case_no_testsuite_element,
    case_empty_testsuites_root,
    case_contradictory_errors_attr_fails,
    case_contradictory_failures_attr_fails,
    case_zero_test_suite_fails,
    case_all_skipped_fails,
    case_negative_failures_counter_fails,
    case_negative_tests_counter_fails,
    case_multi_suite_with_empty_auxiliary_passes,
    case_too_many_arguments_is_a_usage_error,
    case_default_path_resolves_to_repo_root,
)


def main() -> int:
    if not CHECKER.exists():
        print(f"FATAL: {CHECKER} not found", file=sys.stderr)
        return 1

    print(f"== check_test_results.py self-test ({len(CASES)} cases) ==")
    failures = 0
    for case in CASES:
        try:
            ok, detail = case()
        except Exception as exc:  # noqa: BLE001 -- report, don't abort the suite
            ok, detail = False, f"raised {type(exc).__name__}: {exc}"
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case.__name__}")
        if not ok:
            failures += 1
            print("        " + detail.replace("\n", "\n        "))

    print()
    if failures:
        print(f"FAIL: {failures}/{len(CASES)} self-test case(s) did not behave as specified")
        return 1
    print(f"PASS: all {len(CASES)} self-test cases behaved as specified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
