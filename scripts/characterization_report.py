#!/usr/bin/env python3
"""Generate / check the pre-silicon characterization report (T1 item 8, issue #349).

Inputs (all committed): spec/target-spec.md (row names), the "Current reading"
digest of spec/gap-to-submission.md (row verdicts), measurements/
characterization-sources.json (measured values, evidence citations and, since
issue #524, a per-row evidence owner) and verification/records/*/records/*.md
(the cited records).

Outputs: measurements/characterization.md and the generic signoff envelope
manifests/evidence/characterization.json (status pass only when no row fails).

Owner column (issue #524): every row that does not pass must name, in
characterization-sources.json, the open issue that would move its verdict
(owner.issues, rendered as clickable links) and/or the ratification it waits
on (owner.waits). The generator enforces this offline -- it validates shape,
never fetching issue state; openness is the filer's verification, recorded
when the owner is entered.

--check also compares the top-level manifest's item 8 citation
(manifests/sg13cmos5l-protocol-emulator.json, evidence["8"].content_hash)
with the freshly built envelope's input hash. The manifest is hand-curated,
so a regeneration leaves that pin stale; this check surfaces it in the same
step as the generated-file drift instead of three gates later (issue #458).
The generation run never writes the manifest.

Usage:
    python3 scripts/characterization_report.py          # regenerate both files
    python3 scripts/characterization_report.py --check  # fail on any drift

Exit codes: 0 ok, 1 drift or invalid input. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "verification"))
from check_records import effective_supersedes

SOURCES = "measurements/characterization-sources.json"
REPORT = "measurements/characterization.md"
ENVELOPE = "manifests/evidence/characterization.json"
MANIFEST = "manifests/sg13cmos5l-protocol-emulator.json"
ISSUE_URL = "https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/issues/"
VERDICT = {"met": "pass", "unmet": "fail", "proposed": "proposed"}
REMEDIATION = (
    "remediate in order: regenerate the report and envelope (rerun without --check), "
    "review and update the item 8 pin to the envelope's provenance.input.content_hash, "
    "re-mint the affected signoff-baseline records with scripts/signoff-report.sh, then "
    "confirm record freshness with python3 verification/check_records.py"
)


class Invalid(Exception):
    pass


def live_records(repo: Path, experiments: Iterable[str]) -> dict[str, dict[str, str]]:
    """experiment -> {record_id: ''} for records no later record supersedes.

    Only the named experiments are read, each once (issue #625); an experiment
    without a records directory has no live records.
    """
    base = repo / "verification" / "records"
    out: dict[str, dict[str, str]] = {}
    for exp in dict.fromkeys(experiments):
        ids: set[str] = set()
        superseded: set[str] = set()
        for f in sorted((base / exp / "records").glob("*.md")) if isinstance(exp, str) else []:
            m = re.search(r"<!-- record-meta\n(.*?)\n-->", f.read_text(), re.S)
            if not m:
                continue
            meta = json.loads(m.group(1))
            ids.add(f.stem)
            superseded.update(effective_supersedes(f, meta.get("supersedes"), ids))
        out[exp] = dict.fromkeys(sorted(ids - superseded), "")
    return out


def cited_experiments(node) -> Iterator[str]:
    """Every experiment characterization-sources.json names, at any nesting."""
    if isinstance(node, dict):
        if "experiment" in node:
            yield node["experiment"]
        for v in node.values():
            yield from cited_experiments(v)
    elif isinstance(node, list):
        for v in node:
            yield from cited_experiments(v)


def cite(ev: list[dict], live: dict[str, dict[str, str]], where: str) -> str:
    parts = []
    for e in ev:
        exp = e["experiment"]
        heads = sorted(live.get(exp, {}))
        if not heads:
            raise Invalid(f"{where}: experiment {exp!r} has no live record")
        rid = e.get("record_id")
        if rid:
            if rid not in heads:
                raise Invalid(f"{where}: record {rid} of {exp} is missing or superseded")
            parts.append(f"{exp} `{rid}`")
        else:
            n = len(heads)
            parts.append(f"{exp} `{heads[-1]}`" + (f" (+{n - 1} live)" if n > 1 else ""))
    return "; ".join(parts) if parts else "none"


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def spec_rows(text: str) -> dict[int, str]:
    rows = {}
    for line in text.splitlines():
        c = split_row(line) if line.startswith("|") else []
        if len(c) > 2 and c[0].isdigit():
            rows[int(c[0])] = c[1]
    return rows


def digest(text: str) -> dict[int, tuple[str, str]]:
    out = {}
    sec = text.split("## Current reading", 1)[1].split("\n## ", 1)[0]
    for line in sec.splitlines():
        c = split_row(line) if line.startswith("|") else []
        if len(c) == 5 and c[0].isdigit():
            out[int(c[0])] = (c[1], c[2])
    return out


def esc(s: str) -> str:
    return s.replace("|", "\\|")


def owner_cell(n: int, row: dict, verdict: str) -> str:
    """Render the per-row owner / ratification-wait cell (issue #524).

    characterization-sources.json carries an optional per-row "owner" object:
    {"issues": [<open issue numbers>], "waits": "<ratification it waits on>"}.
    A row whose verdict is fail / no evidence MUST carry at least one of the
    two, so a failing row without an owner or a named wait fails generation
    instead of silently regressing to an untracked gap. Shape only -- issue
    state is never fetched here (generation stays offline).
    """
    o = row.get("owner")
    if o is None:
        if verdict in ("fail", "no evidence"):
            raise Invalid(
                f"row {n}: failing row carries no owner or ratification wait; add an "
                f'"owner" {{"issues": [...]}} and/or {{"waits": "..."}} entry for the '
                f"row in {SOURCES}"
            )
        return "none"
    if not isinstance(o, dict):
        raise Invalid(f"row {n}: owner must be an object with optional issues / waits")
    issues = o.get("issues", [])
    waits = o.get("waits", "")
    if not isinstance(issues, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in issues
    ):
        raise Invalid(f"row {n}: owner.issues must be a list of positive issue numbers")
    if len(set(issues)) != len(issues):
        raise Invalid(f"row {n}: owner.issues names an issue twice")
    if not isinstance(waits, str) or (waits and not waits.strip()):
        raise Invalid(f"row {n}: owner.waits must be a non-empty string when present")
    if not issues and not waits.strip():
        raise Invalid(f"row {n}: owner names neither an issue nor a wait")
    parts = []
    if waits.strip():
        parts.append(f"waits on {waits.strip()}")
    if issues:
        parts.append(", ".join(f"[#{i}]({ISSUE_URL}{i})" for i in issues))
    return esc("; ".join(parts))


def build(repo: Path) -> tuple[str, str]:
    src = json.loads((repo / SOURCES).read_text())
    names = spec_rows((repo / "spec/target-spec.md").read_text())
    dig = digest((repo / "spec/gap-to-submission.md").read_text())
    live = live_records(repo, cited_experiments(src))
    rows = {int(k): v for k, v in src["rows"].items()}
    if set(rows) != set(names) or set(dig) != set(names):
        raise Invalid(f"row sets differ: spec {sorted(names)}, sources {sorted(rows)}, digest {sorted(dig)}")

    lines = [
        "# Pre-silicon characterization report",
        "",
        "<!-- Generated by scripts/characterization_report.py; do not edit by hand. -->",
        "",
        "T1 item 8 summary: per-spec-row performance across conditions, with the evidence",
        "record each verdict rests on. **Pre-silicon:** every figure is simulation, static",
        "timing or place-and-route output; no bench or silicon data exists here (post-tape-out",
        "bench data belongs elsewhere in `measurements/`). Verdicts are the live reading of",
        "`spec/gap-to-submission.md`; the report neither relaxes nor re-grades the ratified spec.",
        "Each number names the flow that produced it (LibreLane = Tiny Tapeout template flow;",
        "klt = this program's flow). Every failing row's owner cell names the open issue",
        "that would move its verdict, or the ratification it waits on (issue #524; the",
        "generator validates shape offline -- openness was verified when the owner was",
        "recorded).",
        "",
        "## Spec rows",
        "",
        "| Row | Spec row | Target | Measured | Conditions | Verdict | Evidence records | Owner / wait |",
        "|---|---|---|---|---|---|---|---|",
    ]
    fails = []
    for n in sorted(rows):
        r = rows[n]
        state, reason = dig[n]
        if state not in VERDICT:
            raise Invalid(f"row {n}: unknown digest state {state!r}")
        verdict = VERDICT[state]
        if not r["evidence"]:
            if state == "met":
                raise Invalid(f"row {n}: met without evidence")
            verdict = "no evidence" if state == "unmet" else verdict
        if verdict in ("fail", "no evidence"):
            fails.append(n)
        ev = cite(r["evidence"], live, f"row {n}")
        lines.append(
            f"| {n} | {esc(names[n])} | {esc(r['target'])} | {esc(r['measured'])} | "
            f"{esc(r['conditions'])} | {verdict}: {esc(reason)} | {esc(ev)} | "
            f"{owner_cell(n, r, verdict)} |"
        )

    clk = src["clock_ns"]
    lines += [
        "",
        "## Fmax per corner",
        "",
        f"Flow: {src['timing_flow']}, clock {clk:g} ns, record "
        f"{cite([src['timing_record']], live, 'timing_record')}. Fmax is an **estimate** derived as "
        "1/(T - worst setup slack); the worst path at typ and fast is an I/O path, so treat those "
        "two as upper bounds.",
        "",
        "| Corner | Worst setup slack (ns) | Worst hold slack (ns) | Implied Fmax (MHz) | Setup/hold met at 20 ns |",
        "|---|---|---|---|---|",
    ]
    for c in src["corners"]:
        s, h = c["setup_slack_ns"], c["hold_slack_ns"]
        fmax = 1000.0 / (clk - s)
        lines.append(f"| {c['corner']} | {s:+.3f} | {h:+.4f} | {fmax:.1f} | {'yes' if s >= 0 and h >= 0 else 'NO'} |")
    kt = src["klt_timing"]
    lines += [
        "",
        f"Flow {kt['flow']}: {kt['status']} (record {cite(kt['evidence'], live, 'klt_timing')}).",
        "",
        "## Area",
        "",
        "| Quantity | Value | Flow | Evidence records |",
        "|---|---|---|---|",
    ]
    for a in src["area"]:
        lines.append(f"| {esc(a['item'])} | {esc(a['value'])} | {esc(a['flow'])} | {esc(cite(a['evidence'], live, 'area'))} |")
    p = src["power"]
    lines += [
        "",
        "## Power",
        "",
        f"Dynamic power per corner: **{p['value']}**. {p['reason']} "
        f"(record {cite(p['evidence'], live, 'power')}).",
        "",
        "## Findings",
        "",
    ]
    lines += [f"- {f}" for f in src["findings"]]
    lines += ["", f"Rows not passing: {', '.join(map(str, fails)) if fails else 'none'}.", ""]
    report = "\n".join(lines)

    digest_hash = hashlib.sha256(report.encode()).hexdigest()
    env = {
        "schema_version": 1,
        "kind": "generic",
        "status": "fail" if fails else "pass",
        "t1_item": 8,
        "summary": "Pre-silicon characterization report: one row per target-spec row with target, measured value, conditions, verdict and evidence record ids, plus Fmax per corner, area and power. Regenerated by scripts/characterization_report.py; "
        + (f"rows not passing: {', '.join(map(str, fails))}." if fails else "every row passes."),
        "source": REPORT,
        "provenance": {
            "klt_version": "n/a (generated by scripts/characterization_report.py)",
            "klayout_version": None,
            "pdk": None,
            "deck": None,
            "input": {
                "content_hash": "sha256:" + digest_hash,
                "path": {"path": REPORT, "scope": "repo"},
            },
        },
    }
    return report, json.dumps(env, indent=2) + "\n"


def manifest_pin_error(expected: str) -> str | None:
    """Top-manifest item 8 citation vs the freshly built envelope's input hash."""
    try:
        manifest = json.loads((REPO / MANIFEST).read_text())
    except (OSError, json.JSONDecodeError) as e:
        return f"{MANIFEST} is not readable JSON ({e}); cannot check the item 8 citation"
    cite = manifest.get("evidence", {}).get("8")
    if not isinstance(cite, dict) or not isinstance(cite.get("content_hash"), str):
        return (
            f"{MANIFEST}: evidence[\"8\"].content_hash is missing; the freshly built "
            f"envelope records {expected}"
        )
    if cite["content_hash"] != expected:
        return (
            f"{MANIFEST}: evidence[\"8\"].content_hash pins {cite['content_hash']}, "
            f"the freshly built envelope records {expected}"
        )
    return None


def main(argv: list[str]) -> int:
    check = "--check" in argv
    try:
        report, env = build(REPO)
    except (Invalid, OSError, KeyError, ValueError) as e:
        print(f"characterization_report: {e}", file=sys.stderr)
        return 1
    expected = json.loads(env)["provenance"]["input"]["content_hash"]
    bad = False
    for rel, new in ((REPORT, report), (ENVELOPE, env)):
        p = REPO / rel
        if check:
            if not p.exists() or p.read_text() != new:
                print(f"characterization_report: {rel} is out of date; rerun without --check", file=sys.stderr)
                bad = True
        else:
            p.write_text(new)
    if check:
        err = manifest_pin_error(expected)
        if err:
            print(f"characterization_report: {err}", file=sys.stderr)
            print(f"characterization_report: {REMEDIATION}", file=sys.stderr)
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
