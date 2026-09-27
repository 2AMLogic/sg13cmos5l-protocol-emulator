#!/usr/bin/env bash
#
# flow/_klt.sh -- shared `klt`-bootstrap helpers for the flow/ bash runners
# (`run-sta-corner-sweep.sh`, `run-die-area-par.sh`, `run-post-layout-sdf.sh`).
#
# SOURCE THIS FILE; DO NOT EXECUTE IT. It defines functions and expects the
# caller's own `set -euo pipefail` to be already in effect -- it does not set
# its own, and it has no `main`. A caller sources it after its own
# `REPO_ROOT`/`set -euo pipefail` lines, then calls the functions below in
# whatever order/subset it needs:
#
#   source "${FLOW_DIR}/_klt.sh"
#   klt_resolve                                  # sets $KLT
#   klt_require_verbs "functional-verification"  # optional, FATAL if missing
#   klt_export_pdk_root "ihp-sg13cmos5l"          # sets/exports PDK_ROOT, PDK_ARGS
#   NETLIST_ABS="$(klt_response_path "$response_json" netlist_path)"
#
# Consolidated out of the three runners per issue #47 -- see that issue for
# the byte-identical duplication this replaces. Every FATAL message and exit
# code below is preserved verbatim from the runner it was copied out of, so
# sourcing this file changes no observable behavior of any of the three
# runners except where `klt_export_pdk_root`'s exporting choice below is
# called out explicitly.
#
# Deliberately NOT used by flow/run-sram-macro-feasibility.py (Python; a bash
# helper cannot serve it -- its own `klt_bin()`/`assert_klt_commands()` stay
# where they are) or flow/run_synthesize_direct_yosys.py (historical
# stopgap, off the active path -- see flow/README.md; owned by issue #32).

# --- klt_resolve -------------------------------------------------------
# Sets the global $KLT from ${KLT_BIN:-klt}. FATALs (exit 1) if the
# resolved binary is not on $PATH -- identical message/exit code to what
# all three runners inlined before this consolidation.
klt_resolve() {
  KLT="${KLT_BIN:-klt}"
  if ! command -v "$KLT" >/dev/null 2>&1; then
    echo "FATAL: klt ('$KLT') not found on \$PATH -- run scripts/setup-env.sh or set KLT_BIN." >&2
    exit 1
  fi
}

# --- klt_require_verbs ---------------------------------------------------
# klt_require_verbs <verb> [<verb> ...]
# For each <verb>, FATALs (exit 1) naming the missing verb if `klt --help`
# does not list it -- the layout/toolchain.json `klt_required_commands`
# contract: a missing verb is a tooling error every runner that needs it
# must fail loudly on, never skip silently. Requires $KLT to already be set
# (call klt_resolve first). Previously only run-post-layout-sdf.sh performed
# this check (for "functional-verification"); the other two runners did not
# call the equivalent check for their own verbs (`sta` / `place-and-route`)
# before this consolidation and still don't call klt_require_verbs today --
# adding it to those runners was not in issue #47's scope (would add a new
# check where none existed, which is a behavior change, not a pure
# extraction). The function exists here so a future runner (or a future pass
# adding the check to the existing two) has one implementation to call.
klt_require_verbs() {
  local verb
  for verb in "$@"; do
    if ! "$KLT" --help 2>/dev/null | grep -q "$verb"; then
      echo "FATAL: '$KLT --help' does not list '$verb' -- the install at '$KLT' lacks the verb this runner needs (layout/toolchain.json's klt_required_commands contract)." >&2
      exit 1
    fi
  done
}

# --- klt_export_pdk_root -------------------------------------------------
# klt_export_pdk_root <pdk-variant>
# Resolves <pdk-variant> via `klt pdk find --format json`, sets
# $PDK_ROOT_RESOLVED, exports $PDK_ROOT to the same value, and sets the
# global array $PDK_ARGS to `(--pdk <pdk-variant>)`. Requires $KLT to
# already be set (call klt_resolve first).
#
# Why exported even when klt itself can resolve the PDK without it: the
# openroad docker wrapper (scripts/install-openroad-docker.sh) mounts only
# $PWD and $PDK_ROOT into the container, so without the mount the
# containerized read_liberty/read_lef cannot see the PDK files. This is the
# single merged version of what run-sta-corner-sweep.sh and
# run-die-area-par.sh each said in their own words before this
# consolidation (the two comments had already drifted -- "read_liberty
# cannot see the liberty files" vs. "read_liberty/read_lef cannot see the
# PDK files" -- same mechanism, restated here once).
#
# Deliberate choice for run-post-layout-sdf.sh (2026-09-27, issue #47's
# "Verified corrections"): that runner never calls openroad (it drives
# `klt functional-verification` against Icarus, not the docker-wrapped
# OpenROAD place-and-route/sta engines) and, before this consolidation,
# resolved $PDK_ROOT_RESOLVED into a local variable ONLY -- it never
# exported PDK_ROOT. This helper always exports, so folding
# run-post-layout-sdf.sh onto it adds one new (previously-absent) export of
# PDK_ROOT into that runner's environment. That export is accepted as
# harmless rather than routed around with a resolve-only variant: nothing
# downstream in run-post-layout-sdf.sh reads $PDK_ROOT for a mount decision
# (there is no docker wrapper on its path), and `klt functional-verification`
# resolves the PDK itself via `klt pdk find`, independent of whether
# $PDK_ROOT happens to be exported in its parent shell. A single shared
# function that always exports is simpler to keep in sync than a
# resolve-only/export variant pair for a difference with no observed
# consequence; if a future runner's environment turns out to be sensitive to
# an incidental PDK_ROOT export, split the variant then rather than
# preemptively here.
klt_export_pdk_root() {
  local pdk_variant="$1"
  PDK_ROOT_RESOLVED="$("$KLT" pdk find --pdk "$pdk_variant" --format json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["root"])')"
  export PDK_ROOT="$PDK_ROOT_RESOLVED"
  PDK_ARGS=(--pdk "$pdk_variant")
}

# --- klt_response_path ----------------------------------------------------
# klt_response_path <response.json> <field>
# Prints the value of top-level <field> in the klt JSON response at
# <response.json>, unwrapping the `{"path": ..., "scope": ...}` envelope to
# its "path" member if <field>'s value is an object rather than a bare
# string.
#
# This is the ONE place in this repo that names 2AMLogic/klayout-tools#2073
# (the two-shape output-artifact-path-field contract that envelope came
# from). Findings, recorded once here rather than re-derived at each call
# site:
#
#   - #2073 closed upstream 2026-09-18 via klayout-tools PR #2081, which is
#     DOCUMENTATION-ONLY ("no code/behavior changes"; see the PR body).
#     klayout-tools deliberately chose "Option 3: document the mixed state"
#     over finishing the envelope migration -- the issue itself frames the
#     three options and states the maintainers' reasoning for not picking
#     Option 1 (finishing the migration is a breaking change for every
#     existing plain-string consumer, including `place-and-route`'s own
#     `def_path` input to `sta`). So #2073 closing is NOT a signal that the
#     `{path, scope}` envelope on `synthesize`'s `netlist_path` (the field
#     every call site in this repo unwraps) was retired, replaced, or is
#     going away -- it is confirmation that the envelope is the PERMANENT,
#     intentional shape for that field, and that `place-and-route`'s own
#     path fields (`def_path`/`gds_path`/`verilog_path`) are separately and
#     equally permanently plain strings. The unwrap this function performs
#     is therefore not a stopgap with a retirement date; it is the correct
#     long-term handling of a two-shape contract klayout-tools has
#     explicitly decided to keep. Do not remove the `isinstance` check on
#     the strength of #2073's closure -- there is no such finding to act on.
#   - Whether this repo's own klt pin (layout/toolchain.json's
#     `klt_last_verified_commit`, 1d964cf4ed93b15... as of 2026-09-21) is
#     before or after #2081's merge (2026-09-18, commit 75691225d5bd) is
#     moot given the above: since #2081 changed no code, being on either
#     side of it cannot change what shape `synthesize.netlist_path` reports.
#     No further pin-side verification of this specific question is needed.
#
# Does NOT check the resolved path exists, retry it as repo-root-relative,
# or FATAL -- callers that need that behavior (the two `klt synthesize` ->
# netlist resolution call sites) do it themselves with this function's
# printed value, exactly as each did inline before this consolidation.
klt_response_path() {
  local response_path="$1" field="$2"
  python3 - "$response_path" "$field" <<'PYEOF'
import json
import sys

response_path, field = sys.argv[1], sys.argv[2]
with open(response_path, encoding="utf-8") as handle:
    value = json.load(handle)[field]
if isinstance(value, dict):
    value = value["path"]   # {path, scope} envelope (klt issue #2073)
print(value)
PYEOF
}
