#!/usr/bin/env bash
# scripts/setup-env.sh — provision the local environment for verification/'s
# klt-driven cocotb harness.
#
# Ported from 2AMLogic/sky130-modexp's scripts/setup-env.sh (this program's
# first digital canary, per CLAUDE.md's "Harness bootstrap" section) and
# adapted for this repo (issue #6):
#
#   1. Installs `klayout-tools` (`klt`) as a `uv tool`, together with
#      pinned cocotb/cocotb-tools versions, in one shot -- at the exact
#      commit `layout/toolchain.json`'s `klt_install` field already
#      records for the layout/ DRC/LVS flow, not a second, independently
#      chosen pin. This replaces the ad hoc `uv tool install --with cocotb
#      --with cocotb-tools klayout-tools` workaround previously documented
#      in verification/README.md.
#   2. Resolves the `ihp-sg13cmos5l` PDK location via `klt pdk find` --
#      this program's own shared PDK_ROOT resolver, which every downstream
#      layout/flow tool already imports instead of re-deriving the lookup
#      itself (see `klt pdk find --help`). sky130-modexp fetches its PDK
#      (sky130A) via `volare`; IHP SG13 PDKs have no volare equivalent, so
#      this script documents/reports what `klt pdk find` resolves rather
#      than fetching a copy itself. See docs/environment.md for the full
#      picture, including why this repo currently has more than one
#      PDK_ROOT convention in play.
#   3. Reports -- with an actionable message, never a Python traceback --
#      which of `iverilog`, `yosys`, `openroad` are missing from `$PATH`.
#
# Exit codes:
#   0  klt + cocotb/cocotb-tools provisioned; `klt functional-verification
#      verification/request-protocol-emulator.json --format json` should
#      now succeed (it needs Icarus + cocotb only, no PDK). The PDK
#      resolution and iverilog/yosys/openroad checks are reported but
#      non-fatal -- see their own output for what, if anything, is still
#      missing.
#   1  `uv` is missing, layout/toolchain.json can't be read, or the
#      `uv tool install` for klt/cocotb/cocotb-tools failed.
#
# Usage:
#   ./scripts/setup-env.sh
#   ./scripts/setup-env.sh --help
#
# This is a local-dev convenience/pin tool, not a CI dependency: ci.yml
# deliberately excludes the PDK-heavy legs (klt synthesize, klt
# functional-verification) -- those are run locally and their results
# recorded as append-only evidence under verification/records/. Do not wire
# this script into ci.yml/test.yaml/gds.yaml.
#
# Pinned versions are recorded in docs/environment.md -- update both
# together if you re-pin (klt's own pin lives in layout/toolchain.json;
# this script reads it from there rather than duplicating it).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLCHAIN_JSON="$REPO_ROOT/layout/toolchain.json"

# --- pinned cocotb/cocotb-tools versions -- keep in sync with
# docs/environment.md. klt's own pin is read live from
# layout/toolchain.json (single source of truth shared with the layout/
# DRC/LVS flow) rather than duplicated here.
COCOTB_VERSION="2.1.0"
COCOTB_TOOLS_VERSION="0.1.0"
# ----------------------------------------------------------------------------

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,39p' "${BASH_SOURCE[0]}"
  exit 0
fi

echo "== sg13cmos5l-protocol-emulator: verification/ environment setup =="
echo

# ---------------------------------------------------------------------------
# 1. klt + cocotb/cocotb-tools, pinned to layout/toolchain.json's klt_install
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' is not on \$PATH." >&2
  echo "  Fix: install uv first -- https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [[ ! -f "$TOOLCHAIN_JSON" ]]; then
  echo "ERROR: $TOOLCHAIN_JSON not found -- cannot determine the pinned klt commit." >&2
  exit 1
fi

KLT_INSTALL="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    doc = json.load(f)
print(doc['klt_install'])
" "$TOOLCHAIN_JSON")"

if [[ -z "$KLT_INSTALL" || "$KLT_INSTALL" != git+* ]]; then
  echo "ERROR: layout/toolchain.json's klt_install ('$KLT_INSTALL') is not a pinned VCS URL (expected 'git+https://...@<sha>')." >&2
  echo "  Fix: check layout/toolchain.json -- klt_install must never be a floating branch reference." >&2
  exit 1
fi

echo "-- klt + cocotb==$COCOTB_VERSION + cocotb-tools==$COCOTB_TOOLS_VERSION (pinned via layout/toolchain.json)"
echo "   klt_install: $KLT_INSTALL"
if ! uv tool install --force \
    --with "cocotb==$COCOTB_VERSION" \
    --with "cocotb-tools==$COCOTB_TOOLS_VERSION" \
    "$KLT_INSTALL"; then
  echo "ERROR: 'uv tool install' failed for klayout-tools/cocotb/cocotb-tools." >&2
  echo "  Common causes: no network access to the klt git remote, or no C/C++" >&2
  echo "  toolchain for a dependency's native build." >&2
  echo "  Re-run with the same command for a full traceback:" >&2
  echo "    uv tool install --force --with cocotb==$COCOTB_VERSION --with cocotb-tools==$COCOTB_TOOLS_VERSION \"$KLT_INSTALL\"" >&2
  exit 1
fi

echo
if ! command -v klt >/dev/null 2>&1; then
  echo "ERROR: 'klt' not found on \$PATH after install." >&2
  echo "  Fix: check the 'uv tool install' output above, and confirm uv's tool bin dir is on \$PATH (run: uv tool update-shell)." >&2
  exit 1
fi
echo "-- klt version: $(klt --version)"

# ---------------------------------------------------------------------------
# 2. $PDK_ROOT resolution for ihp-sg13cmos5l
# ---------------------------------------------------------------------------
echo
echo "-- Resolving \$PDK_ROOT for ihp-sg13cmos5l ..."
if PDK_INFO="$(klt pdk find --pdk ihp-sg13cmos5l --format json 2>/dev/null)"; then
  PDK_ROOT_RESOLVED="$(python3 -c "import json,sys; print(json.load(sys.stdin)['root'])" <<<"$PDK_INFO")"
  RESOLVED_VIA="$(python3 -c "import json,sys; print(json.load(sys.stdin)['resolved_via'])" <<<"$PDK_INFO")"
  PDK_VERSION="$(python3 -c "import json,sys; print(json.load(sys.stdin).get('version') or 'unknown (no version stamp recorded at this install)')" <<<"$PDK_INFO")"
  echo "   Found: PDK_ROOT=$PDK_ROOT_RESOLVED"
  echo "   Resolved via: $RESOLVED_VIA"
  echo "   Version: $PDK_VERSION"
  echo
  echo "   To use it in your shell:"
  echo "     export PDK_ROOT=$PDK_ROOT_RESOLVED"
else
  cat >&2 <<'PDKMSG'
   NOT FOUND: no ihp-sg13cmos5l PDK install resolved.

   `klt pdk find` checked $PDK_ROOT, $PDK, and its usual search roots
   (e.g. ~/.volare, ~/share/pdk -- see `klt pdk find --help` /
   `klt pdk list --format json` for the full search order) and found
   nothing.

   This repo's PDK is IHP SG13CMOS5L, which is not distributed via volare
   (sky130-modexp's PDK mechanism -- there is no IHP equivalent). Two ways
   to get it:

     1. Local dev: obtain a pre-built ihp-sg13cmos5l install (this repo's
        own CI provisions one via TinyTapeout/tt-gds-action's
        install_sg13cmos5l.sh step -- see .github/workflows/gds.yaml and
        layout/README.md's "Former blocker" section for that mechanism),
        then point PDK_ROOT at its parent directory (the directory that
        directly CONTAINS an `ihp-sg13cmos5l/` subdirectory), e.g.:
            export PDK_ROOT=/path/to/pdk-root
     2. CI: the `gds` GitHub Actions workflow provisions the PDK itself via
        TinyTapeout/tt-gds-action@ihp-cmos5l -- no local PDK_ROOT is needed
        there, and this script is not (and should not be) wired into that
        workflow.

   See docs/environment.md for the full picture, including why this repo
   currently has more than one PDK_ROOT convention documented
   (.devcontainer/Dockerfile's own PDK_ROOT vs. this script's klt-pdk-find
   convention).

   Continuing without a resolved PDK: `klt functional-verification`
   (Icarus-only, no PDK dependency) does not need one, but
   flow/run_synthesize_direct_yosys.py and any future layout/ DRC/LVS run
   do.
PDKMSG
fi

# ---------------------------------------------------------------------------
# 3. Simulator/flow toolchain on $PATH
# ---------------------------------------------------------------------------
echo
echo "-- Checking simulator/flow tools on \$PATH ..."
MISSING=()
for tool in iverilog yosys openroad; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "   OK: $tool -> $(command -v "$tool")"
  else
    MISSING+=("$tool")
  fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo
  echo "   MISSING from \$PATH: ${MISSING[*]}" >&2
  for tool in "${MISSING[@]}"; do
    case "$tool" in
      iverilog)
        echo "     - iverilog (Icarus Verilog): required by 'klt functional-verification' (engine: icarus, the default) and by 'npm run test' (test/Makefile)." >&2
        echo "       Fix: apt-get install iverilog   (or see https://steveicarus.github.io/iverilog/usage/installation.html)" >&2
        ;;
      yosys)
        echo "     - yosys: required by flow/run_synthesize_direct_yosys.py (and future 'klt synthesize' runs, once the liberty-naming gap tracked at 2AMLogic/klayout-tools#1786 is fixed)." >&2
        echo "       Fix: see https://github.com/YosysHQ/yosys#installation" >&2
        ;;
      openroad)
        echo "     - openroad: required by any future place-and-route leg of flow/ (this program's own flow, distinct from the Tiny Tapeout LibreLane flow which bundles its own OpenROAD)." >&2
        echo "       Fix: see https://github.com/The-OpenROAD-Project/OpenROAD#installation" >&2
        ;;
    esac
  done
else
  echo "   All of iverilog, yosys, openroad found on \$PATH."
fi

echo
echo "== Done. See docs/environment.md for the full pinned-version record. =="
