#!/usr/bin/env python3
"""Hash-and-shape check for the T1 item 6 "not applicable" claim (issue #348).

`klt signoff` grades item 6's `not_applicable` form from two JSON documents
the block manifest cites by content hash (klayout-tools #2865):

  spec/target-spec-ratified.json    {"status": "ratified", "rows": [{"id": ..}]}
  spec/statistical-claims-na.json   {"rows": [{"id", "class", "reason"}, ..]}

The grader reads only those two files, so the markdowns they summarize --
`spec/target-spec.md` (the ratified spec) and `spec/statistical-claims-na.md`
(the human-readable statement) -- would be invisible to it. Each JSON
therefore embeds the sha256 of the markdown it stands for, and this script
fails when an embed no longer matches the file on disk. That is the tripwire
that freezes the spec markdown: any edit to it (including a dated note that
changes no Target) fails here first, and updating the companions then moves
the content hashes the manifest pins, which `klt signoff --check` reports as
drift -- the re-mint `manifests/README.md` documents.

Also checked, so a bad edit fails here with a named error instead of at the
signoff render (or in CI's signoff job):

  * the spec companion is `ratified`, and every row is exactly `{"id": <str>}`
    -- ids only, never row titles, because the grader's conservative
    statistical scan refuses a spec row that mentions accuracy, matching,
    offset, yield, sigma or Monte Carlo, and row 10 is titled "UART
    bit-timing accuracy";
  * every statement row has non-empty string id/class/reason, its `class`
    passes the grader's statistical-word scan, and the statement accounts
    for exactly the spec companion's rows (no uncovered, no unknown, no
    duplicate);
  * both JSONs agree on the spec markdown's hash.

Run: python3 scripts/check_statistical_claims_na.py [--repo-root DIR]
(`npm run lint` via scripts/lint-manifest.txt). Standard library only.
Exit codes: 0 pass, 1 a check failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

SPEC_MD = "spec/target-spec.md"
SPEC_JSON = "spec/target-spec-ratified.json"
STATEMENT_MD = "spec/statistical-claims-na.md"
STATEMENT_JSON = "spec/statistical-claims-na.json"

# Mirror of klayout-tools signoff._NA_STATISTICAL_TEXT_RE, transcribed from
# klayout-tools 0.8.0 -- klt-pin: historical; this repo stopped pinning klt
# on 2026-11-14 (issue #371). A statement row's `class` (and any spec-row
# string) matching this refuses the item. The fleet version now lives in
# PIN_KLAYOUT_TOOLS_VERSION in 2AMLogic/2am's infra/aws/batch-image-pins.env
# (layout/toolchain.json declares only the bare `klayout-tools` requirement);
# when the fleet version changes, compare this mirror with the grader's scan
# and update it if the upstream scan changed.
STATISTICAL_TEXT_RE = re.compile(
    r"σ|\bsigma\b|\bcpk\b|\bppk\b|\byield\b|\bmonte[ _-]?carlo\b"
    r"|\bmismatch\b|\bmatching\b|\boffset\b|\baccuracy\b",
    re.IGNORECASE,
)

STATISTICAL_KEY_RE = re.compile(
    r"sigma|σ|yield|cpk|ppk|offset|mismatch|monte[_ -]?carlo|std[_ -]?dev",
    re.IGNORECASE,
)


def sha256_hex(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _str_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def scan_statistical(value: object, path: str) -> str | None:
    """The grader's conservative scan, mirrored (signoff._na_scan_statistical).

    Returns a path description of the first statistical-looking hit, or None.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() == "statistical":
                if child not in (None, False, 0, "", "false", "no"):
                    return key_path
                continue
            keyed = STATISTICAL_KEY_RE.search(str(key)) and child not in (
                None, False, "", [], {},
            )
            if keyed:
                return key_path
            hit = scan_statistical(child, key_path)
            if hit is not None:
                return hit
        return None
    if isinstance(value, list):
        for index, child in enumerate(value):
            hit = scan_statistical(child, f"{path}[{index}]")
            if hit is not None:
                return hit
        return None
    if isinstance(value, str) and STATISTICAL_TEXT_RE.search(value):
        return path
    return None


def check(root: Path) -> list[str]:
    errors: list[str] = []

    spec_json_path = root / SPEC_JSON
    statement_json_path = root / STATEMENT_JSON
    spec_md_path = root / SPEC_MD
    statement_md_path = root / STATEMENT_MD
    for path, label in (
        (spec_json_path, SPEC_JSON),
        (statement_json_path, STATEMENT_JSON),
        (spec_md_path, SPEC_MD),
        (statement_md_path, STATEMENT_MD),
    ):
        if not path.is_file():
            errors.append(f"{label}: missing")
    if errors:
        return errors

    try:
        spec_doc = json.loads(spec_json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{SPEC_JSON}: not readable JSON ({exc})"]
    try:
        statement_doc = json.loads(statement_json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{STATEMENT_JSON}: not readable JSON ({exc})"]
    if not isinstance(spec_doc, dict):
        return [f"{SPEC_JSON}: must be a JSON object"]
    if not isinstance(statement_doc, dict):
        return [f"{STATEMENT_JSON}: must be a JSON object"]

    # --- spec companion: ratified, ids-only rows -------------------------
    status = spec_doc.get("status")
    if not (isinstance(status, str) and status.strip().lower() == "ratified"):
        errors.append(
            f"{SPEC_JSON}: status must be the string 'ratified' (grader refusal "
            f"not_applicable_spec_unratified), got {status!r}"
        )
    spec_rows = spec_doc.get("rows")
    if not isinstance(spec_rows, list) or not spec_rows:
        return errors + [
            f"{SPEC_JSON}: 'rows' must be a non-empty list "
            "(the cited spec has no rows otherwise)"
        ]
    spec_ids: list[str] = []
    for index, row in enumerate(spec_rows):
        if not isinstance(row, dict):
            errors.append(f"{SPEC_JSON}: rows[{index}] must be an object")
            continue
        row_id = _str_or_none(row.get("id"))
        if row_id is None:
            errors.append(
                f"{SPEC_JSON}: rows[{index}] needs a non-empty string 'id'"
            )
            continue
        extra = sorted(set(row) - {"id"})
        if extra:
            errors.append(
                f"{SPEC_JSON}: rows[{index}] ({row_id}) carries keys beyond "
                f"'id' ({', '.join(extra)}) -- spec rows are ids only, never "
                "titles or prose: the grader's statistical scan refuses a row "
                "that mentions accuracy, matching, offset, yield, sigma or "
                "Monte Carlo, and row 10 is titled 'UART bit-timing accuracy'"
            )
        hit = scan_statistical(row, f"rows[{index}]")
        if hit is not None:
            errors.append(
                f"{SPEC_JSON}: rows[{index}] ({row_id}) looks statistical at "
                f"{hit or 'id'} -- the grader refuses the whole item for this"
            )
        spec_ids.append(row_id)
    if len(set(spec_ids)) != len(spec_ids):
        errors.append(f"{SPEC_JSON}: duplicate row ids")

    # --- statement: shape, class scan, exact coverage --------------------
    statement_rows = statement_doc.get("rows")
    if not isinstance(statement_rows, list) or not statement_rows:
        return errors + [
            f"{STATEMENT_JSON}: 'rows' must be a non-empty list of "
            "{id, class, reason} objects"
        ]
    statement_ids: list[str] = []
    for index, row in enumerate(statement_rows):
        if not isinstance(row, dict):
            errors.append(f"{STATEMENT_JSON}: rows[{index}] must be an object")
            continue
        row_id = _str_or_none(row.get("id"))
        row_class = _str_or_none(row.get("class"))
        row_reason = _str_or_none(row.get("reason"))
        if row_id is None:
            errors.append(
                f"{STATEMENT_JSON}: rows[{index}] needs a non-empty string 'id'"
            )
            continue
        if row_class is None or row_reason is None:
            errors.append(
                f"{STATEMENT_JSON}: rows[{index}] ({row_id}) needs non-empty "
                "string 'class' and 'reason' (grader refusal "
                "not_applicable_statement_incomplete)"
            )
            continue
        if STATISTICAL_TEXT_RE.search(row_class):
            errors.append(
                f"{STATEMENT_JSON}: rows[{index}] ({row_id}) class "
                f"{row_class!r} trips the grader's statistical scan "
                "(not_applicable_statistical_row) -- rename the class"
            )
        statement_ids.append(row_id)
    uncovered = [rid for rid in spec_ids if rid not in statement_ids]
    unknown = [rid for rid in statement_ids if rid not in spec_ids]
    if len(set(statement_ids)) != len(statement_ids):
        errors.append(f"{STATEMENT_JSON}: duplicate row ids")
    if uncovered or unknown:
        errors.append(
            f"{STATEMENT_JSON}: statement must account for exactly the spec "
            f"companion's rows -- uncovered ids {uncovered}, unknown ids "
            f"{unknown} (grader refusal not_applicable_statement_incomplete)"
        )
    not_covered = statement_doc.get("not_covered", [])
    if not isinstance(not_covered, list):
        errors.append(f"{STATEMENT_JSON}: 'not_covered' must be a list")
        not_covered = []
    for index, row in enumerate(not_covered):
        if not isinstance(row, dict) or _str_or_none(row.get("id")) is None:
            errors.append(
                f"{STATEMENT_JSON}: not_covered[{index}] needs a string 'id'"
            )
            continue
        if row["id"] in spec_ids:
            errors.append(
                f"{STATEMENT_JSON}: not_covered[{index}] ({row['id']}) is "
                "ratified in the spec companion -- it belongs in 'rows'"
            )

    # --- hash binding: the embeds must match the markdowns on disk ------
    spec_md_hash = sha256_hex(spec_md_path)
    statement_md_hash = sha256_hex(statement_md_path)
    spec_embed = spec_doc.get("source_content_hash")
    if spec_embed != spec_md_hash:
        errors.append(
            f"{SPEC_JSON}: source_content_hash is {spec_embed!r} but "
            f"{SPEC_MD} now hashes to {spec_md_hash} -- the spec markdown "
            "moved under the claim; update the companions and re-mint the "
            "signoff baseline"
        )
    statement_spec_embed = statement_doc.get("spec_markdown_content_hash")
    if statement_spec_embed != spec_md_hash:
        errors.append(
            f"{STATEMENT_JSON}: spec_markdown_content_hash is "
            f"{statement_spec_embed!r} but {SPEC_MD} now hashes to "
            f"{spec_md_hash} -- update the companions and re-mint"
        )
    if spec_embed is not None and statement_spec_embed is not None:
        if spec_embed != statement_spec_embed:
            errors.append(
                f"{STATEMENT_JSON}: spec_markdown_content_hash "
                f"({statement_spec_embed!r}) disagrees with {SPEC_JSON}'s "
                f"source_content_hash ({spec_embed!r})"
            )
    statement_embed = statement_doc.get("statement_content_hash")
    if statement_embed != statement_md_hash:
        errors.append(
            f"{STATEMENT_JSON}: statement_content_hash is {statement_embed!r} "
            f"but {STATEMENT_MD} now hashes to {statement_md_hash} -- the "
            "statement markdown moved; update the embed and re-mint"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    errors = check(args.repo_root)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        print(
            f"{len(errors)} error(s) in the item 6 not-applicable claim "
            "(spec/statistical-claims-na.md and its JSON companions)",
            file=sys.stderr,
        )
        return 1
    print(
        "item 6 not-applicable claim consistent: JSON companions parse, "
        "cover the ratified rows exactly, and their embedded hashes match "
        "spec/target-spec.md and spec/statistical-claims-na.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
