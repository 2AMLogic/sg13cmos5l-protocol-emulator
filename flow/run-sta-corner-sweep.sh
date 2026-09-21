#!/usr/bin/env bash
#
# flow/run-sta-corner-sweep.sh -- run a standalone multi-corner static
# timing analysis (`klt sta`, verilog mode) over **one freshly synthesized
# gate-level netlist** of the current top, at every `sg13cmos5l_stdcell`
# liberty corner the IHP SG13CMOS5L PDK ships, and collect each run's
# timing/power metrics into one JSON summary.
#
# Ported from 2AMLogic/sky130-modexp's flow/run-sta-corner-sweep.sh per
# CLAUDE.md's "Harness bootstrap" section (issue #20), adapted where this
# repo's flow genuinely differs:
#
#   - sky130-modexp sweeps a *committed routed DEF* (`layout/modexp.def`);
#     this repo has no place-and-route leg yet, so the swept artifact is
#     instead the **synthesized gate-level netlist** the `klt synthesize`
#     leg of this flow produces. That makes every number this script
#     reports a `geometry_source: "netlist_estimate"` number -- cell
#     delays plus the liberty's own default wire-load model (`"1k"`, mode
#     `"top"`), never real routing parasitics. When a routed DEF exists,
#     switch the request to `def` mode; until then, no number from this
#     script may be cited as a routed-timing claim.
#   - All corner set: the full six-corner `sg13cmos5l_stdcell` liberty
#     matrix the PDK ships (2 fast, 2 typical, 2 slow -- enumerated below).
#     This sweep IS the corner-set declaration for target-spec row 4 / T1
#     checklist item 5 ("multi-corner static timing analysis, setup and
#     hold across the PVT corner set"): the set this block is held to is
#     the PDK's own shipped set, pending the spec's own ratification
#     machinery (issue #17) folding it into a decision record.
#   - One fixed netlist, N corners: the netlist is synthesized ONCE
#     (at the recipe's nominal corner, `typ_1p20V_25C`) and every corner
#     run loads the identical netlist, byte for byte. Synthesis is not
#     corner-invariant, so synthesizing once -- not per corner -- is what
#     makes this a characterization of one design rather than a sweep of
#     N different mappings (the same argument sky130-modexp's runner makes
#     for its fixed routed DEF).
#
# Why `klt sta` and not `klt place-and-route`'s in-flow STA: same reason
# as sky130-modexp (klayout-tools#1099) -- `klt place-and-route` reports
# timing as a by-product of a full implementation run, which cannot
# characterize one fixed artifact across N corners. `klt sta` never
# places, routes, or runs CTS; it loads the netlist fresh per corner.
#
# Environment requirements (docs/environment.md):
#   - `klt` on $PATH at the exact commit layout/toolchain.json pins
#     (scripts/setup-env.sh provisions it). If your ambient `klt` is
#     stale, install the pinned build somewhere and point `KLT_BIN` at
#     it -- the pinned revision must postdate
#     2AMLogic/klayout-tools#1861, which wired `klt sta`'s liberty
#     resolver to the shared single-underscore-compatible resolver
#     (older klt fails on IHP's `<library>_<corner>.lib` naming with
#     klayout-tools#1786's double-underscore error).
#   - An `openroad` binary on $PATH. On hosts where `openroad` is the
#     docker wrapper scripts/install-openroad-docker.sh generates, $PWD
#     and $PDK_ROOT are the only paths mounted into the container -- so
#     this script keeps every input path inside the repo and exports
#     PDK_ROOT for the wrapper to mount.
#   - A resolvable `ihp-sg13cmos5l` PDK (klt pdk find).
#
# Usage:
#   ./flow/run-sta-corner-sweep.sh                    # all 6 shipped corners
#   ./flow/run-sta-corner-sweep.sh slow_1p08V_125C    # a single named corner
#   KLT_BIN=.venv/bin/klt ./flow/run-sta-corner-sweep.sh
#
# Writes flow/sta-corner-sweep-results.json (gitignored; the evidence
# record under verification/records/sta-corner-sweep/artifacts/ freezes a
# copy). Exits non-zero if any individual `klt sta` run itself fails --
# negative slack is a *result*, not a run failure, and does not affect the
# exit code.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLOW_DIR="${REPO_ROOT}/flow"
REQUEST_DIR="${FLOW_DIR}/sta-corners"
NETLIST_SCRATCH="${FLOW_DIR}/sta-sweep"
RESULTS_FILE="${FLOW_DIR}/sta-corner-sweep-results.json"
SYNTH_RECIPE="${FLOW_DIR}/synthesize-protocol-emulator.json"
PDK_VARIANT="ihp-sg13cmos5l"
CELL_LIBRARY="sg13cmos5l_stdcell"
CLOCK_PORT="clk"
CLOCK_PERIOD_NS="20.0"   # 50 MHz -- the target-spec row-4 number under test
HDL_TOPLEVEL="tt_um_2amlogic_protocol_emulator"
# The liberty's own declared default wire-load model/mode
# (`default_wire_load : "1k"`, `default_wire_load_mode : "top"` in every
# sg13cmos5l_stdcell corner file) -- set explicitly so the request is
# self-describing about how interconnect was estimated in netlist mode.
WIRE_LOAD_MODEL="1k"
WIRE_LOAD_MODE="top"

# The declared corner set: every sg13cmos5l_stdcell liberty corner the
# PDK ships (setup is binding on the slow corners, hold on the fast ones).
ALL_CORNERS=(
  slow_1p08V_125C slow_1p35V_125C
  typ_1p20V_25C   typ_1p50V_25C
  fast_1p32V_m40C fast_1p65V_m40C
)

CORNERS=("$@")
if [ "${#CORNERS[@]}" -eq 0 ]; then
  CORNERS=("${ALL_CORNERS[@]}")
fi

KLT="${KLT_BIN:-klt}"
if ! command -v "$KLT" >/dev/null 2>&1; then
  echo "FATAL: klt ('$KLT') not found on \$PATH -- run scripts/setup-env.sh or set KLT_BIN." >&2
  exit 1
fi

# Export PDK_ROOT even when klt itself can resolve the PDK without it: the
# openroad docker wrapper mounts only $PWD and $PDK_ROOT, and without the
# mount the container's read_liberty cannot see the liberty files.
PDK_ROOT_RESOLVED="$("$KLT" pdk find --pdk "$PDK_VARIANT" --format json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["root"])')"
export PDK_ROOT="$PDK_ROOT_RESOLVED"
# Pin the invocation to this PDK even if $PDK points elsewhere.
PDK_ARGS=(--pdk "$PDK_VARIANT")

mkdir -p "$NETLIST_SCRATCH"

# --- Step 1: synthesize ONCE at the recipe's nominal corner -------------
# `klt synthesize` drives this itself at the pinned revision -- the
# direct-Yosys stopgap (flow/run_synthesize_direct_yosys.py, kept for the
# record) is no longer on this leg's path since klayout-tools#1786's fix
# landed (see flow/README.md).
echo "== synthesizing (nominal corner, once per sweep) ==" >&2
"$KLT" synthesize "$SYNTH_RECIPE" "${PDK_ARGS[@]}" --format json \
  > "${NETLIST_SCRATCH}/synthesize-response.json" 2> "${NETLIST_SCRATCH}/synthesize.log"
NETLIST_ABS="$(python3 - "${NETLIST_SCRATCH}/synthesize-response.json" <<'PYEOF'
import json
import sys

path = json.load(open(sys.argv[1]))["netlist_path"]
if isinstance(path, dict):
    path = path["path"]   # {path, scope} envelope (klt issue #2073)
print(path)
PYEOF
)"
if [ ! -f "$NETLIST_ABS" ]; then
  # scope "repo" paths are repo-root-relative
  NETLIST_ABS="${REPO_ROOT}/${NETLIST_ABS}"
fi
if [ ! -f "$NETLIST_ABS" ]; then
  echo "FATAL: klt synthesize reported netlist_path ${NETLIST_ABS}, which does not exist." >&2
  exit 1
fi
# Freeze the swept netlist next to the summary so the artifacts record
# copies the exact bytes every corner run loaded (they are identical
# across the sweep by construction).
NETLIST_BASENAME="$(basename "$NETLIST_ABS")"
cp "$NETLIST_ABS" "${NETLIST_SCRATCH}/${NETLIST_BASENAME}"
NETLIST_FOR_STA="${NETLIST_SCRATCH}/${NETLIST_BASENAME}"

# --- Step 2: one `klt sta` run per corner, over that one netlist --------
echo "[" > "${RESULTS_FILE}"
first=1
FAILED=0

for corner in "${CORNERS[@]}"; do
  corner_dir="${REQUEST_DIR}/${corner}"
  mkdir -p "${corner_dir}"
  request_path="${corner_dir}/sta-protocol-emulator.json"
  python3 - "$request_path" "$corner" "$NETLIST_FOR_STA" <<'PYEOF'
import json
import os
import sys

request_path, corner, netlist_abs = sys.argv[1], sys.argv[2], sys.argv[3]
request_dir = os.path.dirname(request_path)
netlist_rel = os.path.relpath(netlist_abs, request_dir)

request = {
    "schema": "klt.sta.request/1",
    "verilog": netlist_rel,
    "hdl_toplevel": "tt_um_2amlogic_protocol_emulator",
    "pdk": {"cell_library": "sg13cmos5l_stdcell", "corner": corner},
    "constraints": {
        "clock_port": "clk",
        "clock_period_ns": 20.0,
        "wire_load_model": "1k",
        "wire_load_mode": "top",
    },
}
with open(request_path, "w", encoding="utf-8") as handle:
    json.dump(request, handle, indent=2)
    handle.write("\n")
PYEOF

  echo "== ${corner} ==" >&2
  start_ts=$(date +%s)
  set +e
  "$KLT" sta "${request_path}" "${PDK_ARGS[@]}" --format json \
    > "${corner_dir}/sta-output.json" 2> "${corner_dir}/sta-output.log"
  run_rc=$?
  set -e
  end_ts=$(date +%s)
  elapsed=$((end_ts - start_ts))
  if [ "$run_rc" -eq 0 ]; then
    status="ok"
  else
    status="failed"
    FAILED=1
  fi
  echo "   status=${status} elapsed_s=${elapsed}" >&2

  if [ "$first" -eq 0 ]; then
    echo "," >> "${RESULTS_FILE}"
  fi
  first=0
  python3 - "$corner" "${corner_dir}/sta-output.json" "$status" "$elapsed" >> "${RESULTS_FILE}" <<'PYEOF'
import json
import sys

corner, output_path, status, elapsed = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    with open(output_path, encoding="utf-8") as handle:
        data = json.load(handle)
except (OSError, json.JSONDecodeError):
    data = None
entry = {"corner": corner, "run_status": status, "elapsed_s": int(elapsed), "response": data}
print(json.dumps(entry, indent=2), end="")
PYEOF
done

echo "]" >> "${RESULTS_FILE}"
python3 -c "import json; json.load(open('${RESULTS_FILE}'))" \
  && echo "wrote ${RESULTS_FILE}" >&2

if [ "$FAILED" -ne 0 ]; then
  echo "FATAL: at least one klt sta run failed -- see ${RESULTS_FILE} and the per-corner sta-output.log files under ${REQUEST_DIR}/." >&2
  exit 1
fi
