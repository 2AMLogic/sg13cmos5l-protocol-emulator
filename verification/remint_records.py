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
   deleted. The new record's prose is the old record's, with the
   `# Record` heading, Record ID, Result, Timestamp / author and Supersedes
   rewritten and a "Re-mint" note added to Links -- review it, and edit the
   Claim if the claim moved, before committing. A failing request mints
   nothing.

`--only EXPERIMENT` restricts to one experiment; `--klt CMD` picks the klt
executable (default `klt`; use `uvx --from klayout-tools==X.Y.Z klt`
quoting as needed).

`--collapse EXPERIMENT` (mutually exclusive with `--rerun`, #472) targets the
interchangeable-leaf experiments (`COLLAPSIBLE_EXPERIMENTS`, currently
`signoff-baseline`): it mints ONE record whose `supersedes` lists every stale
live leaf of the experiment, instead of one successor per leaf, so parallel
branches that each re-mint cannot double the leaf count again. It is
bookkeeping only -- nothing is re-run (those leaves hash no request file;
their experiment is re-run by hand, e.g. `scripts/signoff-report.sh`) -- so
the minted record's **Result**, **Run configuration** and **Design provenance** are `(fill in)`
placeholders that `check_records.py` rejects until the operator who re-ran
the experiment fills them in. Refused for any other experiment, for stale
leaves that hash request files (use `--rerun`), and for leaves whose input
paths, claim or result are not interchangeable.

Heavy experiments (`ARTIFACT_STORE_EXPERIMENTS`, plus any `--artifact-store
EXPERIMENT`) do not commit their raw outputs (#344): the envelope and XML are
staged in the git-ignored `verification/.artifact-scratch/`, stored with
`klt artifact put` (see `verification/artifact_store.py`), and the new record
carries only the summary table, with the manifest under `manifests/artifacts/`.
This fails closed: with no broker the run stops before any simulation and
mints nothing.

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

# Experiments whose raw run output is large; their bytes go to the artifact store.
ARTIFACT_STORE_EXPERIMENTS = frozenset({
    "librelane-gds-signoff-check",
    "post-layout-sdf-regression",
    "random-regression",
})

# Experiments whose stale live leaves are interchangeable restatements of one
# verdict -- identical input paths, claim and result, only record_id,
# supersedes and timestamp differ (measured on the 20261119 signoff-baseline
# batches, #472). `--collapse` mints ONE record superseding every stale live
# leaf of such an experiment instead of one per leaf, so two branches that
# each re-mint in parallel cannot double the live-leaf count on merge. Every
# other experiment keeps one successor per leaf (its records assert
# genuinely distinct runs).
COLLAPSIBLE_EXPERIMENTS = frozenset({
    "signoff-baseline",
})

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
        exp = cr.experiment_key(path)
        for target in cr.effective_supersedes(
                path, meta.get("supersedes"), ids.get(exp, set())):
            superseded.add((exp, target))
    return [
        (p, m) for p, m in sorted(metas.items())
        if (cr.experiment_key(p), p.stem) not in superseded
    ]


def stale_report(records: list[tuple[Path, dict]]) -> list[dict]:
    """One entry per live record with >= 1 stale input:
    {path, experiment, record_id, stale: [(rel, recorded, current)],
    requests: [rel, ...]}. Missing/untracked inputs are not 'stale' (that
    is a different failure, left to check_records). Paths in
    `check_records.FRESHNESS_EXEMPT_INPUT_PATHS` are not compared here
    either, so this tool never asks for a re-mint the linter does not want
    (#371); the exemption list is imported, never restated."""
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
            if rel in cr.FRESHNESS_EXEMPT_INPUT_PATHS:
                continue  # not compared by check_records either (#371)
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


def _resolve_results_xml(xml: object) -> Path | None:
    """Anchor klt's `environment.results_xml` on REPO_ROOT (#552).

    klt >= 0.9 reports a `{path, scope, sha256}` document: `scope: "repo"`
    means `path` is relative to the repo (never this process's cwd), and
    `scope: "absent"` with a null path means no XML was produced. klt < 0.9
    reported a bare string (absolute, or repo-relative). Everything else --
    an unreadable or missing scope, a non-string/empty/absolute repo path,
    a path escaping REPO_ROOT, a non-string/non-dict value -- raises: klt
    named the results, so silently dropping them would mint a record that
    looks complete but is not. Returns None only for a missing value or an
    explicit absent document."""
    if xml is None:
        return None
    if isinstance(xml, dict):
        scope, path = xml.get("scope"), xml.get("path")
        if scope == "absent" and path is None:
            return None
        if scope == "repo":
            if not isinstance(path, str) or not path:
                raise RuntimeError(f"results_xml: 'repo' scope without a usable path: {xml!r}")
            rel = Path(path)
            if rel.is_absolute():
                raise RuntimeError(f"results_xml: 'repo' scope path is absolute: {xml!r}")
            target = (REPO_ROOT / rel).resolve()
            if not target.is_relative_to(REPO_ROOT.resolve()):
                raise RuntimeError(f"results_xml: 'repo' scope path escapes the repo root: {xml!r}")
            return target
        raise RuntimeError(f"results_xml: unreadable scope {scope!r}: {xml!r}")
    if isinstance(xml, str):
        if not xml:
            raise RuntimeError("results_xml: empty path")
        p = Path(xml)
        return p if p.is_absolute() else REPO_ROOT / p
    raise RuntimeError(f"results_xml: unexpected value: {xml!r}")


def run_request(klt: list[str], request: str) -> tuple[dict, str | None]:
    """Run one request; return (parsed klt envelope, results-XML text).

    The XML is read immediately: klt reuses one `results_xml` path across
    requests, so a later request overwrites it. The snapshot travels with the
    envelope (and into the cache). Raises on no JSON, on a `results_xml`
    that cannot be resolved (see `_resolve_results_xml`), and on a reported
    XML missing from disk -- a miss is a real failure, not an optional
    extra."""
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
    target = _resolve_results_xml(xml)
    if target is not None:
        if not target.is_file():
            raise RuntimeError(
                f"klt reported results_xml at {target} for {request}, but no such "
                f"file exists; refusing to mint a record without its per-test results"
            )
        xml_text = target.read_text(encoding="utf-8")
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


# A field bullet exactly as the linter recognises it (`check_records.py`
# strips each line first, so an indented `- **Field**:` counts).
_FIELD_RE = re.compile(r"^\s*-\s+\*\*(.+?)\*\*:")
# Column-0 lines that always end a field's block.
_NEW_BLOCK_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s|#|<!--|>|```|\|)")
# The fields the collapse path compares, replaces or relies on; each must be
# identified unambiguously (exactly one bullet) or the tool refuses to mint.
_COLLAPSE_REQUIRED = ("Record ID", "Claim", "Design provenance", "Run configuration",
                      "Result", "Links", "Timestamp / author", "Supersedes")


def _split_blocks(body: str) -> list[list[str]]:
    """Split record prose into field blocks using the linter's field
    recognition. A field bullet (at any indent) owns every following line up
    to the next field bullet, heading, comment or column-0 bullet: indented
    lines (including after a blank line, e.g. a second paragraph) and
    flush-left hard-wrapping directly after it. Blank lines that trail a
    block stay in it so replacement preserves spacing. Other lines are
    blocks of their own."""
    blocks: list[list[str]] = []
    after_blank = False
    for line in body.splitlines():
        cur = blocks[-1] if blocks else None
        in_field = cur is not None and _field_of(cur) is not None
        if _FIELD_RE.match(line):
            blocks.append([line])
        elif in_field and not line.strip():
            cur.append(line)
        elif in_field and line.strip() and (
                line.startswith((" ", "\t"))
                or (not after_blank and not _NEW_BLOCK_RE.match(line))):
            cur.append(line)
        else:
            blocks.append([line])
        after_blank = not line.strip()
    return blocks


def _field_of(block: list[str]) -> str | None:
    m = _FIELD_RE.match(block[0])
    return m.group(1).strip() if m else None


def _is_record_heading(line: str, old_id: str) -> bool:
    """True if `line` is exactly the `# Record <old_id>` H1. One shared
    match for both renderers, so the plain and collapse re-mints rewrite
    the heading the same way."""
    return bool(re.fullmatch(r"#\s+Record\s+" + re.escape(old_id), line.strip()))


def _content_lines(block: list[str]) -> list[str]:
    """The block without its trailing blank lines."""
    end = len(block)
    while end and not block[end - 1].strip():
        end -= 1
    return block[:end]


def _trailing_blanks(block: list[str]) -> list[str]:
    return block[len(_content_lines(block)):]


def _require_fields(body: str, names: tuple[str, ...] = _COLLAPSE_REQUIRED) -> None:
    """Require exactly one bullet with an unambiguous end for each named field."""
    counts: dict[str, int] = {}
    field_before_blank = None
    for block in _split_blocks(body):
        f = _field_of(block)
        if f is not None:
            counts[f] = counts.get(f, 0) + 1
        elif field_before_blank in names:
            raise ValueError(f"ambiguous unindented block after `{field_before_blank}`: "
                             "indent field continuations after a blank line")
        field_before_blank = f if not block[-1].strip() else None
    bad = [n for n in names if counts.get(n, 0) != 1]
    if bad:
        raise ValueError("field(s) not identifiable exactly once: "
                         + ", ".join(f"`{n}` (x{counts.get(n, 0)})" for n in bad))


def render_record(old_text: str, old_meta: dict, new_id: str, revision: str,
                  envelopes: dict[str, dict], artifact_names: dict[str, list[str]],
                  now: dt.datetime, stale_inputs: list[str], klt_version: str | None,
                  stored: str | None = None,
                  supersede_ids: list[str] | None = None) -> str:
    old_id = old_meta["record_id"]
    old_ids = [old_id] if supersede_ids is None else list(supersede_ids)
    meta = json.loads(json.dumps(old_meta))
    meta["record_id"] = new_id
    meta["supersedes"] = old_ids[0] if len(old_ids) == 1 else old_ids
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
    where = (f"Raw outputs stored via the artifact store (manifest `{stored}`, not in git): {arts}"
             if stored else f"Artifacts in `artifacts/{new_id}/`: {arts}")
    where_link = (f"manifest `{stored}`" if stored else f"artifacts `artifacts/{new_id}/`")
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    ids_listed = ", ".join(f"`{i}`" for i in old_ids)
    replacements = {
        "Record ID": f"- **Record ID**: {new_id}",
        "Result": (
            f"- **Result**: {'; '.join(result_bits)}. {where}. Machine-generated by "
            f"`verification/remint_records.py`; per-case detail is in the envelope."
        ),
        "Timestamp / author": (
            f"- **Timestamp / author**: {ts}, `verification/remint_records.py` "
            f"(automated re-mint; review before commit)."
        ),
        "Supersedes": (
            f"- **Supersedes**: {ids_listed} -- hashed input(s) changed: "
            f"{', '.join('`' + s + '`' for s in stale_inputs)}. Re-run unchanged "
            f"(same request file(s)); no claim text was edited by the tool."
        ),
    }
    out = []
    for block in _split_blocks(body):
        field = _field_of(block)
        if field in replacements:
            out.append(replacements[field])
            out.extend(_trailing_blanks(block))
        elif field == "Links":
            out.extend(_content_lines(block))
            if len(old_ids) == 1:
                out.append(
                    f"  - Re-mint of `records/{old_id}.md` (superseded, untouched); "
                    f"{where_link}."
                )
            else:
                out.append(
                    f"  - Collapse re-mint of {len(old_ids)} stale live leaves "
                    f"({ids_listed}; superseded, untouched); {where_link}."
                )
            out.extend(_trailing_blanks(block))
        elif _is_record_heading(block[0], old_id):
            out.append(f"# Record {new_id}")
            out.extend(block[1:])
        else:
            out.extend(block)
    return head + "\n".join(out).rstrip("\n") + "\n"


def mint(entry: dict, envelopes: dict[str, dict], xmls: dict[str, str | None],
         new_id: str, revision: str, now: dt.datetime, klt_version: str | None,
         klt: list[str] | None = None, store_bytes: bool = False) -> Path:
    path: Path = entry["path"]
    exp_dir = path.parent.parent
    new_rec = path.parent / f"{new_id}.md"
    art_dir = exp_dir / "artifacts" / new_id
    if new_rec.exists() or art_dir.exists():
        raise RuntimeError(f"{new_rec} or {art_dir} already exists; refusing to overwrite")
    if not new_id > entry["record_id"]:
        raise RuntimeError(f"new id {new_id} does not sort after {entry['record_id']}")
    if store_bytes:
        import artifact_store
        art_dir = artifact_store.scratch_dir(new_id)
    else:
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
    summary = manifest_rel = None
    if store_bytes:
        manifest, entries = artifact_store.store(
            entry["experiment"].replace("/", "-"), new_id,
            [art_dir / n for ns in names.values() for n in ns], klt)
        manifest_rel = str(manifest.relative_to(REPO_ROOT))
        summary = artifact_store.summary_markdown(manifest, entries)
    text = render_record(old_text, old_meta, new_id, revision, envelopes, names,
                         now, [s[0] for s in entry["stale"]], klt_version, manifest_rel)
    if summary:
        text += "\n" + summary
    new_rec.write_text(text, encoding="utf-8")
    return new_rec


def _collapse_fingerprint(entry: dict) -> tuple:
    """What makes stale live leaves interchangeable: the ordered list of
    input paths they hash, and their Claim and Result prose. Recorded hashes
    are deliberately excluded -- two branches that re-minted in parallel
    recorded the hashes of their own trees, which is the exact case
    `--collapse` exists to merge (#472)."""
    text = entry["path"].read_text(encoding="utf-8")
    meta = cr._extract_meta_block(text, entry["path"])
    inputs = (meta.get("provenance") or {}).get("inputs")
    paths = tuple(i.get("path") for i in inputs) if isinstance(inputs, list) else ()
    _require_fields(_prose_body(text))
    return (paths, _field_text(text, "Claim"), _field_text(text, "Result"))


def _prose_body(text: str) -> str:
    m = re.search(r"<!--\s*record-meta\s*(.*?)-->", text, re.DOTALL)
    return text[m.end():] if m else text


def _field_text(text: str, field: str) -> str | None:
    """The COMPLETE body of a prose field -- its bullet line and every
    continuation line, indented or hard-wrapped flush-left -- with each line
    stripped so the two wrapping styles compare equal."""
    found = [b for b in _split_blocks(_prose_body(text)) if _field_of(b) == field]
    if len(found) != 1:
        raise ValueError(f"field `{field}` is not identifiable exactly once "
                         f"(found {len(found)})")
    return "\n".join(line.strip() for line in _content_lines(found[0]) if line.strip())


def render_collapsed_record(old_text: str, old_meta: dict, new_id: str,
                            supersede_ids: list[str], revision: str,
                            now: dt.datetime,
                            stale_inputs: list[str]) -> str:
    """The `--collapse` mint (#472): one record whose `supersedes` lists every
    stale live leaf. Bookkeeping only -- nothing was re-run by this tool, so
    **Result**, **Run configuration** and **Design provenance** are left as `(fill in)`
    placeholders, which `check_records.py` rejects until the operator who
    re-ran the experiment fills them in."""
    meta = json.loads(json.dumps(old_meta))
    meta["record_id"] = new_id
    meta["supersedes"] = list(supersede_ids)
    meta["git_revision"] = revision
    for item in meta["provenance"]["inputs"]:
        item["content_hash"] = sha256_of(REPO_ROOT / item["path"])

    m = re.search(r"<!--\s*record-meta\s*(.*?)-->", old_text, re.DOTALL)
    body = old_text[m.end():]
    head = "<!-- record-meta\n" + json.dumps(meta, indent=2) + "\n-->"
    old_id = old_meta["record_id"]
    _require_fields(body)

    ids_listed = ", ".join(f"`{i}`" for i in supersede_ids)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Design provenance names the predecessor's revision; nothing here ran,
    # so it is a placeholder (the linter rejects it) until the operator who
    # re-ran the experiment states the new one. The old text is kept, marked
    # historical, under Links.
    old_prov = next(
        _FIELD_RE.sub("", " ".join(l.strip() for l in _content_lines(b) if l.strip()),
                      count=1).strip()
        for b in _split_blocks(body) if _field_of(b) == "Design provenance")
    replacements = {
        "Record ID": f"- **Record ID**: {new_id}",
        "Design provenance": "- **Design provenance**: (fill in)",
        "Run configuration": "- **Run configuration**: (fill in)",
        "Result": "- **Result**: (fill in)",
        "Timestamp / author": (
            f"- **Timestamp / author**: {ts}, `verification/remint_records.py "
            f"--collapse` (bookkeeping mint; no run performed by the tool)."
        ),
        "Supersedes": (
            f"- **Supersedes**: {ids_listed} -- {len(supersede_ids)} interchangeable "
            f"stale live leaves (identical input paths, claim and result) collapsed "
            f"into this one record (#472). Hashed input(s) changed: "
            f"{', '.join('`' + s + '`' for s in stale_inputs)}."
        ),
    }

    def retarget(lines: list[str]) -> list[str]:
        """Point record-specific references (artifact directories) at the
        successor; the predecessor stays cited only as history."""
        return [l.replace(f"artifacts/{old_id}/", f"artifacts/{new_id}/") for l in lines]

    out = []
    for block in _split_blocks(body):
        field = _field_of(block)
        if field in replacements:
            out.append(replacements[field])
            out.extend(_trailing_blanks(block))
        elif field == "Links":
            out.extend(retarget(_content_lines(block)))
            out.append(
                f"  - Collapse re-mint of {len(supersede_ids)} stale live leaves "
                f"({ids_listed}; superseded, untouched) by "
                f"`verification/remint_records.py --collapse`; no run was performed "
                f"by the tool -- re-run the experiment, put its outputs in "
                f"`artifacts/{new_id}/`, then fill **Result**, **Run configuration** "
                f"and **Design provenance** before committing (`check_records.py` "
                f"fails on the placeholders until you do)."
            )
            out.append(
                f"  - Historical, from the predecessor `{old_id}` (not this "
                f"record's evidence): design provenance was {old_prov}"
            )
            out.extend(_trailing_blanks(block))
        elif old_id in "\n".join(block):
            # A record-specific reference the tool does not know how to
            # retarget would leave the reader inspecting the predecessor.
            if _is_record_heading(block[0], old_id):
                out.append(f"# Record {new_id}")
                out.extend(block[1:])
            else:
                retargeted = retarget(block)
                if old_id in "\n".join(retargeted):
                    raise ValueError(
                        f"a kept block still cites the predecessor `{old_id}` "
                        f"outside an artifacts/ link; cannot tell whether it is "
                        f"record-specific: {block[0].strip()[:80]!r}")
                out.extend(retargeted)
        else:
            out.extend(block)
    return head + "\n".join(out).rstrip("\n") + "\n"


def mint_collapsed(template: dict, supersede_ids: list[str], new_id: str,
                   revision: str, now: dt.datetime,
                   stale_inputs: list[str]) -> Path:
    path: Path = template["path"]
    new_rec = path.parent / f"{new_id}.md"
    if new_rec.exists():
        raise RuntimeError(f"{new_rec} already exists; refusing to overwrite")
    latest = max(supersede_ids)
    if not new_id > latest:
        raise RuntimeError(f"new id {new_id} does not sort after {latest}")
    old_text = path.read_text(encoding="utf-8")
    old_meta = cr._extract_meta_block(old_text, path)
    rendered = render_collapsed_record(old_text, old_meta, new_id, supersede_ids,
                                       revision, now, stale_inputs)
    new_rec.write_text(rendered, encoding="utf-8")
    return new_rec


def pending_collapse_drafts(experiment: str, leaf_ids: set[str]) -> list[Path]:
    """Untracked (not yet committed) records of `experiment` whose
    `supersedes` already names any of `leaf_ids`: a collapse draft minted by
    an earlier invocation. Tracked-only discovery cannot see them, so a retry
    would otherwise mint a second, differently named draft (#472)."""
    out = run_git("ls-files", "-z", "--others", "--exclude-standard", "--",
                  f"verification/records/{experiment}/records/*.md")
    drafts = []
    for name in out.split("\0"):
        if not name:
            continue
        path = REPO_ROOT / name
        try:
            meta = cr._extract_meta_block(path.read_text(encoding="utf-8"), path)
        except (cr.LintError, OSError):
            continue
        if not leaf_ids.isdisjoint(cr.supersedes_ids(meta.get("supersedes"))):
            drafts.append(path)
    return sorted(drafts)


def collapse(experiment: str) -> int:
    """`--collapse EXPERIMENT`: mint ONE record superseding every stale live
    leaf of an interchangeable-leaf experiment (#472). See the module
    docstring for the guards."""
    if experiment not in COLLAPSIBLE_EXPERIMENTS:
        print(
            f"ERROR: --collapse refuses {experiment!r}: only the known "
            f"interchangeable-leaf experiments "
            f"{', '.join(sorted(COLLAPSIBLE_EXPERIMENTS))} may be collapsed; "
            f"every other experiment keeps one successor per stale leaf"
        )
        return 1
    report = [e for e in stale_report(live_records()) if e["experiment"] == experiment]
    if not report:
        print(f"no stale live records in {experiment}; nothing to collapse")
        return 0
    if any(e["requests"] for e in report):
        print(
            f"ERROR: {experiment}: some stale leaves hash request files; re-run "
            f"them with --rerun instead (a collapse mint would skip the runs)"
        )
        return 1
    drafts = pending_collapse_drafts(experiment, {e["record_id"] for e in report})
    if drafts:
        print(
            f"ERROR: {experiment}: a collapse draft is already pending: "
            f"{', '.join(str(d.relative_to(REPO_ROOT)) for d in drafts)}; fill "
            f"it in and commit it (edits are preserved), or delete it to start "
            f"over -- not minting a second one"
        )
        return 1
    try:
        fingerprints = {_collapse_fingerprint(e) for e in report}
    except (ValueError, cr.LintError) as exc:
        print(f"ERROR: {experiment}: cannot compare the stale live leaves: {exc}; "
              f"collapse refuses to mint when a required field is ambiguous")
        return 1
    if len(fingerprints) > 1:
        print(
            f"ERROR: {experiment}: the {len(report)} stale live leaves are not "
            f"interchangeable (input paths, claim or result differ); collapse "
            f"refuses to merge records that assert different things"
        )
        return 1
    if run_git("status", "--porcelain", "--untracked-files=no"):
        print("WARNING: working tree is dirty; git_revision will be HEAD, not the tree run")
    revision = run_git("rev-parse", "HEAD")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    short_rev = run_git("rev-parse", "--short=7", "HEAD")
    supersede_ids = sorted(e["record_id"] for e in report)
    template = max(report, key=lambda e: e["record_id"])  # newest leaf
    exp_dir = template["path"].parent.parent
    new_id, _ = allocate_id(supersede_ids[-1], exp_dir, now, short_rev, set())
    stale_inputs = sorted({rel for e in report for rel, _, _ in e["stale"]})
    try:
        new = mint_collapsed(template, supersede_ids, new_id, revision, now,
                             stale_inputs)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"ERROR: {experiment}: {exc}; nothing minted")
        return 1
    print(f"MINTED: {new.relative_to(REPO_ROOT)} "
          f"(collapses {len(supersede_ids)} stale live leaves: {', '.join(supersede_ids)})")
    print("NOTE: Result, Run configuration and Design provenance are `(fill in)` placeholders -- re-run "
          "the experiment and fill them before committing; check_records.py fails on "
          "the placeholders until you do")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rerun", action="store_true",
                    help="re-run the stale records' requests and mint superseding records")
    ap.add_argument("--collapse", metavar="EXPERIMENT",
                    help="mint ONE record superseding every stale live leaf of "
                         "EXPERIMENT (interchangeable-leaf experiments only; "
                         "bookkeeping -- nothing is re-run; mutually exclusive "
                         "with --rerun)")
    ap.add_argument("--only", metavar="EXPERIMENT",
                    help="restrict to one experiment (path relative to verification/records/)")
    ap.add_argument("--klt", default="klt", help="klt command (default: klt)")
    ap.add_argument("--artifact-store", action="append", default=[], metavar="EXPERIMENT",
                    help="also keep this experiment's raw outputs in the artifact store "
                         "(repeatable; the heavy experiments always do)")
    args = ap.parse_args(argv)

    if args.collapse is not None:
        if args.rerun:
            ap.error("--collapse and --rerun are mutually exclusive")
        if args.only and args.only != args.collapse:
            ap.error("--only conflicts with --collapse EXPERIMENT")
        return collapse(args.collapse)

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
    stored_exps = ARTIFACT_STORE_EXPERIMENTS | set(args.artifact_store)
    if any(e["experiment"] in stored_exps for e in todo):
        import artifact_store
        try:
            artifact_store.preflight(klt)
        except artifact_store.ArtifactStoreError as exc:
            print(f"ERROR: {exc}; nothing run, nothing minted")
            return 1
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
            new = mint(e, envs, xmls, new_id, revision, when, klt_version, klt,
                       e["experiment"] in stored_exps)
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
