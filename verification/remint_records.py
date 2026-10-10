#!/usr/bin/env python3
"""Stale-record report and re-mint helper for `verification/records/` (#193).

`check_records.py` fails a *live* record (one no other record supersedes)
whose `provenance.inputs[].content_hash` no longer matches the working tree.
The response is always the same chore: re-run the request that produced the
record and mint a superseding record. This tool automates the bookkeeping and
changes no semantics: freshness is decided by `check_records.check_hash_freshness`'s
own rule (recompute `sha256_of`, compare), and records stay append-only.

Default (report only, touches nothing):

    python3 verification/remint_records.py

prints, per stale live record, each stale input (recorded vs current hash)
and the `verification/request-*.json` file(s) the record hashes as inputs --
the request(s) that produced it. A record that hashes no request file (a
gate-level run, a synthesis baseline, ...) is reported as needing a by-hand
re-mint. Exit 0 if nothing is stale, 1 if something is.

With `--rerun`, for every stale record that names request file(s):

1. runs `klt functional-verification <request> --format json` once per
   distinct request (single-threaded, one at a time);
2. if every request passes, writes a NEW record
   `<experiment>/records/<new-id>.md` plus `artifacts/<new-id>/` (the klt
   envelope and its results XML, absolute paths replaced by `<repo>`/`<home>`; in the XML as
   `&lt;repo&gt;`/`&lt;home&gt;` so it stays well-formed),
   with `supersedes` = the stale record's ID, `git_revision` = HEAD, and every
   input hash recomputed from the tree. The old record is never edited or
   deleted. The new record's prose is the old record's, with Record ID,
   Result, Timestamp / author and Supersedes rewritten and a "Re-mint" note
   added to Links -- review it, and edit the Claim if the claim moved, before
   committing. A failing request mints nothing.

`--only EXPERIMENT` restricts to one experiment; `--klt CMD` picks the klt
executable (default `klt`; use `uvx --from klayout-tools==X.Y.Z klt`
quoting as needed).

Zero dependencies beyond the Python 3 standard library, `git` and klt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import check_records as cr
from _repo_utils import REPO_ROOT, run_git, sha256_of

REQUEST_RE = re.compile(r"^verification/request-[A-Za-z0-9._-]+\.json$")


def live_records() -> list[tuple[Path, dict]]:
    """Every tracked, well-laid-out, parseable record that no valid record in
    its own experiment supersedes (the same rule check_records.main uses)."""
    metas: dict[Path, dict] = {}
    ids: dict[str, set] = {}
    for path in cr._tracked_record_files():
        if not path.is_file() or cr.layout_error(path) or cr.symlink_error(path):
            continue
        ids.setdefault(cr.experiment_key(path), set()).add(path.stem)
        try:
            metas[path] = cr._extract_meta_block(path.read_text(encoding="utf-8"), path)
        except cr.LintError:
            continue
    superseded = set()
    for path, meta in metas.items():
        target = meta.get("supersedes")
        if not isinstance(target, str) or target == "none":
            continue
        exp = cr.experiment_key(path)
        if cr.supersession_error(path, target, ids.get(exp, set())) is None:
            superseded.add((exp, target))
    return [
        (p, m) for p, m in sorted(metas.items())
        if (cr.experiment_key(p), p.stem) not in superseded
    ]


def stale_report(records: list[tuple[Path, dict]]) -> list[dict]:
    """One entry per live record with >= 1 stale input:
    {path, experiment, record_id, stale: [(rel, recorded, current)],
     requests: [rel, ...]}. Missing/untracked inputs are not 'stale' (that
    is a different failure, left to check_records)."""
    out = []
    for path, meta in records:
        inputs = (meta.get("provenance") or {}).get("inputs")
        if not isinstance(inputs, list):
            continue
        stale, requests = [], []
        for item in inputs:
            if cr.input_error(path, item):
                continue
            rel = item["path"]
            if REQUEST_RE.match(rel):
                requests.append(rel)
            if cr.live_input_error(path, rel):
                continue
            current = sha256_of(REPO_ROOT / rel)
            if current != item["content_hash"]:
                stale.append((rel, item["content_hash"], current))
        if stale:
            out.append({
                "path": path,
                "experiment": cr.experiment_key(path),
                "record_id": path.stem,
                "stale": stale,
                "requests": requests,
            })
    return out


def print_report(report: list[dict]) -> None:
    if not report:
        print("no stale live records")
        return
    for e in report:
        print(f"STALE: {e['path'].relative_to(REPO_ROOT)}")
        for rel, rec, cur in e["stale"]:
            print(f"  - input {rel}: recorded {rec}, current {cur}")
        if e["requests"]:
            print(f"  request(s): {', '.join(e['requests'])}")
        else:
            print("  request(s): none hashed -- no request file; re-mint by hand")


def _sanitize(text: str) -> str:
    text = text.replace(str(REPO_ROOT), "<repo>")
    return text.replace(str(Path.home()), "<home>")


# Placeholder tokens the evidence workflow substitutes for host paths.
PLACEHOLDERS = ("repo", "home", "scratch", "PDK_ROOT")


def escape_placeholders(text: str) -> str:
    """Rewrite literal `<repo>`-style placeholders as `&lt;repo&gt;`.

    A literal `<` is forbidden in an XML attribute value, and a bare
    `<repo>` in text content is parsed as a (never closed) element, so a
    placeholder dropped into a results XML makes the file unparseable
    (#192 review). The escaped form parses back to exactly `<repo>`."""
    for name in PLACEHOLDERS:
        text = text.replace(f"<{name}>", f"&lt;{name}&gt;")
    return text


def _sanitize_xml(text: str) -> str:
    """`_sanitize` for XML: same substitutions, XML-escaped placeholders."""
    return escape_placeholders(_sanitize(text))


def run_request(klt: list[str], request: str) -> tuple[dict, str | None]:
    """Run one request; return (parsed klt envelope, results-XML text).

    The XML is read immediately: klt reuses one `results_xml` path across
    requests, so a later request overwrites it. The snapshot travels with the
    envelope (and into the cache). Raises on no JSON."""
    proc = subprocess.run(
        [*klt, "functional-verification", request, "--format", "json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"klt produced no JSON for {request} (exit {proc.returncode}): "
            f"{proc.stderr.strip()[-400:]}"
        )
    xml_text = None
    xml = (env.get("environment") or {}).get("results_xml") if isinstance(env, dict) else None
    if xml and Path(xml).is_file():
        xml_text = Path(xml).read_text(encoding="utf-8")
    return env, xml_text


def allocate_id(old_id: str, exp_dir: Path, now: dt.datetime, short_rev: str,
                taken: set[str]) -> tuple[str, dt.datetime]:
    """A schema-valid record ID, lexically after `old_id`, unused in this
    experiment (records/, artifacts/) and not in `taken`. Bumps the timestamp
    one second at a time; returns (id, the timestamp that ID encodes)."""
    when = now
    while True:
        cand = f"{when.strftime('%Y%m%d-%H%M%S')}-{short_rev}"
        if (cand > old_id and cand not in taken
                and not (exp_dir / "records" / f"{cand}.md").exists()
                and not (exp_dir / "artifacts" / cand).exists()):
            return cand, when
        when += dt.timedelta(seconds=1)


def _split_blocks(body: str) -> list[list[str]]:
    """Split record prose into top-level bullet blocks (bullet + indented
    continuation lines); non-bullet lines are blocks of their own."""
    blocks: list[list[str]] = []
    for line in body.splitlines():
        if blocks and line.startswith((" ", "\t")) and line.strip():
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return blocks


def _field_of(block: list[str]) -> str | None:
    m = re.match(r"^-\s+\*\*(.+?)\*\*:", block[0])
    return m.group(1).strip() if m else None


def render_record(old_text: str, old_meta: dict, new_id: str, revision: str,
                  envelopes: dict[str, dict], artifact_names: dict[str, list[str]],
                  now: dt.datetime, stale_inputs: list[str], klt_version: str | None) -> str:
    old_id = old_meta["record_id"]
    meta = json.loads(json.dumps(old_meta))
    meta["record_id"] = new_id
    meta["supersedes"] = old_id
    meta["git_revision"] = revision
    if klt_version:
        meta["provenance"]["klt_version"] = klt_version
    for item in meta["provenance"]["inputs"]:
        item["content_hash"] = sha256_of(REPO_ROOT / item["path"])

    m = re.search(r"<!--\s*record-meta\s*(.*?)-->", old_text, re.DOTALL)
    head, body = "", old_text[m.end():]
    head = "<!-- record-meta\n" + json.dumps(meta, indent=2) + "\n-->"

    result_bits = []
    for req, env in envelopes.items():
        result_bits.append(
            f"`{req}`: **{env.get('status', '?').upper()}, "
            f"{env.get('passed_count')}/{env.get('test_count')}**"
        )
    arts = ", ".join(f"`{n}`" for names in artifact_names.values() for n in names)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    replacements = {
        "Record ID": f"- **Record ID**: {new_id}",
        "Result": (
            f"- **Result**: {'; '.join(result_bits)}. Artifacts in "
            f"`artifacts/{new_id}/`: {arts}. Machine-generated by "
            f"`verification/remint_records.py`; per-case detail is in the envelope."
        ),
        "Timestamp / author": (
            f"- **Timestamp / author**: {ts}, `verification/remint_records.py` "
            f"(automated re-mint; review before commit)."
        ),
        "Supersedes": (
            f"- **Supersedes**: `{old_id}` -- hashed input(s) changed: "
            f"{', '.join('`' + s + '`' for s in stale_inputs)}. Re-run unchanged "
            f"(same request file(s)); no claim text was edited by the tool."
        ),
    }
    out = []
    for block in _split_blocks(body):
        field = _field_of(block)
        if field in replacements:
            out.append(replacements[field])
        elif field == "Links":
            out.extend(block)
            out.append(
                f"  - Re-mint of `records/{old_id}.md` (superseded, untouched); "
                f"artifacts `artifacts/{new_id}/`."
            )
        else:
            out.extend(block)
    return head + "\n".join(out).rstrip("\n") + "\n"


def mint(entry: dict, envelopes: dict[str, dict], xmls: dict[str, str | None],
         new_id: str, revision: str, now: dt.datetime, klt_version: str | None) -> Path:
    path: Path = entry["path"]
    exp_dir = path.parent.parent
    new_rec = path.parent / f"{new_id}.md"
    art_dir = exp_dir / "artifacts" / new_id
    if new_rec.exists() or art_dir.exists():
        raise RuntimeError(f"{new_rec} or {art_dir} already exists; refusing to overwrite")
    if not new_id > entry["record_id"]:
        raise RuntimeError(f"new id {new_id} does not sort after {entry['record_id']}")
    art_dir.mkdir(parents=True)
    names: dict[str, list[str]] = {}
    multi = len(envelopes) > 1
    for req, env in envelopes.items():
        suffix = "-" + Path(req).stem.removeprefix("request-") if multi else ""
        files = []
        env_name = f"klt-functional-verification{suffix}.json"
        (art_dir / env_name).write_text(
            _sanitize(json.dumps(env, indent=2)) + "\n", encoding="utf-8")
        files.append(env_name)
        xml_text = xmls.get(req)
        if xml_text is not None:
            x_name = f"results_{env.get('engine', 'sim')}{suffix}.xml"
            (art_dir / x_name).write_text(_sanitize_xml(xml_text), encoding="utf-8")
            files.append(x_name)
        names[req] = files
    old_text = path.read_text(encoding="utf-8")
    old_meta = cr._extract_meta_block(old_text, path)
    text = render_record(old_text, old_meta, new_id, revision, envelopes, names,
                         now, [s[0] for s in entry["stale"]], klt_version)
    new_rec.write_text(text, encoding="utf-8")
    return new_rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rerun", action="store_true",
                    help="re-run the stale records' requests and mint superseding records")
    ap.add_argument("--only", metavar="EXPERIMENT",
                    help="restrict to one experiment (path relative to verification/records/)")
    ap.add_argument("--klt", default="klt", help="klt command (default: klt)")
    args = ap.parse_args(argv)

    report = stale_report(live_records())
    if args.only:
        report = [e for e in report if e["experiment"] == args.only]
    print_report(report)
    if not args.rerun:
        return 1 if report else 0

    todo = [e for e in report if e["requests"]]
    if not todo:
        return 1 if report else 0
    if run_git("status", "--porcelain", "--untracked-files=no"):
        print("WARNING: working tree is dirty; git_revision will be HEAD, not the tree run")
    klt = shlex.split(args.klt)
    revision = run_git("rev-parse", "HEAD")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    short_rev = run_git("rev-parse", "--short=7", "HEAD")
    taken: set[str] = set()
    try:
        v = subprocess.run([*klt, "--version"], capture_output=True, text=True, cwd=REPO_ROOT)
        klt_version = v.stdout.strip().split()[-1] if v.returncode == 0 and v.stdout.strip() else None
    except OSError:
        klt_version = None

    cache: dict[str, tuple[dict, str | None]] = {}
    failed = 0
    for e in todo:
        try:
            for req in e["requests"]:
                if req not in cache:
                    print(f"running {req} ...")
                    cache[req] = run_request(klt, req)
        except (RuntimeError, OSError) as exc:
            print(f"ERROR: {e['experiment']}: {exc}")
            failed += 1
            continue
        envs = {req: cache[req][0] for req in dict.fromkeys(e["requests"])}
        xmls = {req: cache[req][1] for req in envs}
        bad = [r for r, env in envs.items() if env.get("status") != "pass"]
        if bad:
            print(f"FAIL: {e['experiment']}: request(s) did not pass: {', '.join(bad)}; "
                  f"no record minted")
            failed += 1
            continue
        exp_dir = e["path"].parent.parent
        new_id, when = allocate_id(e["record_id"], exp_dir, now, short_rev, taken)
        taken.add(new_id)
        try:
            new = mint(e, envs, xmls, new_id, revision, when, klt_version)
        except (RuntimeError, OSError) as exc:
            print(f"ERROR: {e['experiment']}: {exc}")
            failed += 1
            continue
        print(f"MINTED: {new.relative_to(REPO_ROOT)} (supersedes {e['record_id']})")
    skipped = [e for e in report if not e["requests"]]
    for e in skipped:
        print(f"SKIPPED (no request file): {e['experiment']}/{e['record_id']}")
    return 1 if failed or skipped else 0


if __name__ == "__main__":
    sys.exit(main())
