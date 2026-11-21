#!/usr/bin/env bash
#
# flow/run-power-par.sh -- T1 item 11 part 2 (issue #523): a
# `klt place-and-route` run on the macro-backed top
# (`tt_um_2amlogic_protocol_emulator`) that carries a `request.power` PDN
# block, so the response's `power` block states the grid the klt flow can
# build: `pdn`, the tap-cell statement, every `straps[].layer`, and the
# DEF-measured `placed` audit.
#
# Relationship to flow/run-die-area-par.sh (issue #389): that runner and
# its die-area numbers are the byte-stable measurement of record and are
# NOT touched by this one -- no mode flag was added to it, and this
# runner's floorplan/synthesis configuration is a copy of its inputs for
# the macro-backed top only, so the two runs stay comparable. Everything
# this runner adds lives in the request's `power`/`library` blocks.
#
# Two-step design, because `sg13cmos5l_stdcell` has no built-in power
# table in klt (it is in neither `_POWER_PIN_PATTERNS` nor
# `_TAPCELL_CELLS`/`_NO_TAPCELL_LIBRARIES`; klt issues #4086/#4127 added
# the `request.library` escape hatch):
#
#   1. PROBE -- the same request with `power` but WITHOUT `library`.
#      klt rejects it up front (before any engine run) with one error
#      naming the missing inputs. The runner captures that diagnostic and
#      fails if the premise drifts (klt accepting the probe, or the
#      diagnostic no longer naming `request.library.power_pins` and
#      `request.library.tapcell`) -- this is the "record which were
#      needed" evidence for the issue.
#   2. FULL RUN -- `power` + `library`:
#        power: explicit straps (there is no `power.preset` for this
#          library), mirroring the flow of record's PDN
#          (`src/pdn_cfg.tcl` + `src/config.json`) wherever the klt
#          schema allows it: a Metal1 `-followpins` row rail
#          (`FP_PDN_RAIL_WIDTH` 0.44 from the PDK's own
#          `libs.tech/librelane/sg13cmos5l_stdcell/config.tcl`; pitch
#          7.56 = 2x the 3.78 CoreSite row height, the same derivation
#          klt's `sg13g2` preset documents for the same site) and the
#          Metal4 vertical straps re-pitched by `src/config.json`
#          (`FP_PDN_VWIDTH` 2.1 / `FP_PDN_VPITCH` 44.96 /
#          `FP_PDN_VOFFSET` 93.985, `FP_PDN_VSPACING` 2.0 from the PDK's
#          `libs.tech/librelane/config.tcl`), plus the Metal1<->Metal4
#          `connects` pair `src/pdn_cfg.tcl` itself adds. NO strap above
#          Metal4: TopMetal1.drawing is not on the competition precheck
#          allowlist, exactly as `src/pdn_cfg.tcl` states.
#        library: `power_pins` for the standard cells' VDD/VSS (the LEF's
#          only USE POWER/GROUND pin names) and the SRAM macro's
#          VDD!/VDDARRAY!/VSS! aliases (same pins
#          `PDN_MACRO_CONNECTIONS` in `src/config.json` joins to
#          VPWR/VGND); `tapcell: null` -- the PDK's own librelane config
#          states "There are no endcap and welltie cells in
#          ihp-sg13cmos5l"; `filler` from that same config's
#          `FILL_CELLS "sg13cmos5l_fill_1 sg13cmos5l_fill_2"` (filler
#          placement is a route-stage-only call; at `target_stage:
#          "place"` it is inert, recorded so a future route-stage run
#          need not rediscover it).
#      `power_net`/`ground_net` are VPWR/VGND, the supply net names the
#      ERC spec (`flow/erc-librelane-gds.json`) declares primary.
#
# What this runner does NOT reproduce from the flow of record: the custom
# Metal4 macro bridge `src/pdn_cfg.tcl` draws over the SRAM stripes
# (klt's `request.power` schema has no free-Tcl escape, by design), and
# klt emits no macro grid here because the macro declares no `halo`.
# Whether the flat stdcell grid alone reaches the macro's pins is a
# measured question the response's `power.placed` audit answers; it is
# recorded, not worked around.
#
# The summary also cross-checks every `power.straps[].layer` against the
# stackup of `flow/erc-librelane-gds.json` (T1 item 11's strap-coverage
# rule) mechanically, so the record citing this run states the coverage
# from the run's own output rather than by hand.
#
# Environment requirements (same as `flow/run-die-area-par.sh`; see
# docs/environment.md, flow/README.md): `klt` on $PATH at the fleet
# version (`KLT_BIN` can point elsewhere), a docker-wrapped `openroad`
# on $PATH (the runner keeps every input inside the repo and runs from
# the repo root, and exports PDK_ROOT for the wrapper's mount), and a
# resolvable `ihp-sg13cmos5l` PDK.
#
# Usage (from the repo root):
#   ./flow/run-power-par.sh
#   KLT_BIN=/tmp/klt-092-venv/bin/klt ./flow/run-power-par.sh
#
# Writes flow/power-par-results.json (gitignored; the evidence record
# under verification/records/power-par-pdn/artifacts/ freezes the probe
# diagnostic, both requests and the response). Exits non-zero if the
# probe premise fails, the full `klt synthesize`/`klt place-and-route`
# run fails, or a strap layer is not covered by the ERC spec's stackup.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLOW_DIR="${REPO_ROOT}/flow"
SCRATCH_DIR="${FLOW_DIR}/power-par-scratch"
RESULTS_FILE="${FLOW_DIR}/power-par-results.json"
ERC_SPEC="${REPO_ROOT}/flow/erc-librelane-gds.json"
PDK_VARIANT="ihp-sg13cmos5l"
# Clock/stage/seed travel into the request builder below; the remaining
# floorplan inputs (utilization 40%, aspect 1.0, core margin 2.0 um, site
# CoreSite, IO Metal3/Metal2) are copied verbatim from
# flow/run-die-area-par.sh inside that builder, so the power-bearing run
# floors the same die the die-area record measured.
CLOCK_PERIOD_NS="20.0"   # 50 MHz -- matches the recipes and src/config.json
SEED="1"
TARGET_STAGE="place"
# The PDN/global-connect steps run at the end of the floorplan stage, so
# "place" is enough to get the power block; "route" stays unexercised on
# this flow (same posture as the die-area runner).
RECIPE="flow/synthesize-protocol-emulator.json"
TOP="tt_um_2amlogic_protocol_emulator"
MACRO_INSTANCE="u_prog_mem/u_sram"
SRAM_CELL="RM_IHPSG13_1P_256x16_c2_bm_bist"
MACRO_INSET_UM="5.0"
# Core margin 2.0 um -- the die-area runner's value (see its header).
MACRO_X_UM="$(python3 -c "print(2.0 + ${MACRO_INSET_UM})")"
MACRO_Y_UM="$MACRO_X_UM"

# shellcheck source=./_klt.sh
source "${FLOW_DIR}/_klt.sh"

klt_resolve
klt_require_verbs "synthesize" "place-and-route"
command -v openroad >/dev/null 2>&1 || {
  echo "FATAL: openroad not found on \$PATH -- see docs/environment.md." >&2
  exit 1
}

# Resolves/exports PDK_ROOT and sets PDK_ARGS -- see _klt.sh's
# klt_export_pdk_root for why this is exported even though klt itself can
# resolve the PDK without it (the openroad docker wrapper's mount).
klt_export_pdk_root "$PDK_VARIANT"

rm -rf "$SCRATCH_DIR"
mkdir -p "$SCRATCH_DIR"

slug="tt-um-2amlogic-protocol-emulator"

echo "== ${TOP}: synthesize (nominal corner) ==" >&2
"$KLT" synthesize "$RECIPE" "${PDK_ARGS[@]}" --format json \
  > "${SCRATCH_DIR}/synthesize-${slug}-response.json" 2> "${SCRATCH_DIR}/synthesize-${slug}.log"
NETLIST_ABS="$(klt_response_path "${SCRATCH_DIR}/synthesize-${slug}-response.json" netlist_path)"
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

# Both requests share everything except the library block: the probe
# proves which request.library inputs klt demands for this library, the
# full run supplies them.
python3 - "$SCRATCH_DIR" "$TOP" "${SCRATCH_DIR}/${NETLIST_BASENAME}" \
  "$MACRO_INSTANCE" "$PDK_ROOT_RESOLVED" "$SRAM_CELL" "$MACRO_X_UM" "$MACRO_Y_UM" \
  "$CLOCK_PERIOD_NS" "$TARGET_STAGE" "$SEED" <<'PYEOF'
import json
import os
import sys

scratch, top, netlist = sys.argv[1], sys.argv[2], sys.argv[3]
macro_instance, pdk_root, sram_cell = sys.argv[4], sys.argv[5], sys.argv[6]
macro_x_um, macro_y_um = float(sys.argv[7]), float(sys.argv[8])
clock_period_ns, target_stage, seed = float(sys.argv[9]), sys.argv[10], int(sys.argv[11])
sram = os.path.join(pdk_root, "ihp-sg13cmos5l", "libs.ref", "sg13cmos5l_sram")
# Per-corner macro liberty, keyed by the stdcell corner name (DR 0007
# pairing) -- the same map flow/run-die-area-par.sh builds.
macro_lib = {
    "slow_1p08V_125C": "slow_1p08V_125C",
    "typ_1p20V_25C": "typ_1p20V_25C",
    "fast_1p32V_m40C": "fast_1p32V_m55C",
}

# The PDN this request declares, mirroring src/pdn_cfg.tcl +
# src/config.json where the klt schema allows (see this runner's header).
# Bottom-to-top, exactly one connect pair, nothing above Metal4.
power = {
    "power_net": "VPWR",
    "ground_net": "VGND",
    "straps": [
        # Metal1 followpin row rail: FP_PDN_RAIL_WIDTH 0.44 (PDK
        # librelane sg13cmos5l_stdcell config.tcl); pitch 7.56 = 2 x the
        # 3.78 um CoreSite row height (PLACE_SITE_HEIGHT in that same
        # file) -- the derivation klt's sg13g2 preset documents for the
        # same site shape.
        {
            "layer": "Metal1",
            "width_um": 0.44,
            "pitch_um": 7.56,
            "offset_um": 0.0,
            "followpins": True,
        },
        # Metal4 vertical straps: FP_PDN_VWIDTH 2.1 / VPITCH 44.96 /
        # VOFFSET 93.985 re-pitched by src/config.json; VSPACING 2.0 is
        # the PDK librelane default that config does not override.
        {
            "layer": "Metal4",
            "width_um": 2.1,
            "spacing_um": 2.0,
            "pitch_um": 44.96,
            "offset_um": 93.985,
        },
    ],
    "connects": [{"layers": ["Metal1", "Metal4"]}],
}

# Per-library inputs klt has no built-in table for (probe proves which
# are required): the stdcell LEF's only supply pins are VDD/VSS; the SRAM
# macro's are VDD!/VDDARRAY!/VSS! (the pins PDN_MACRO_CONNECTIONS joins);
# the PDK's own librelane config states there are no endcap/welltie
# cells in ihp-sg13cmos5l and names FILL_CELLS sg13cmos5l_fill_1/2.
library = {
    "power_pins": [
        {"net_role": "power", "pattern": "^VDD$", "primary": True},
        {"net_role": "power", "pattern": "^VDD!$", "primary": False},
        {"net_role": "power", "pattern": "^VDDARRAY!$", "primary": False},
        {"net_role": "ground", "pattern": "^VSS$", "primary": True},
        {"net_role": "ground", "pattern": "^VSS!$", "primary": False},
    ],
    "tapcell": None,
    "filler": ["sg13cmos5l_fill_1", "sg13cmos5l_fill_2"],
}

def request(with_library):
    req = {
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
        "constraints": {"clock_port": "clk", "clock_period_ns": clock_period_ns},
        "macros": [
            {
                "cell": sram_cell,
                "lef": os.path.join(sram, "lef", sram_cell + ".lef"),
                "lib": {
                    k: os.path.join(sram, "lib", f"{sram_cell}_{v}.lib")
                    for k, v in macro_lib.items()
                },
                "instance": macro_instance,
                "x_um": macro_x_um,
                "y_um": macro_y_um,
                "orientation": "R0",
            }
        ],
        "power": power,
        "seed": seed,
        "target_stage": target_stage,
    }
    if with_library:
        req["library"] = library
    return req

for name, with_library in (
    ("par-power-probe-request.json", False),
    ("par-power-request.json", True),
):
    with open(os.path.join(scratch, name), "w", encoding="utf-8") as handle:
        json.dump(request(with_library), handle, indent=2)
        handle.write("\n")
PYEOF

# --- step 1: probe -- expect the up-front rejection ----------------------
echo "== ${TOP}: probe place-and-route (power, NO library) ==" >&2
set +e
"$KLT" place-and-route "${SCRATCH_DIR}/par-power-probe-request.json" "${PDK_ARGS[@]}" \
  --format json > "${SCRATCH_DIR}/par-power-probe-response.json" \
  2> "${SCRATCH_DIR}/par-power-probe-no-library.log"
probe_rc=$?
set -e
if [ "$probe_rc" -eq 0 ]; then
  echo "FATAL: probe succeeded (rc=0) -- klt now accepts request.power without request.library for sg13cmos5l_stdcell; this runner's recorded premise (issue #523) is stale. Re-derive from the probe response." >&2
  exit 1
fi
for needle in "request.library.power_pins" "request.library.tapcell"; do
  if ! grep -q "$needle" "${SCRATCH_DIR}/par-power-probe-no-library.log"; then
    echo "FATAL: probe rejection does not name '${needle}' -- the missing-input diagnostic changed; see ${SCRATCH_DIR}/par-power-probe-no-library.log" >&2
    exit 1
  fi
done
echo "probe rejected as expected (rc=${probe_rc}); diagnostic names request.library.power_pins and request.library.tapcell" >&2

# --- step 2: full run -- power + library ----------------------------------
echo "== ${TOP}: place-and-route with power + library (target_stage: ${TARGET_STAGE}) ==" >&2
"$KLT" place-and-route "${SCRATCH_DIR}/par-power-request.json" "${PDK_ARGS[@]}" --format json \
  > "${SCRATCH_DIR}/par-${slug}-response.json" 2> "${SCRATCH_DIR}/par-${slug}.log"

# --- step 3: fold the power block + strap-coverage cross-check into the
# summary. The response's `power` object is copied VERBATIM (every key);
# the coverage check mirrors the T1 item 11 grader's rule (a strap layer
# must be a stackup entry's name or layer).
python3 - "$SCRATCH_DIR" "$RESULTS_FILE" "$slug" "$ERC_SPEC" "$probe_rc" <<'PYEOF'
import json
import sys

scratch, out_path, slug, erc_spec_path, probe_rc = (
    sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]),
)
par = json.load(open(f"{scratch}/par-{slug}-response.json"))
spec = json.load(open(erc_spec_path))
stackup = {
    entry[field]
    for entry in spec.get("stackup") or []
    if isinstance(entry, dict)
    for field in ("name", "layer")
    if isinstance(entry.get(field), str) and entry[field]
}
strap_layers = [strap["layer"] for strap in par["power"]["straps"]]
uncovered = [layer for layer in strap_layers if layer not in stackup]
doc = {
    "experiment": "power-par-pdn",
    "flow": "klt synthesize + klt place-and-route with request.power (OpenROAD, iteration flow of DR 0002)",
    "hdl_toplevel": par["hdl_toplevel"],
    "probe": {
        "request": "par-power-probe-request.json",
        "exit_status": probe_rc,
        "rejected_without_library": True,
        "diagnostic_names": [
            "request.library.power_pins",
            "request.library.tapcell",
        ],
        "diagnostic_log": "par-power-probe-no-library.log",
    },
    "power": par["power"],
    "placed_stage": {
        "stage_reached": par["stage_reached"],
        "die_area_um2": par["die_area_um2"],
        "core_area_um2": par["core_area_um2"],
        "utilization_pct": par["utilization_pct"],
        "engine_version": par["engine_version"],
        "deck_name": par["provenance"]["deck"]["name"],
    },
    "strap_layer_erc_stackup_coverage": {
        "erc_spec": "flow/erc-librelane-gds.json",
        "stackup": sorted(stackup),
        "strap_layers": strap_layers,
        "uncovered_strap_layers": uncovered,
        "all_covered": not uncovered,
    },
    "warnings": par.get("warnings", []),
}
if uncovered:
    doc["error"] = (
        "strap layer(s) not covered by the ERC spec stackup: "
        + ", ".join(uncovered)
    )
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(doc, handle, indent=2)
    handle.write("\n")
print(out_path)
if uncovered:
    sys.exit(1)
PYEOF
