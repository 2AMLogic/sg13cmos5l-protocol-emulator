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

import datetime as datetime_mod
import os
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
# Like STUB_PASS, plus a minimal `klt artifact put` that writes a manifest.
STUB_STORE = STUB_PASS.replace(
    'echo \'{"status"',
    '''if [ "$1" = artifact ]; then
  [ "$2" = put ] && [ "$3" = --help ] && exit 0
  M="$4"; shift 6
  printf '{"schema_version":1,"entries":[' > "$M"; sep=""
  for f in "$@"; do
    printf '%s{"sha256":"%064d","size":3,"kind":"evidence","name":"%s","uri":"artifact:evidence/x/00/%064d"}' "$sep" 7 "$f" 7 >> "$M"; sep=","
  done
  printf ']}' >> "$M"; exit 0
fi
echo \'{"status"''')
STUB_FAIL = STUB_PASS.replace('"pass"', '"fail"')


def stub_with_results(env_results: str, create: bool = True) -> str:
    """A klt stub whose envelope reports `env_results` verbatim as
    `environment.results_xml` (a `{path, scope, sha256}` document or a
    legacy bare string, #552). With `create`, writes the repo-relative XML
    first; the stub runs with cwd=REPO_ROOT, as the real tool invokes it."""
    write = ""
    if create:
        write = ("mkdir -p verification/.klt\n"
                 "printf 'xml-doc-for-%s' \"$(basename \"$2\" .json)\""
                 " > verification/.klt/results.xml\n")
    return ("#!/bin/sh\n"
            "case \"$1\" in --version) echo \"klt 9.9.9\"; exit 0;; esac\n"
            + write
            + "echo '{\"status\":\"pass\",\"engine\":\"icarus\",\"test_count\":1,"
              "\"passed_count\":1,\"environment\":{\"results_xml\":" + env_results + "}}'\n")


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
    for name in ("check_records.py", "_repo_utils.py", "remint_records.py", "artifact_store.py"):
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


# --- #472: --collapse ---------------------------------------------------------


def build_collapsible(tmp: Path, leaves: int = 2, claim_vary: bool = False,
                      with_request: bool = False) -> Path:
    """Experiment `signoff-baseline` with N interchangeable live leaves
    (identical inputs, claim and result), optionally hashing a request
    file, optionally one leaf asserting a different claim."""
    repo = tmp / "fixture"
    (repo / "rtl").mkdir(parents=True)
    (repo / "verification" / "records" / "signoff-baseline" / "records").mkdir(parents=True)
    (repo / "rtl" / "dut.v").write_text(T.DUMMY_RTL, encoding="utf-8")
    inputs = [("rtl/dut.v", T._sha256_text(T.DUMMY_RTL))]
    if with_request:
        (repo / REQ).write_text('{"schema": "demo"}\n', encoding="utf-8")
        inputs.append((REQ, T._sha256_text('{"schema": "demo"}\n')))
    for name in ("check_records.py", "_repo_utils.py", "remint_records.py"):
        shutil.copyfile(T.SCRIPT_DIR / name, repo / "verification" / name)
    for i in range(leaves):
        rid = f"20260101-{i:06d}-abc1234"
        text = T.make_record(rid, "signoff-baseline", inputs=inputs)
        if claim_vary and i == 1:
            text = text.replace("fixture claim", "a different claim")
        T.record_path(repo, "signoff-baseline", rid).write_text(text, encoding="utf-8")
    T._git(repo, "init", "--quiet")
    T._git(repo, "add", "-A")
    T._git(repo, "commit", "--quiet", "-m", "fixture")
    T._git(repo, "update-ref", T.BASE_REF, "HEAD")
    return repo


def baseline_records(repo: Path) -> list[str]:
    return sorted(
        p.stem
        for p in (repo / "verification/records/signoff-baseline/records").glob("*.md")
    )


LEAF_IDS = ["20260101-000000-abc1234", "20260101-000001-abc1234"]


def collapse_cases(failures: list) -> None:
    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d))
        code, out = tool(repo, "--collapse", "demo")
        check("--collapse refuses a non-interchangeable experiment",
              code == 1 and "refuses" in out and "--rerun" not in out.splitlines()[0]
              and baseline_records(repo) == LEAF_IDS, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d))
        code, out = tool(repo, "--collapse", "signoff-baseline")
        check("--collapse with nothing stale mints nothing",
              code == 0 and "nothing to collapse" in out
              and baseline_records(repo) == LEAF_IDS, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d), with_request=True)
        stale(repo)
        code, out = tool(repo, "--collapse", "signoff-baseline")
        check("--collapse refuses stale leaves that hash request files",
              code == 1 and "--rerun" in out
              and baseline_records(repo) == LEAF_IDS, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d), claim_vary=True)
        stale(repo)
        code, out = tool(repo, "--collapse", "signoff-baseline")
        check("--collapse refuses leaves with differing claims",
              code == 1 and "not interchangeable" in out
              and baseline_records(repo) == LEAF_IDS, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d))
        stale(repo)
        code, out = tool(repo, "--collapse", "signoff-baseline", "--rerun")
        check("--collapse and --rerun are mutually exclusive",
              code == 2 and "mutually exclusive" in out, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d))
        stale(repo)
        olds = {rid: T.record_path(repo, "signoff-baseline", rid).read_text(encoding="utf-8")
                for rid in LEAF_IDS}
        code, out = tool(repo, "--collapse", "signoff-baseline")
        new = [r for r in baseline_records(repo) if r not in LEAF_IDS]
        check("--collapse mints exactly one record for two stale leaves",
              code == 0 and len(new) == 1 and "MINTED" in out
              and "collapses 2 stale live leaves" in out, out, failures)
        if new:
            text = T.record_path(repo, "signoff-baseline", new[0]).read_text(encoding="utf-8")
            check("collapsed record's supersedes lists both leaves",
                  f'"supersedes": [\n    "{LEAF_IDS[0]}",\n    "{LEAF_IDS[1]}"\n  ]' in text
                  and T._sha256_text(NEW_RTL) in text, text, failures)
            check("collapsed record fails closed on the Result/Run configuration placeholders",
                  "- **Result**: (fill in)" in text
                  and "- **Run configuration**: (fill in)" in text
                  and "no run was performed" in text, text, failures)
            check("old leaves are byte-identical (append-only)",
                  all(T.record_path(repo, "signoff-baseline", r).read_text(encoding="utf-8") == olds[r]
                      for r in LEAF_IDS), "", failures)
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "collapse mint")
            r = subprocess.run([sys.executable, str(repo / "verification" / "check_records.py"),
                                "--base-ref", T.BASE_REF, "--require-append-only"],
                               cwd=repo, capture_output=True, text=True)
            check("linter rejects the collapse mint until the placeholders are filled",
                  r.returncode == 1 and "empty/placeholder" in r.stdout
                  and "`Result`" in r.stdout and "`Run configuration`" in r.stdout,
                  r.stdout, failures)
            filled = (text
                      .replace("- **Result**: (fill in)",
                               "- **Result**: **Overall: PASS** (re-run by hand)")
                      .replace("- **Run configuration**: (fill in)",
                               "- **Run configuration**: re-run by hand")
                      .replace("- **Design provenance**: (fill in)",
                               "- **Design provenance**: rtl re-run by hand"))
            T.record_path(repo, "signoff-baseline", new[0]).write_text(filled, encoding="utf-8")
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "fill the placeholders")
            r = subprocess.run([sys.executable, str(repo / "verification" / "check_records.py"),
                                "--base-ref", T.BASE_REF, "--require-append-only"],
                               cwd=repo, capture_output=True, text=True)
            check("filled collapse mint passes the real linter", r.returncode == 0,
                  r.stdout, failures)
            # Exactly one live record remains: the next change stales one record.
            (repo / "rtl" / "dut.v").write_text(NEW_RTL + "// v3\n", encoding="utf-8")
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "v3")
            code, out = tool(repo)
            stale_lines = [l for l in out.splitlines() if l.startswith("STALE")]
            check("two leaves collapsed to one live record",
                  code == 1 and stale_lines == [
                      f"STALE: verification/records/signoff-baseline/records/{new[0]}.md"
                  ], out, failures)


def wrapped_result(text: str, verdict: str, indent: str) -> str:
    """Give a leaf's Result a first line shared by every leaf and a wrapped
    continuation (indented or flush-left) that carries the verdict."""
    return text.replace(
        "- **Result**: **Overall: PASS** (fixture)",
        f"- **Result**: Item 9 status\n{indent}{verdict} (wrapped)",
    ).replace(
        "- **Run configuration**: fixture run, no real simulator invoked",
        f"- **Run configuration**: fixture run\n{indent}run configuration tail",
    )


def collapse_wrapped_cases(failures: list) -> None:
    for label, indent in (("indented", "  "), ("flush-left", "")):
        with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
            repo = build_collapsible(Path(d))
            for rid, verdict in zip(LEAF_IDS, ("PASS", "FAIL")):
                p = T.record_path(repo, "signoff-baseline", rid)
                p.write_text(wrapped_result(p.read_text(encoding="utf-8"), verdict, indent),
                             encoding="utf-8")
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "wrap")
            stale(repo)
            code, out = tool(repo, "--collapse", "signoff-baseline")
            check(f"--collapse refuses leaves whose {label} Result continuations differ",
                  code == 1 and "not interchangeable" in out
                  and baseline_records(repo) == LEAF_IDS, out, failures)

        with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
            repo = build_collapsible(Path(d))
            for rid in LEAF_IDS:
                p = T.record_path(repo, "signoff-baseline", rid)
                p.write_text(wrapped_result(p.read_text(encoding="utf-8"), "PASS", indent),
                             encoding="utf-8")
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "wrap")
            stale(repo)
            code, out = tool(repo, "--collapse", "signoff-baseline")
            new = [r for r in baseline_records(repo) if r not in LEAF_IDS]
            check(f"--collapse accepts identical {label} wrapped Results", code == 0
                  and len(new) == 1, out, failures)
            if new:
                text = T.record_path(repo, "signoff-baseline", new[0]).read_text(encoding="utf-8")
                check(f"collapsed record replaces the whole {label} wrapped Result body",
                      "- **Result**: (fill in)" in text and "PASS (wrapped)" not in text
                      and "run configuration tail" not in text, text, failures)

    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d))
        stale(repo)
        code, out = tool(repo, "--collapse", "signoff-baseline")
        first = [r for r in baseline_records(repo) if r not in LEAF_IDS]
        draft = T.record_path(repo, "signoff-baseline", first[0]) if first else None
        if draft:
            edited = draft.read_text(encoding="utf-8") + "\noperator note\n"
            draft.write_text(edited, encoding="utf-8")
        code2, out2 = tool(repo, "--collapse", "signoff-baseline")
        check("a repeat --collapse points at the pending draft and mints nothing",
              code == 0 and code2 == 1 and "already pending" in out2
              and bool(draft) and first[0] in out2
              and [r for r in baseline_records(repo) if r not in LEAF_IDS] == first
              and draft.read_text(encoding="utf-8") == edited, out2, failures)


def mixed_list_cases(failures: list) -> None:
    """A valid entry beside an invalid sibling still supersedes its target in
    the minter's liveness view (#472)."""
    for label, sibs in (("an int", [7]), ("nulls", [None, None]),
                        ("a duplicate", None)):
        with tempfile.TemporaryDirectory(prefix="remint-mixed-") as d:
            repo = build_collapsible(Path(d), leaves=3)
            ids = [f"20260101-{i:06d}-abc1234" for i in range(3)]
            sup = ([ids[0], *sibs] if sibs is not None
                   else [ids[0], ids[0], ids[1]])
            nid = "20260102-000000-abc1234"
            T.record_path(repo, "signoff-baseline", nid).write_text(
                T.make_record(nid, "signoff-baseline", supersedes=sup,
                              inputs=[("rtl/dut.v", T._sha256_text(T.DUMMY_RTL))]),
                encoding="utf-8")
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "mixed list")
            stale(repo)
            code, out = tool(repo)
            stale_ids = {l.rsplit("/", 1)[-1][:-3] for l in out.splitlines()
                         if l.startswith("STALE")}
            expected = {ids[1], ids[2], nid} if sibs is not None else {ids[0], ids[2], nid}
            check(f"minter keeps a valid entry beside {label} effective",
                  code == 1 and stale_ids == expected, out, failures)


def tool(repo: Path, *args: str, broker: str | None = None,
         cwd: Path | None = None) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != "KLT_ARTIFACT_BROKER"}
    if broker:
        env["KLT_ARTIFACT_BROKER"] = broker
    r = subprocess.run([sys.executable, str(repo / "verification" / "remint_records.py"), *args],
                       cwd=cwd or repo, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def records(repo: Path) -> list[str]:
    return sorted(p.stem for p in (repo / "verification/records/demo/records").glob("*.md"))


def check(name: str, ok: bool, out: str, failures: list) -> None:
    print(("OK:   " if ok else "FAIL: ") + name)
    if not ok:
        failures.append(name)
        print("  | " + out.replace("\n", "\n  | "))


def lint(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(repo / "verification" / "check_records.py"),
                           "--base-ref", T.BASE_REF, "--require-append-only"],
                          cwd=repo, capture_output=True, text=True)


def commit_leaves(repo: Path, edit) -> None:
    for rid in LEAF_IDS:
        p = T.record_path(repo, "signoff-baseline", rid)
        p.write_text(edit(rid, p.read_text(encoding="utf-8")), encoding="utf-8")
    T._git(repo, "add", "-A")
    T._git(repo, "commit", "--quiet", "-m", "edit leaves")
    stale(repo)


def collapse_boundary_cases(failures: list) -> None:
    """Comparison and replacement share one complete field boundary; an
    unidentifiable field refuses the mint (#477 review)."""
    def blank_indented(verdict):
        def edit(rid, text):
            v = verdict[rid]
            return text.replace(
                "- **Result**: **Overall: PASS** (fixture)",
                f"\n  - **Result**: Item 9 status\n  {v} (indented)",
            ).replace(
                "- **Run configuration**: fixture run, no real simulator invoked",
                f"\n - **Run configuration**: fixture run {v}",
            )
        return edit

    def second_para(field, value, verdict, paragraph="  {verdict} second paragraph"):
        def edit(rid, text):
            tail = paragraph.format(verdict=verdict[rid])
            return text.replace(
                f"- **{field}**: {value}",
                f"- **{field}**: Item 9 status\n\n{tail}")
        return edit

    claim = "`docs/baseline.md#the-measurement` -- fixture claim"
    result = "**Overall: PASS** (fixture)"
    differ = dict(zip(LEAF_IDS, ("PASS", "FAIL")))
    same = dict(zip(LEAF_IDS, ("PASS", "PASS")))
    cases = (
        ("blank-line indented field bullets", blank_indented),
        ("a Claim second paragraph", lambda v: second_para("Claim", claim, v)),
        ("a Result second paragraph", lambda v: second_para("Result", result, v)),
    )
    for label, mk in cases:
        with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
            repo = build_collapsible(Path(d))
            commit_leaves(repo, mk(differ))
            code, out = tool(repo, "--collapse", "signoff-baseline")
            check(f"--collapse mints nothing for conflicting leaves ({label})",
                  code == 1 and baseline_records(repo) == LEAF_IDS, out, failures)
        with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
            repo = build_collapsible(Path(d))
            commit_leaves(repo, mk(same))
            code, out = tool(repo, "--collapse", "signoff-baseline")
            new = [r for r in baseline_records(repo) if r not in LEAF_IDS]
            check(f"--collapse accepts equivalent leaves ({label})",
                  code == 0 and len(new) == 1, out, failures)
            if new:
                text = T.record_path(repo, "signoff-baseline", new[0]).read_text(encoding="utf-8")
                check(f"draft drops every inherited Result/Run configuration line ({label})",
                      "(indented)" not in text and "fixture run PASS" not in text
                      and ("second paragraph" in text) == ("Claim" in label), text, failures)
                T._git(repo, "add", "-A")
                T._git(repo, "commit", "--quiet", "-m", "draft")
                r = lint(repo)
                check(f"draft fails lint on Result and Run configuration ({label})",
                      r.returncode == 1 and "`Result`" in r.stdout
                      and "`Run configuration`" in r.stdout, r.stdout, failures)

    for label, field, value, verdicts, paragraph in (
        ("flush-left prose", "Result", result, differ, "{verdict} second paragraph"),
        ("blockquote", "Result", result, differ, "> {verdict}"),
        ("fenced code", "Result", result, differ, "```\n{verdict}\n```"),
        ("matching prose", "Run configuration", "fixture run, no real simulator invoked",
         same, "{verdict} second paragraph"),
    ):
        with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
            repo = build_collapsible(Path(d))
            commit_leaves(repo, second_para(field, value, verdicts, paragraph))
            code, out = tool(repo, "--collapse", "signoff-baseline")
            check(f"--collapse refuses {label} after a blank line in {field}",
                  code == 1 and f"`{field}`" in out and "ambiguous" in out
                  and baseline_records(repo) == LEAF_IDS, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d))
        commit_leaves(repo, lambda rid, t: t + "- **Result**: a second Result bullet\n")
        code, out = tool(repo, "--collapse", "signoff-baseline")
        check("--collapse refuses a leaf with a repeated required field",
              code == 1 and "not identifiable exactly once" in out
              and baseline_records(repo) == LEAF_IDS, out, failures)


def collapse_successor_cases(failures: list) -> None:
    """The successor cites its own evidence, not the predecessor's."""
    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d))

        def edit(rid, text):
            return (text.replace("- **Links**: Design under test: `rtl/dut.v`",
                                 f"- **Links**: [verdict](../artifacts/{rid}/report.json)")
                    .replace("rtl (`rtl/dut.v` @ `" + "0" * 40 + "`)",
                             "rtl at `" + "0" * 40 + "`"))
        commit_leaves(repo, edit)
        code, out = tool(repo, "--collapse", "signoff-baseline")
        new = [r for r in baseline_records(repo) if r not in LEAF_IDS]
        check("--collapse mints for leaves with artifact links", code == 0 and len(new) == 1,
              out, failures)
        if new:
            text = T.record_path(repo, "signoff-baseline", new[0]).read_text(encoding="utf-8")
            prose = text.split("-->", 1)[1]
            check("successor heading uses the new ID",
                  f"# Record {new[0]}" in prose and f"# Record {LEAF_IDS[1]}" not in prose,
                  text, failures)
            check("record-specific links point at the successor's artifacts",
                  f"../artifacts/{new[0]}/report.json" in prose
                  and f"artifacts/{LEAF_IDS[1]}/" not in prose, text, failures)
            check("run-specific Design provenance must be filled and the old one is historical",
                  "- **Design provenance**: (fill in)" in prose
                  and "Historical, from the predecessor" in prose, text, failures)
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "draft")
            r = lint(repo)
            check("lint requires Design provenance to be completed",
                  r.returncode == 1 and "`Design provenance`" in r.stdout, r.stdout, failures)

    with tempfile.TemporaryDirectory(prefix="remint-collapse-") as d:
        repo = build_collapsible(Path(d))
        commit_leaves(repo, lambda rid, t: t.replace(
            "N/A (fixture)", f"N/A, derived from {rid} elsewhere"))
        code, out = tool(repo, "--collapse", "signoff-baseline")
        check("--collapse refuses when a kept block cites the predecessor ambiguously",
              code == 1 and "nothing minted" in out
              and baseline_records(repo) == LEAF_IDS, out, failures)


def results_xml_cases(failures: list) -> None:
    """`environment.results_xml` must anchor on REPO_ROOT, never the
    process's cwd, and a reported-but-unreadable XML is an error, not an
    optional extra (#552)."""
    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        stale(repo)
        (repo / "klt-stub").write_text(stub_with_results(
            '{"path":"verification/.klt/results.xml","scope":"repo",'
            '"sha256":"sha256:0000"}'), encoding="utf-8")
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"),
                         cwd=repo / "rtl")
        new = [r for r in records(repo) if r != OLD_ID]
        check("repo-scoped results_xml re-mints from a subdirectory",
              code == 0 and len(new) == 1 and "MINTED" in out, out, failures)
        if new:
            xml = (repo / "verification/records/demo/artifacts" / new[0]
                   / "results_icarus.xml")
            check("subdirectory re-mint carries the results XML",
                  xml.is_file()
                  and xml.read_text(encoding="utf-8") == "xml-doc-for-request-demo",
                  out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        stale(repo)
        (repo / "klt-stub").write_text(
            stub_with_results('"verification/.klt/results.xml"'), encoding="utf-8")
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"),
                         cwd=repo / "rtl")
        new = [r for r in records(repo) if r != OLD_ID]
        check("legacy relative-string results_xml resolves against REPO_ROOT",
              code == 0 and len(new) == 1, out, failures)
        if new:
            xml = repo / "verification/records/demo/artifacts" / new[0] / "results_icarus.xml"
            check("legacy string re-mint carries the results XML",
                  xml.is_file()
                  and xml.read_text(encoding="utf-8") == "xml-doc-for-request-demo",
                  out, failures)

    for label, doc in (
            ("repo-scoped document",
             '{"path":"verification/.klt/never-written.xml","scope":"repo"}'),
            ("legacy string", '"verification/.klt/never-written.xml"')):
        with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
            repo = build(Path(d))
            stale(repo)
            (repo / "klt-stub").write_text(
                stub_with_results(doc, create=False), encoding="utf-8")
            code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"))
            check(f"missing results_xml ({label}) fails the re-mint",
                  code == 1 and records(repo) == [OLD_ID]
                  and "ERROR" in out and "results_xml" in out, out, failures)

    for label, doc in (
            ("external scope", '{"path":null,"scope":"external"}'),
            ("unknown scope", '{"path":"verification/.klt/results.xml","scope":"wat"}'),
            ("absent scope with a non-null path",
             '{"path":"verification/.klt/results.xml","scope":"absent"}'),
            ("missing scope", '{"path":"verification/.klt/results.xml"}')):
        with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
            repo = build(Path(d))
            stale(repo)
            (repo / "klt-stub").write_text(stub_with_results(doc), encoding="utf-8")
            code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"))
            check(f"unreadable results_xml ({label}) fails the re-mint",
                  code == 1 and records(repo) == [OLD_ID]
                  and "ERROR" in out and "results_xml" in out, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        stale(repo)
        (repo.parent / "outside-results.xml").write_text("outside", encoding="utf-8")
        (repo / "klt-stub").write_text(
            stub_with_results('{"path":"../outside-results.xml","scope":"repo"}',
                              create=False), encoding="utf-8")
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"))
        check("repo-scoped path escaping the repo root fails the re-mint",
              code == 1 and records(repo) == [OLD_ID]
              and "ERROR" in out and "results_xml" in out, out, failures)

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        stale(repo)
        (repo / "klt-stub").write_text(
            stub_with_results('{"path":null,"scope":"absent"}', create=False),
            encoding="utf-8")
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"))
        new = [r for r in records(repo) if r != OLD_ID]
        check("absent results_xml (null path) mints a record",
              code == 0 and len(new) == 1, out, failures)
        if new:
            art = repo / "verification/records/demo/artifacts" / new[0]
            check("absent results_xml mints the envelope only",
                  (art / "klt-functional-verification.json").is_file()
                  and not list(art.glob("results_*.xml")), out, failures)


def rerun_links_cases(failures: list) -> None:
    """A `--rerun` mint retargets the copied Links block's artifact
    references at the successor's own `artifacts/<new-id>/` directory; the
    predecessor stays cited only in the "Re-mint of" note (#588)."""
    with tempfile.TemporaryDirectory(prefix="remint-links-") as d:
        repo = build(Path(d))
        links = (f"[klt result](../artifacts/{OLD_ID}/klt-functional-verification.json), "
                 f"[test cases](../artifacts/{OLD_ID}/results_icarus.xml)")
        inputs = [("rtl/dut.v", T._sha256_text(T.DUMMY_RTL)),
                  (REQ, T._sha256_text('{"schema": "demo"}\n'))]
        T.record_path(repo, "demo", OLD_ID).write_text(
            T.make_record(OLD_ID, "demo", inputs=inputs, links=links),
            encoding="utf-8")
        old_art = repo / "verification/records/demo/artifacts" / OLD_ID
        old_art.mkdir(parents=True)
        (old_art / "klt-functional-verification.json").write_text("{}", encoding="utf-8")
        (old_art / "results_icarus.xml").write_text("<testsuites/>", encoding="utf-8")
        T._git(repo, "add", "-A")
        T._git(repo, "commit", "--quiet", "-m", "record with artifact links")
        T._git(repo, "update-ref", T.BASE_REF, "HEAD")
        stale(repo)
        (repo / "klt-stub").write_text(STUB_XML, encoding="utf-8")
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"))
        new = [r for r in records(repo) if r != OLD_ID]
        check("--rerun mints one superseding record (links fixture)",
              code == 0 and len(new) == 1 and "MINTED" in out, out, failures)
        if new:
            text = T.record_path(repo, "demo", new[0]).read_text(encoding="utf-8")
            check("re-minted [klt result]/[test cases] point at the successor's artifacts",
                  f"[klt result](../artifacts/{new[0]}/klt-functional-verification.json)" in text
                  and f"[test cases](../artifacts/{new[0]}/results_icarus.xml)" in text,
                  text, failures)
            prose = text.split("-->", 1)[1]
            check("the predecessor's artifact dir is cited only via the Re-mint note",
                  f"artifacts/{OLD_ID}/" not in prose
                  and f"Re-mint of `records/{OLD_ID}.md`" in prose, text, failures)
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "remint")
            r = lint(repo)
            check("retargeted links resolve (re-minted tree passes the real linter)",
                  r.returncode == 0, r.stdout + r.stderr, failures)

    # Multi-id and no-artifact-reference edges, exercised on the renderer
    # directly (the --rerun CLI never passes more than one supersedes id).
    import remint_records as rr
    other = "20260101-000005-abc1234"
    new_id = "20260102-000000-abc1234"
    meta = {"record_id": OLD_ID, "supersedes": None, "git_revision": "0" * 40,
            "provenance": {"inputs": [{"path": "rtl/protocol_core.v",
                                       "content_hash": "0" * 64}]}}
    old_text = T.make_record(
        OLD_ID, "demo", inputs=[("rtl/protocol_core.v", "0" * 64)],
        links=(f"[klt result](../artifacts/{OLD_ID}/klt-functional-verification.json), "
               f"[shared](../artifacts/{other}/results.xml), "
               "[bench](../../../test_firmware_swd.py)"))
    env = {"verification/request-demo.json":
           {"status": "pass", "passed_count": 1, "test_count": 1}}
    names = {"verification/request-demo.json":
             ["klt-functional-verification.json", "results_icarus.xml"]}
    rendered = rr.render_record(
        old_text, meta, new_id, "0" * 40, env, names,
        datetime_mod.datetime(2026, 1, 2, tzinfo=datetime_mod.timezone.utc),
        ["rtl/protocol_core.v"], "9.9.9", supersede_ids=[OLD_ID, other])
    check("multi-id retarget rewrites every superseded id's artifact refs",
          f"[klt result](../artifacts/{new_id}/klt-functional-verification.json)" in rendered
          and f"[shared](../artifacts/{new_id}/results.xml)" in rendered
          and f"artifacts/{OLD_ID}/" not in rendered
          and f"artifacts/{other}/" not in rendered, rendered, failures)
    check("a Links line with no artifact reference is left unchanged",
          "[bench](../../../test_firmware_swd.py)" in rendered, rendered, failures)


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

    with tempfile.TemporaryDirectory(prefix="remint-selftest-") as d:
        repo = build(Path(d))
        stale(repo)
        (repo / "klt-stub").write_text(STUB_STORE, encoding="utf-8")
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"),
                         "--artifact-store", "demo")
        check("artifact store without a broker fails closed, mints nothing",
              code == 1 and records(repo) == [OLD_ID] and "KLT_ARTIFACT_BROKER" in out
              and not (repo / "manifests").exists()
              and not (repo / "verification/records/demo/artifacts").exists(), out, failures)
        code, out = tool(repo, "--rerun", "--klt", str(repo / "klt-stub"),
                         "--artifact-store", "demo", broker="http://broker.invalid")
        new = [r for r in records(repo) if r != OLD_ID]
        check("artifact store mints a record with a manifest and no committed bytes",
              code == 0 and len(new) == 1
              and not (repo / "verification/records/demo/artifacts").exists()
              and (repo / "manifests/artifacts" / f"demo-{new[0]}.manifest.json").is_file()
              if new else False, out, failures)
        if new:
            text = T.record_path(repo, "demo", new[0]).read_text(encoding="utf-8")
            check("stored record carries the name/size/sha256 summary",
                  "| name | size | sha256 |" in text and "artifact store" in text
                  and "klt-functional-verification.json" in text, text, failures)
            T._git(repo, "add", "-A")
            T._git(repo, "commit", "--quiet", "-m", "remint")
            r = subprocess.run([sys.executable, str(repo / "verification/check_records.py"),
                                "--base-ref", T.BASE_REF],
                               cwd=repo, capture_output=True, text=True)
            check("stored record passes the real linter", r.returncode == 0,
                  r.stdout + r.stderr, failures)

    # Sanitized XML must still parse (#192): a literal `<repo>` in an attribute
    # is not well-formed XML, so the XML path escapes the placeholder.
    sys.path.insert(0, str(T.SCRIPT_DIR))
    import xml.etree.ElementTree as ET
    import remint_records as rr
    raw = (f'<testsuites>\n<property name="file" value="{rr.REPO_ROOT}/v/t.py"/>'
           f'<property name="h" value="{Path.home()}/x"/>'
           '<testcase name="t" classname="<scratch>/c">stdout <PDK_ROOT>/a</testcase>'
           '</testsuites>').replace('<testcase name="t" classname="<scratch>/c">',
                                    '<testcase name="t" classname="&lt;scratch&gt;/c">')
    clean = rr._sanitize_xml(raw)
    try:
        root = ET.fromstring(clean)
        parsed = root.find("property").get("value")
    except ET.ParseError as exc:
        root, parsed = None, f"ParseError: {exc}"
    check("sanitized XML parses and decodes to the <repo> placeholder",
          root is not None and parsed == "<repo>/v/t.py", str(parsed), failures)
    check("sanitized XML carries no literal placeholder",
          not any(f"<{n}>" in clean for n in rr.PLACEHOLDERS), clean, failures)
    check("plain _sanitize (JSON/text path) still writes the literal <repo>",
          rr._sanitize(f"{rr.REPO_ROOT}/a") == "<repo>/a", "", failures)

    collapse_cases(failures)
    collapse_wrapped_cases(failures)
    mixed_list_cases(failures)
    collapse_boundary_cases(failures)
    collapse_successor_cases(failures)
    results_xml_cases(failures)
    rerun_links_cases(failures)

    print()
    if failures:
        print(f"FAIL: {len(failures)} case(s)")
        return 1
    print("PASS: all remint_records cases behaved as specified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
