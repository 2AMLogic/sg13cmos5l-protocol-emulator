#!/usr/bin/env bash
# scripts/signoff-report.sh -- the single entry point for rendering this
# block's `klt signoff` tier-verdict report (issue #16).
#
# Runs the pinned invocation
#
#   klt signoff --manifest manifests/sg13cmos5l-protocol-emulator.json \
#               --format json
#
# from the repo root (evidence paths inside the manifest are cwd-relative,
# so the runner -- not the caller -- owns the working directory). The
# rendered report is the verdict of record for this block's T1 state once
# committed as an evidence record under
# verification/records/signoff-baseline/ (see manifests/README.md).
#
# It does NOT gate on a klt version. Until 2026-11-14 it refused to run
# unless `klt version --format json`'s git_commit equalled
# `layout/toolchain.json`'s `klt_last_verified_commit`; the 2026-11-09
# operator ruling (2AMLogic/2am#7038) retired both the repo-level pin and
# that check -- a record keeps the version that produced it, and signoff
# stops checking a record against a repo pin (issue #371). The grading
# build's full identity is printed to stderr and travels in the rendered
# report's build block instead.
#
# No `--tiers-doc` override: the provisioned `klt` bundles its own copy of `docs/design-evidence-tiers.md` with all eleven
# T1 items (issue #52 retired the vendored `manifests/design-evidence-tiers.md`
# once the pin moved past the checklist's item-11 addition -- see
# manifests/README.md's "The vendored tiers doc" section for the history and
# retirement record).
#
# Exit codes:
#   0  Report rendered (klt exitted 0 = every item met, or 3 = at least one
#      unmet -- see manifests/README.md's "Exit-code semantics" for why an
#      all-unmet render is the normal gap state, not an error). With
#      --check-latest: the latest committed record also still reproduces
#      (`klt signoff --check` reported status "match" -- the grader re-graded
#      the manifest and found nothing outside the build-identity block
#      moved, so the same pinned commit verifies from any provisioning
#      route; klayout-tools #2249/#2258).
#   1  Real failure: klt missing / `signoff` missing from its subcommand
#      list; klt exitted 1 or 2 (usage or
#      error); no signoff-baseline record committed; or --check-latest
#      found a drift (`klt signoff --check` exitted 3, status "drifted":
#      a graded field outside the build block -- item status/reason,
#      citation hash, t1_met_count, ... -- moved since the committed
#      report; the exact "fails rather than rotting" case that check
#      exists for). NOTE the exit-code trap: 3 means OPPOSITE things in
#      the two modes -- render mode's 3 is the normal all-unmet gap state
#      mapped to success above, but --check mode's 3 is DRIFT and a hard
#      failure. The two mappings are kept separate below on purpose.
#
# Usage:
#   scripts/signoff-report.sh                 # render to stdout (JSON)
#   scripts/signoff-report.sh --out FILE     # write the JSON report to FILE
#   scripts/signoff-report.sh --check-latest # re-grade and verify against
#                                            # the latest evidence record's
#                                            # committed artifact via
#                                            # `klt signoff --check` (the
#                                            # grader's own comparison, not
#                                            # a byte-compare)
#
# klt resolution: `klt` from $PATH unless $KLT_BIN names another binary
# (used by environments that provision the pinned klt in an isolated
# `uv tool` dir). Provisioning the pin is scripts/setup-env.sh's job; this
# script deliberately does not install anything.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

MANIFEST="manifests/sg13cmos5l-protocol-emulator.json"
RECORDS_GLOB="verification/records/signoff-baseline/records/*.md"

OUT=""
CHECK_LATEST=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)
      [[ $# -ge 2 ]] || { echo "error: --out requires a value" >&2; exit 1; }
      OUT="$2"; shift 2 ;;
    --check-latest)
      CHECK_LATEST=1; shift ;;
    -h|--help)
      sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)
      echo "error: unknown argument '$1' (see --help)" >&2; exit 1 ;;
  esac
done

KLT_BIN="${KLT_BIN:-klt}"

if ! command -v "$KLT_BIN" >/dev/null 2>&1; then
  echo "error: '$KLT_BIN' not found on \$PATH. Provision the pinned klt first: ./scripts/setup-env.sh" >&2
  exit 1
fi

# --- producer identity: RECORDED, not asserted (issue #371) ---
# This used to be a gate: it read `klt_last_verified_commit` from
# layout/toolchain.json and exitted 1 unless `klt version --format json`'s
# git_commit matched it exactly. The 2026-11-09 operator ruling
# (2AMLogic/2am#7038) retires that check along with the per-repo pin -- rule 2
# is that an evidence record keeps the klayout-tools version that produced it,
# and signoff stops checking that a record matches a repo pin. So the grading
# build's identity is now REPORTED here (and carried into the rendered
# report's own build block, which `klt signoff --check` excludes from the
# comparison) rather than used to refuse the run. A release that actually
# moves a graded field is still caught -- by --check-latest's drift
# comparison, which names the field, instead of by a version mismatch that
# pre-empted it.
if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 required to read '$KLT_BIN version --format json'" >&2
  exit 1
fi
GRADER_ID="$(python3 -c "
import json, subprocess, sys
out = subprocess.run(['$KLT_BIN', 'version', '--format', 'json'], capture_output=True, text=True)
try:
    doc = json.loads(out.stdout)
except Exception:
    sys.exit(1)
print('version {} (git_commit {}, tag {}, is_release {}, grading_ruleset_id {})'.format(
    doc.get('version', '?'),
    doc.get('git_commit', '?'),
    doc.get('git_tag') or 'none',
    doc.get('is_release', '?'),
    doc.get('grading_ruleset_id', '?'),
))
")" || { echo "error: could not read '$KLT_BIN version --format json'" >&2; exit 1; }
echo "-- grading klt: $GRADER_ID" >&2

# --- capability check: layout/toolchain.json's own drift-detect pattern ---
if ! "$KLT_BIN" --help 2>&1 | grep -q "signoff"; then
  echo "error: '$KLT_BIN' does not list a 'signoff' subcommand (the provisioned build is missing a capability layout/toolchain.json's klt_required_commands names). Provisioned build: $GRADER_ID" >&2
  exit 1
fi

# --- grade ---
FRESH="$(mktemp)"
trap 'rm -f "$FRESH"' EXIT
set +e
"$KLT_BIN" signoff --manifest "$MANIFEST" --format json >"$FRESH"
KLT_RC=$?
set -e

case "$KLT_RC" in
  0|3) ;; # rendered; the tier/status payload itself is the verdict (3 = at least one unmet)
  1|2)
    echo "error: klt signoff exitted $KLT_RC (see stderr above or manifests/README.md's exit-code table)." >&2
    exit 1 ;;
  *)
    echo "error: klt signoff exitted $KLT_RC (unknown)." >&2
    exit 1 ;;
esac

echo "klt signoff rendered OK (exit $KLT_RC; grader: $GRADER_ID)" >&2

if [[ -n "$OUT" ]]; then
  cp "$FRESH" "$OUT"
fi

if [[ "$CHECK_LATEST" -eq 1 ]]; then
  LATEST_RECORD="$(git ls-files -- "$RECORDS_GLOB" | sort | tail -1)"
  if [[ -z "$LATEST_RECORD" ]]; then
    echo "error: no signoff-baseline evidence record committed under verification/records/signoff-baseline/ -- render one (see manifests/README.md) and commit it before checking." >&2
    exit 1
  fi
  RECORD_ID="$(basename "$LATEST_RECORD" .md)"
  COMMITTED="verification/records/signoff-baseline/artifacts/$RECORD_ID/signoff-report.json"
  if [[ ! -f "$COMMITTED" ]]; then
    echo "error: latest record $RECORD_ID has no committed report artifact at $COMMITTED." >&2
    exit 1
  fi
  # The grader's own comparison (klt signoff --check, klayout-tools #2258):
  # re-grades the manifest and diffs the fresh result against the committed
  # report EXCLUDING the build-identity block, so two legitimate installs of
  # the same pinned commit -- one clean-tree, one whose build stamped .dirty
  # -- both verify (the byte-compare this replaces failed on exactly that
  # provisioning-route difference, #2249). Exit-code trap: under --check,
  # klt's 0 = "match", 3 = "drifted" (a graded field outside build moved),
  # 1/2 = missing/unparseable committed report or real error. The render
  # mode's `0|3) ;;` mapping above MUST NOT be reused here: --check's 3 is
  # drift, a hard failure -- mapping it to success would leave this gate
  # permanently green and blind to the manifest rot it exists to catch.
  CHECK_OUT="$(mktemp)"
  set +e
  "$KLT_BIN" signoff --manifest "$MANIFEST" --format json \
    --check "$COMMITTED" >"$CHECK_OUT"
  CHECK_RC=$?
  set -e
  case "$CHECK_RC" in
    0)
      echo "report matches the latest committed record ($RECORD_ID) -- no drift (klt signoff --check: status match; grader build identity excluded from the comparison)." >&2
      ;;
    3)
      echo "error: the committed signoff report no longer reproduces (klt signoff --check: status drifted, artifact $COMMITTED)." >&2
      echo "  A graded field outside the build block changed without a fresh" >&2
      echo "  signoff-baseline record. Re-render (scripts/signoff-report.sh --out), mint a new" >&2
      echo "  append-only record superseding $RECORD_ID, and commit it with the change." >&2
      python3 - "$CHECK_OUT" <<'PYDRIFT' >&2 || true
import json, sys
with open(sys.argv[1]) as f:
    envelope = json.load(f)
for d in envelope.get("drift", []):
    print(f"  drifted: {d.get('field')}: committed={d.get('committed')!r} fresh={d.get('fresh')!r}")
PYDRIFT
      rm -f "$CHECK_OUT"
      exit 1
      ;;
    *)
      echo "error: klt signoff --check exitted $CHECK_RC (missing/unparseable committed report, or a real error -- see stderr above)." >&2
      rm -f "$CHECK_OUT"
      exit 1
      ;;
  esac
  rm -f "$CHECK_OUT"
fi

if [[ -z "$OUT" ]]; then
  cat "$FRESH"
fi
