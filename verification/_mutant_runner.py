"""Shared runner for the negative-control (`*_mutants.py`) scripts (issue #295).

Each `verification/*_mutants.py` keeps only its `MUTANTS` table and the few
bench-specific hooks; the scaffolding they all need lives here: the
scratch-tree copy, the `klt functional-verification` call, the golden run,
the exact-text anchor-count substitution check, the caught/targeted logic,
`--out` / `--only` handling and the `summary.json` writer.

`run()` is the common golden-then-mutants loop. A script whose loop is
shaped differently (several benches per mutant, a non-text mutation) uses
the lower-level pieces -- `parse_args`, `open_out`, `fresh_tree`,
`run_bench`, `finish` -- and keeps only its own loop body.

Plain sibling import, like `_repo_utils.py`:
`from _mutant_runner import run, copy_tree`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Top-level directories a scratch tree needs (`verification/` is copied
#: separately, without `records/` and `.klt`).
COPY_DIRS = ("rtl", "src", "firmware", "spec")


def copy_tree(dst: Path, dirs=COPY_DIRS) -> None:
    for name in dirs:
        shutil.copytree(REPO_ROOT / name, dst / name, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "verification", dst / "verification", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "records", ".klt"))


def run_bench(tree: Path, request: str, klt=("klt",), tag: str = "", detail=None) -> dict:
    """Run one request in `tree`; keep klt's stdout/stderr as `klt[-<tag>]-std*`.

    `detail(t)` (optional) maps one parsed test dict to the value stored under
    its name; the default is its status string.
    """
    proc = subprocess.run(
        [*klt, "functional-verification", request, "--format", "json"],
        cwd=tree, capture_output=True, text=True, check=False,
    )
    suffix = f"-{tag}" if tag else ""
    (tree / f"klt{suffix}-stdout.json").write_text(proc.stdout, encoding="utf-8")
    (tree / f"klt{suffix}-stderr.txt").write_text(proc.stderr, encoding="utf-8")
    try:
        doc = json.loads(proc.stdout)
        tests = {t["name"]: (detail(t) if detail else t["status"]) for t in doc["tests"]}
    except (ValueError, KeyError, TypeError):
        return {"parsed": False, "rc": proc.returncode, "tests": {}}
    return {"parsed": True, "rc": proc.returncode, "tests": tests}


def parse_args(doc: str, argv, out_help: str = "directory to keep the per-mutant trees and summary.json in",
               skip_golden: bool = False):
    ap = argparse.ArgumentParser(description=doc.splitlines()[0])
    ap.add_argument("--out", help=out_help)
    ap.add_argument("--only", help="run just this mutant (the golden run still runs)")
    if skip_golden:
        ap.add_argument("--skip-golden", action="store_true", help="do not run the whole bench first")
    return ap.parse_args(argv)


def open_out(out_arg):
    """Return (out dir, TemporaryDirectory or None)."""
    if out_arg:
        out = Path(out_arg).resolve()
        out.mkdir(parents=True, exist_ok=True)
        return out, None
    tmp = tempfile.TemporaryDirectory()
    return Path(tmp.name), tmp


def fresh_tree(out: Path, name: str) -> Path:
    tree = out / name
    shutil.rmtree(tree, ignore_errors=True)
    copy_tree(tree)
    return tree


def apply_subs(tree: Path, name: str, rel: str, subs, summary: dict) -> bool:
    """Apply exact-text substitutions; each anchor must occur exactly `count` times."""
    path = tree / rel
    text = path.read_text(encoding="utf-8")
    for old, new, count in subs:
        if text.count(old) != count or old == new:
            print(f"FAIL {name}: anchor found {text.count(old)}x, expected {count}x: {old!r}")
            summary["runs"].append({"kind": "mutant", "name": name, "as_required": False,
                                    "error": "substitution did not apply"})
            return False
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    return True


def finish(out: Path, tmp, summary: dict, ok: bool, message: str) -> int:
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print("RESULT: " + (message if ok else "NOT as required"))
    if tmp is not None:
        tmp.cleanup()
    return 0 if ok else 1


def failed_tests(res: dict) -> list:
    return sorted(n for n, s in res["tests"].items() if s != "passed")


def run(doc, argv, *, bench, mutants, result_message, request=None, file=None,
        goldens=None, golden_label="golden (unmodified copy)", record_request=False,
        skip_golden_option=False, klt=("klt",), run_bench_fn=None, rebuild=None,
        rebuild_label="the mutated program", prepare=None,
        catch_phrase="a test meant to catch it") -> int:
    """The golden-then-mutants loop.

    `mutants` rows are `(name, what, file, subs, catchers)`; with `file=` given
    they are `(name, what, subs, catchers[, request])`. `goldens` is the list
    of requests the unmodified copy must pass (default: `[request]`);
    `golden_label` may use `{request}`. `rebuild(tree)` regenerates build
    artifacts from a mutated source (raises RuntimeError); `prepare(tree,
    catchers, request)` adjusts the tree before the bench runs.
    `run_bench_fn(tree, request)` replaces the plain bench call (it may add a
    `first` entry, printed and recorded as `first_mismatch`).
    """
    args = parse_args(doc, argv, skip_golden=skip_golden_option)
    out, tmp = open_out(args.out)
    bench_fn = run_bench_fn or (lambda tree, req: run_bench(tree, req, klt))
    ok = True
    summary = {"bench": bench, "runs": []}

    if not (skip_golden_option and args.skip_golden):
        golden = fresh_tree(out, "golden")
        for req in goldens or [request]:
            res = bench_fn(golden, req)
            failed = failed_tests(res)
            good = res["parsed"] and res["tests"] and not failed
            print(f"{'ok  ' if good else 'FAIL'} {golden_label.format(request=req)}: "
                  f"{len(res['tests']) - len(failed)}/{len(res['tests'])} passed")
            entry = {"kind": "golden"}
            if record_request:
                entry["request"] = req
            entry.update({"tests": len(res["tests"]), "failed": failed, "as_required": bool(good)})
            summary["runs"].append(entry)
            ok = ok and bool(good)

    for row in mutants:
        if file is None:
            name, what, rel, subs, catchers = row
            req = request
        else:
            name, what, subs, catchers, *rest = row
            rel, req = file, (rest[0] if rest else request)
        if args.only and name != args.only:
            continue
        tree = fresh_tree(out, name)
        if not apply_subs(tree, name, rel, subs, summary):
            ok = False
            continue
        if rebuild is not None:
            try:
                rebuild(tree)
            except RuntimeError as err:
                print(f"FAIL {name}: {rebuild_label} does not build: {err}")
                summary["runs"].append({"kind": "mutant", "name": name, "as_required": False,
                                        "error": str(err)})
                ok = False
                continue
        if prepare is not None:
            prepare(tree, catchers, req)
        res = bench_fn(tree, req)
        failed = failed_tests(res)
        caught = res["parsed"] and bool(failed)
        targeted = bool(catchers & set(failed))
        good = caught and targeted
        print(f"{'ok  ' if good else 'FAIL'} {name}: {len(failed)}/{len(res['tests'])} tests failed"
              f"{'' if res['parsed'] else ' (NO PARSED RESULT)'}"
              f"{'' if targeted or not caught else f' (not by {catch_phrase})'}"
              f" -- {what}")
        if res.get("first"):
            print(f"       first mismatch: {res['first'][:420]}")
        entry = {"kind": "mutant", "name": name, "defect": what, "file": rel}
        if record_request:
            entry["request"] = req
        entry.update({"tests": len(res["tests"]), "failed": failed,
                      "expected_catchers": sorted(catchers), "as_required": bool(good)})
        if "first" in res:
            entry["first_mismatch"] = res["first"]
        summary["runs"].append(entry)
        ok = ok and good

    return finish(out, tmp, summary, ok, result_message)
