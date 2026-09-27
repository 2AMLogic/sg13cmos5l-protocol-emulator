#!/usr/bin/env python3
"""Assert that a cocotb JUnit summary (`test/results.xml`) actually passed.

Before this script existed, `package.json`'s `test` script ended in:

    ! grep -q failure results.xml

which is vacuous in **both** directions. cocotb writes the JUnit summary's
`<testsuite>` element with attributes such as `failures="0"`; the substring
`failure` is present inside that attribute *name* on every run, pass or fail,
so `grep -q failure` always matches and `!` always inverts it to exit 1 --
`npm run test` was red on every genuinely passing run. The same line has a
second hole: a missing `results.xml` (e.g. the simulator crashed before
writing one) makes `grep` exit 2, which `!` turns into exit 0 -- a crash
silently reported as a pass. See the issue this script closes for the full
diagnosis.

This script replaces that line with a real assertion on the XML, and treats
"the file is missing, empty, or does not parse" as a FAILURE, never a pass.

**Two on-disk shapes are both accepted**, because they come from different
cocotb releases actually seen in this repo: `test/requirements.txt` pins
`cocotb==2.0.1`, whose JUnit writer does *not* emit `failures=`/`errors=`
attributes on `<testsuite>` -- it marks a failing `<testcase>` with a nested
`<failure .../>` (or `<error .../>`) element instead. Later cocotb (the issue
cites 2.1.0) adds the summary attributes the issue describes. Rather than
assume one shape and be wrong about whichever cocotb happens to be installed,
this script sums *both* signals per `<testsuite>`: the `failures=`/`errors=`
attribute when present, and a count of `<testcase>` children carrying a
`<failure>`/`<error>` element. Either signal reporting a nonzero count fails
the run.

Zero dependencies beyond the Python 3 standard library (`xml.etree.ElementTree`).

Usage:
    python3 scripts/check_test_results.py [path/to/results.xml]

    Default path: test/results.xml, resolved relative to the repository root
    (the parent of this script's directory), not the current working
    directory -- so this runs the same way from `npm run test` (cwd `test/`)
    or from the repo root.

Exit codes: 0 the run passed (file present, parses, zero failures/errors
across every `<testsuite>`); 1 otherwise (missing file, unparseable XML, no
`<testsuite>` element found, or a nonzero failure/error count).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_PATH = "test/results.xml"


class ResultsError(Exception):
    """The results file is missing, unparseable, or structurally empty."""


def _int_attr(element: ET.Element, name: str) -> int | None:
    """Return `element`'s integer attribute `name`, or None if absent.

    Raises ResultsError if the attribute is present but not an integer --
    a malformed attribute is a reason to fail, not to silently ignore it.
    """
    raw = element.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ResultsError(
            f"<testsuite> attribute {name}={raw!r} is not an integer"
        ) from exc


def _counted_children(testcase: ET.Element, tag: str) -> int:
    return len(testcase.findall(tag))


def evaluate_testsuite(testsuite: ET.Element) -> tuple[int, int]:
    """Return (failures, errors) for one `<testsuite>` element.

    Prefers the `failures=`/`errors=` summary attribute when present (cocotb
    2.1.0+ shape); otherwise falls back to counting `<testcase>` children
    that carry a nested `<failure>`/`<error>` element (cocotb 2.0.1 shape,
    also the JUnit-standard way a per-test failure is actually recorded).
    """
    attr_failures = _int_attr(testsuite, "failures")
    attr_errors = _int_attr(testsuite, "errors")

    testcases = testsuite.findall("testcase")
    child_failures = sum(_counted_children(tc, "failure") for tc in testcases)
    child_errors = sum(_counted_children(tc, "error") for tc in testcases)

    failures = attr_failures if attr_failures is not None else child_failures
    errors = attr_errors if attr_errors is not None else child_errors
    return failures, errors


def evaluate(xml_text: str) -> tuple[bool, list[str]]:
    """Return (passed, report_lines) for the JUnit XML text `xml_text`.

    Raises ResultsError for input that cannot be evaluated at all (does not
    parse, or contains no `<testsuite>` element) -- callers must treat that
    as a failure, not skip the check.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ResultsError(f"results.xml is not well-formed XML: {exc}") from exc

    if root.tag == "testsuite":
        testsuites = [root]
    else:
        testsuites = root.findall(".//testsuite")

    if not testsuites:
        raise ResultsError("no <testsuite> element found in results.xml")

    lines = []
    total_failures = 0
    total_errors = 0
    for suite in testsuites:
        failures, errors = evaluate_testsuite(suite)
        total_failures += failures
        total_errors += errors
        name = suite.get("name", "<unnamed>")
        lines.append(f"  testsuite {name!r}: failures={failures} errors={errors}")

    passed = total_failures == 0 and total_errors == 0
    lines.append(f"  total: failures={total_failures} errors={total_errors}")
    return passed, lines


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: check_test_results.py [path/to/results.xml]", file=sys.stderr)
        return 2

    if args:
        path = Path(args[0])
        if not path.is_absolute():
            path = Path.cwd() / path
    else:
        path = REPO_ROOT / DEFAULT_RESULTS_PATH

    if not path.is_file():
        print(f"FAIL: {path} does not exist (no test results to check -- treating as a failure)")
        return 1

    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ResultsError("results.xml is empty")
        passed, lines = evaluate(text)
    except ResultsError as exc:
        print(f"FAIL: {path}: {exc}")
        return 1

    for line in lines:
        print(line)

    if passed:
        print(f"PASS: {path} reports zero failures and zero errors")
        return 0

    print(f"FAIL: {path} reports at least one failure or error")
    return 1


if __name__ == "__main__":
    sys.exit(main())
