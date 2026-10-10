#!/usr/bin/env python3
"""Self-test for `verification/remint_records.py` (#193).

Builds a throwaway git repo (reusing `test_check_records.py`'s fixture
helpers), copies the real tool in, and runs it as a subprocess. The re-run
path uses a stub `klt` (a shell script emitting a canned envelope) so no
simulator runs. Also confirms a re-minted record passes the real linter and
that the old record's bytes are untouched.

Usage: python3 verification/test_remint_records.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import test_check_records as T

TOOL = T.SCRIPT_DIR / "remint_records.py"
REQ = "verification/request-demo.json"
OLD_ID = "20260101-000000-abc1234"
NEW_RTL = T.DUMMY_RTL + "// changed\n"

STUB_PASS = """#!/bin/sh
case "$1" in --version) echo "klt 9.9.9"; exit 0;; esac
echo '{"status":"pass","engine":"icarus","test_count":2,"passed_count":2,"environment":{}}'
"""
STUB_FAIL = STUB_PASS.replace('"pass"', '"fail"')


def build(tmp: Path, with_request: bool = True) -> Path:
    repo = tmp / "fixture"
    (repo / "rtl").mkdir(parents=True)
    (repo / "verification" / "records" / "demo" / "records").mkdir(parents=True)
    (repo / "rtl" / "dut.v").write_text(T.DUMMY_RTL, encoding="utf-8")
    req = '{"schema": "demo"}\n'
    inputs = [("rtl/dut.v", T._sha256_text(T.DUMMY_RTL))]
    if with_request:
        (repo / REQ).write_text(req, encoding="utf-8")
        inputs.append((REQ, T._sha256_text(req)))
    for name in ("check_records.py", "_repo_utils.py", "remint_records.py"):
        shutil.copyfile(T.SCRIPT_DIR / name, repo / "verification" / name)
    T.record_path(repo, "demo", OLD_ID).write_text(
        T.make_record(OLD_ID, "demo", inputs=inputs), encoding="utf-8")
    stub = repo / "klt-stub"
    stub.write_text(STUB_PASS, encoding="utf-8")
    stub.chmod(0o755)
    T._git(repo, "init", "--quiet")
    T._git(repo, "add", "-A")
    T._git(repo, "commit", "--quiet", "-m", "fixture")
    T._git(repo, "update-ref", T.BASE_REF, "HEAD")
    return repo


STUB_XML = """#!/bin/sh
case "$1" in --version) echo "klt 9.9.9"; exit 0;; esac
mkdir -p verification/.klt
X="$PWD/verification/.klt/results.xml"
printf 'xml-for-%s' "$(basename "$2" .json)" > "$X"
echo '{"status":"pass","engine":"icarus","test_count":1,"passed_count":1,"environment":{"results_xml":"'"$X"'"}}'
"""


def build_multi(tmp: Path) -> Path:
    """Experiment `demo` has TWO live stale records (both hash request-a);
    experiment `multi` has one record hashing request-a AND request-b. All
    requests share one results_xml path (as klt does)."""
    repo = tmp / "fixture"
    (repo / "rtl").mkdir(parents=True)
    (repo / "rtl" / "dut.v").write_text(T.DUMMY_RTL, encoding="utf-8")
    reqs = {}
    for n in ("a", "b"):
        rel = f"verification/request-{n}.json"
        text = f'{{"schema": "{n}"}}\n'
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
        reqs[n] = (rel, T._sha256_text(text))
    rtl = ("rtl/dut.v", T._sha256_text(T.DUMMY_RTL))
    for name in ("check_records.py", "_repo_utils.py", "remint_records.py"):
        shutil.copyfile(T.SCRIPT_DIR / name, repo / "verification" / name)
    plan = [("demo", OLD_ID, ["a"]), ("demo", "20260101-000005-abc1234", ["a"]),
            ("multi", OLD_ID, ["a", "b"])]
    for exp, rid, ns in plan:
        T.record_path(repo, exp, rid).parent.mkdir(parents=True, exist_ok=True)
        T.record_path(repo, exp, rid).write_text(
            T.make_record(rid, exp, inputs=[rtl, *[reqs[n] for n in ns]]), encoding="utf-8")
    stub = repo / "klt-stub"
    stub.write_text(STUB_XML, encoding="utf-8")
    stub.chmod(0o755)
    T._git(repo, "init", "--quiet")
    T._git(repo, "add", "-A")
    T._git(repo, "commit", "--quiet", "-m", "fixture")
    T._git(repo, "update-ref", T.BASE_REF, "HEAD")
    return repo


def stale(repo: Path) -> None:
    (repo / "rtl" / "dut.v").write_text(NEW_RTL, encoding="utf-8")
    T._git(repo, "add", "-A")
    T._git(repo, "commit", "--quiet", "-m", "change rtl")


def tool(repo: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(repo / "verification" / "remint_records.py"), *args],
                       cwd=repo, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def records(repo: Path) -> list[str]:
    return sorted(p.stem for p in (repo / "verification/records/demo/records").glob("*.md"))


def check(name: str, ok: bool, out: str, failures: list) -> None:
    print(("OK:   " if ok else "FAIL: ") + name)
    if not ok:
        failures.append(name)
        print("  | " + out.replace("\n", "\n  | "))


def main() -> int:
    failures: list = []
    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        code, out = tool(repo)
        check("fresh tree reports nothing, exit 0", code == 0 and "no stale" in out, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        stale(repo)
        code, out = tool(repo)
        check("stale input reported with request, exit 1",
              code == 1 and "STALE" in out and "rtl/dut.v" in out
              and f"request(s): {REQ}" in out and "rtl/dut.v: recorded" in out, out, failures)
        check("report-only mints nothing", records(repo) == [OLD_ID], out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d), with_request=False)
        stale(repo)
        code, out = tool(repo)
        check("record with no request file says re-mint by hand",
              code == 1 and "no request file" in out, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        # Superseded records are exempt: add a fresh superseding record first.
        stale(repo)
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"))
        old = T.record_path(repo, "demo", OLD_ID)
        before = old.read_text(encoding="utf-8")
        new = [r for r in records(repo) if r != OLD_ID]
        check("--rerun mints exactly one superseding record",
              len(new) == 1 and "MINTED" in out, out, failures)
        if new:
            text = T.record_path(repo, "demo", new[0]).read_text(encoding="utf-8")
            check("new record supersedes old, rehashed, artifacts written",
                  f'"supersedes": "{OLD_ID}"' in text and T._sha256_text(NEW_RTL) in text
                  and (repo / "verification/records/demo/artifacts" / new[0]
                       / "klt-functional-verification.json").is_file()
                  and '"klt_version": "9.9.9"' in text, text, failures)
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "remint")
            r = subprocess.run([sys.executable, str(repo / "verification/check_records.py"),
                                "--base-ref", T.BASE_REF, "--require-append-only"],
                               cwd=repo, capture_output=True, text=True)
            check("re-minted tree passes the real linter (old record untouched)",
                  r.returncode == 0 and old.read_text(encoding="utf-8") == before,
                  r.stdout + r.stderr, failures)
            code, out = tool(repo)
            check("after re-mint nothing is stale", code == 0, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        stale(repo)
        (repo / "klt-stub").write_text(STUB_FAIL, encoding="utf-8")
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"))
        check("failing request mints nothing, exit 1",
              code == 1 and records(repo) == [OLD_ID] and "no record minted" in out, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build_multi(Path(d))
        stale(repo)
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"))
        check("multi: rerun succeeds", code == 0, out, failures)
        recs = repo / "verification/records"
        demo_new = sorted(p.stem for p in (recs / "demo/records").glob("*.md")
                          if p.stem not in (OLD_ID, "20260101-000005-abc1234"))
        check("two stale records in one experiment each get a distinct new record",
              len(demo_new) == 2 and len(set(demo_new)) == 2
              and demo_new[0] > "20260101-000005-abc1234", out, failures)
        for new in demo_new:
            xml = recs / "demo/artifacts" / new / "results_icarus.xml"
            check(f"cached reuse keeps request-a XML ({new})",
                  xml.is_file() and xml.read_text() == "xml-for-request-a", out, failures)
        multi_new = [p.stem for p in (recs / "multi/records").glob("*.md") if p.stem != OLD_ID]
        check("multi-request experiment minted one record", len(multi_new) == 1, out, failures)
        if multi_new:
            art = recs / "multi/artifacts" / multi_new[0]
            for n in ("a", "b"):
                f = art / f"results_icarus-{n}.xml"
                check(f"multi-request record keeps request-{n} XML",
                      f.is_file() and f.read_text() == f"xml-for-request-{n}", out, failures)
        T._git(repo, "add", "-A")
        T._git(repo, "commit", "--quiet", "-m", "remint")
        r = subprocess.run([sys.executable, str(repo / "verification/check_records.py"),
                            "--base-ref", T.BASE_REF, "--require-append-only"],
                           cwd=repo, capture_output=True, text=True)
        check("multi: both stale records superseded and tree passes check_records",
              r.returncode == 0, r.stdout + r.stderr, failures)
        code, out = tool(repo)
        check("multi: nothing stale afterwards", code == 0, out, failures)

    print()
    if failures:
        print(f"FAIL: {len(failures)} case(s)")
        return 1
    print("PASS: all remint_records cases behaved as specified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
