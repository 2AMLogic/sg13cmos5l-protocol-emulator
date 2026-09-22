#!/usr/bin/env bash
#
# flow/run-die-area-par.sh -- produce target-spec row 7's missing number:
# a **die area and utilization** figure from this repo's own flow, not a
# cell count. For each of the two synthesizable tops that exist today
# (the harness-bootstrap stub `src/tt_um_2amlogic_protocol_emulator.v` and
# the real-RTL program memory `rtl/protocol_program_memory.v`, issue #19),
# this runner:
#
#   1. synthesizes fresh via `klt synthesize` at the nominal corner
#      (`typ_1p20V_25C`, 20 ns / 50 MHz constraint -- same recipe pair
#      `flow/run-sta-corner-sweep.sh` uses), then
#   2. runs `klt place-and-route` on that netlist with
#      `target_stage: "place"` -- floorplan (initialize_floorplan at the
#      stated utilization) through legalized detailed placement -- which
#      is what reports `die_area_um2` / `core_area_um2` and the effective
#      `utilization_pct` (issue #21's dependency note asks for "a P&R run
#      that gets as far as a floorplan"; this run goes one stage further
#      so the utilization figure is a placed, legalized one, not just the
#      requested target), then
#   3. collects both designs' numbers plus the tile-budget arithmetic
#      into one JSON summary, `flow/die-area-par-results.json`.
#
# Tile-budget arithmetic (the constants are this experiment's own inputs,
# stated once here so every consumer cites the same source):
#   - tile pitch: ~167 x 108 um per tile per the Tiny Tapeout template's
#     own info.yaml (`spec/gap-to-submission.md` row 7, 2026-09-14 note) --
#     18,036 um^2 per tile, an order-of-magnitude figure (the template
#     states no inter-tile spacing or margin).
#   - ratified budget: target-spec row 7's "<= 2x2 tiles" = 72,144 um^2.
#   - competition maximum: 8x4 tiles = 577,152 um^2.
#
# Every number this script reports is a `klt place-and-route` /
# OpenROAD-flow number (the iteration flow of DR 0002; the docker-wrapped
# `openroad` engine). It is NOT a LibreLane number -- per CLAUDE.md's
# two-flows rule, the record that cites this summary names the flow, and
# the two are never silently interchanged.
#
# Environment requirements (docs/environment.md, flow/README.md):
#   - `klt` on $PATH at the exact commit layout/toolchain.json pins
#     (scripts/setup-env.sh provisions it). If your ambient `klt` is
#     stale, install the pinned build somewhere and point `KLT_BIN` at
#     it -- the pinned revision must postdate
#     2AMLogic/klayout-tools#1861 (single-underscore IHP liberty naming).
#   - An `openroad` binary on $PATH. On hosts where `openroad` is the
#     docker wrapper scripts/install-openroad-docker.sh generates, $PWD
#     and $PDK_ROOT are the only paths mounted into the container -- so
#     this script keeps every input path inside the repo, runs from the
#     repo root, and exports PDK_ROOT for the wrapper to mount.
#   - A resolvable `ihp-sg13cmos5l` PDK (klt pdk find).
#
# Usage:
#   ./flow/run-die-area-par.sh
#   KLT_BIN=.venv/bin/klt ./flow/run-die-area-par.sh
#
# Writes flow/die-area-par-results.json (gitignored; the evidence record
# under verification/records/die-area-baseline/artifacts/ freezes a copy).
# Exits non-zero if any individual `klt synthesize` or
# `klt place-and-route` run itself fails.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLOW_DIR="${REPO_ROOT}/flow"
SCRATCH_DIR="${FLOW_DIR}/par-scratch"
RESULTS_FILE="${FLOW_DIR}/die-area-par-results.json"
PDK_VARIANT="ihp-sg13cmos5l"
CELL_LIBRARY="sg13cmos5l_stdcell"
NOMINAL_CORNER="typ_1p20V_25C"
CLOCK_PERIOD_NS="20.0"   # 50 MHz -- matches the recipes and src/config.json
# Floorplan inputs (issue #21's stated measurement point): CoreSite is the
# standard-cell SITE both sg13cmos5l_stdcell LEFs declare; 40% utilization
# with a 1:1 aspect ratio and a 2 um core margin is a conventional
# stdcell-block starting point with routing headroom, in the same family
# as the klt worked example's 38%. The utilization choice does not change
# the tile-budget verdict -- the record derives a utilization-independent
# floor from the synthesis cell area beside this die-area figure.
UTILIZATION_PCT="40"
ASPECT_RATIO="1.0"
CORE_MARGIN_UM="2.0"
SITE="CoreSite"
IO_LAYER_H="Metal3"
IO_LAYER_V="Metal2"
SEED="1"
TARGET_STAGE="place"
# Tiny Tapeout CMOS5L tile geometry (template info.yaml; order of magnitude):
TILE_W_UM="167"
TILE_H_UM="108"

# (recipe, hdl_toplevel) pairs -- both carry a `clk` clock port.
DESIGNS=(
  "flow/synthesize-program-memory.json protocol_program_memory"
  "flow/synthesize-protocol-emulator.json tt_um_2amlogic_protocol_emulator"
)

KLT="${KLT_BIN:-klt}"
if ! command -v "$KLT" >/dev/null 2>&1; then
  echo "FATAL: klt ('$KLT') not found on \$PATH -- run scripts/setup-env.sh or set KLT_BIN." >&2
  exit 1
fi
command -v openroad >/dev/null 2>&1 || {
  echo "FATAL: openroad not found on \$PATH -- see docs/environment.md." >&2
  exit 1
}

# Export PDK_ROOT even when klt itself can resolve the PDK without it: the
# openroad docker wrapper mounts only $PWD and $PDK_ROOT, and without the
# mount the container's read_liberty/read_lef cannot see the PDK files.
PDK_ROOT_RESOLVED="$("$KLT" pdk find --pdk "$PDK_VARIANT" --format json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["root"])')"
export PDK_ROOT="$PDK_ROOT_RESOLVED"
PDK_ARGS=(--pdk "$PDK_VARIANT")

rm -rf "$SCRATCH_DIR"
mkdir -p "$SCRATCH_DIR"

TILE_AREA="$(python3 -c "print(${TILE_W_UM} * ${TILE_H_UM})")"

results="["
first=1
FAILED=0

for entry in "${DESIGNS[@]}"; do
  recipe="${entry%% *}"
  top="${entry##* }"
  slug="$(echo "$top" | tr '_' '-')"

  echo "== ${top}: synthesize (nominal corner) ==" >&2
  "$KLT" synthesize "$recipe" "${PDK_ARGS[@]}" --format json \
    > "${SCRATCH_DIR}/synthesize-${slug}-response.json" 2> "${SCRATCH_DIR}/synthesize-${slug}.log"
  NETLIST_ABS="$(python3 - "${SCRATCH_DIR}/synthesize-${slug}-response.json" <<'PYEOF'
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
  # Freeze the netlist next to the responses: every P&R number below was
  # computed from exactly these bytes.
  NETLIST_BASENAME="$(basename "$NETLIST_ABS")"
  cp "$NETLIST_ABS" "${SCRATCH_DIR}/${NETLIST_BASENAME}"

  request_path="${SCRATCH_DIR}/par-${slug}-request.json"
  python3 - "$request_path" "$top" "${SCRATCH_DIR}/${NETLIST_BASENAME}" <<'PYEOF'
import json
import os
import sys

request_path, top, netlist = sys.argv[1], sys.argv[2], sys.argv[3]
request = {
    "schema": "klt.place_and_route.request/1",
    "engine": "openroad",
    "netlist": netlist,
    "hdl_toplevel": top,
    "pdk": {"cell_library": "sg13cmos5l_stdcell", "corner": "typ_1p20V_25C"},
    "floorplan": {
        "method": "utilization",
        "utilization_pct": 40,
        "aspect_ratio": 1.0,
        "core_margin_um": 2.0,
        "site": "CoreSite",
    },
    "io": {"layer_h": "Metal3", "layer_v": "Metal2"},
    "constraints": {"clock_port": "clk", "clock_period_ns": 20.0},
    "seed": 1,
    "target_stage": "place",
}
with open(request_path, "w", encoding="utf-8") as handle:
    json.dump(request, handle, indent=2)
    handle.write("\n")
PYEOF

  echo "== ${top}: place-and-route (target_stage: ${TARGET_STAGE}) ==" >&2
  set +e
  "$KLT" place-and-route "$request_path" "${PDK_ARGS[@]}" --format json \
    > "${SCRATCH_DIR}/par-${slug}-response.json" 2> "${SCRATCH_DIR}/par-${slug}.log"
  run_rc=$?
  set -e
  if [ "$run_rc" -ne 0 ]; then
    echo "FATAL: klt place-and-route failed for ${top} (rc=${run_rc}) -- see ${SCRATCH_DIR}/par-${slug}.log" >&2
    FAILED=1
    continue
  fi

  # Fold this design's synthesis + P&R numbers plus the tile-budget
  # arithmetic into the summary.
  entry_json="$(python3 - "$SCRATCH_DIR" "$slug" "$recipe" "$TILE_AREA" <<'PYEOF'
import json
import sys

scratch, slug, recipe, tile_area = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
synth = json.load(open(f"{scratch}/synthesize-{slug}-response.json"))
par = json.load(open(f"{scratch}/par-{slug}-response.json"))
netlist_path = synth["netlist_path"]
if isinstance(netlist_path, dict):
    netlist_path = netlist_path["path"]
cell_area = synth["area_um2"]
die = par["die_area_um2"]
out = {
    "recipe": recipe,
    "hdl_toplevel": par["hdl_toplevel"],
    "synthesis": {
        "instance_count": synth["instance_count"],
        "cell_area_um2": cell_area,
        "corner": synth["provenance"]["deck"]["name"],
        "netlist_path": netlist_path,
    },
    "place_and_route": {
        "stage_reached": par["stage_reached"],
        "die_area_um2": die,
        "core_area_um2": par["core_area_um2"],
        "utilization_pct_at_stage": par["utilization_pct"],
        "requested_utilization_pct": par["stages"][0]["utilization_pct"],
        "engine_version": par["engine_version"],
        "deck_name": par["provenance"]["deck"]["name"],
    },
    "tile_budget": {
        "tile_um": [167, 108],
        "tile_area_um2": tile_area,
        "budget_2x2_um2": 4 * tile_area,
        "competition_max_8x4_um2": 32 * tile_area,
        "cell_area_vs_2x2_budget": round(cell_area / (4 * tile_area), 4),
        "die_area_vs_2x2_budget": round(die / (4 * tile_area), 4),
        "die_area_tile_equivalents": round(die / tile_area, 2),
        "min_tiles_at_100pct_utilization": -(-cell_area // tile_area),
    },
}
print(json.dumps(out))
PYEOF
)"
  if [ "$first" -eq 1 ]; then
    first=0
  else
    results+=","
  fi
  results+="$entry_json"
done

results+="]"
python3 - "$RESULTS_FILE" "$TILE_W_UM" "$TILE_H_UM" "$UTILIZATION_PCT" "$results" <<'PYEOF'
import json
import sys

out_path, tile_w, tile_h, util = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
doc = {
    "experiment": "die-area-baseline",
    "flow": "klt synthesize + klt place-and-route (OpenROAD, iteration flow of DR 0002)",
    "tile_geometry_source": "Tiny Tapeout cmos5l template info.yaml (~167x108 um per tile, order of magnitude)",
    "floorplan_inputs": {
        "method": "utilization",
        "requested_utilization_pct": float(util),
        "aspect_ratio": 1.0,
        "core_margin_um": 2.0,
        "site": "CoreSite",
        "io_layers": ["Metal3", "Metal2"],
        "clock_period_ns": 20.0,
        "seed": 1,
        "target_stage": "place",
    },
    "designs": json.loads(sys.argv[5]),
}
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(doc, handle, indent=2)
    handle.write("\n")
print(out_path)
PYEOF

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi
