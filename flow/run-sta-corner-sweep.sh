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
# I/O constraints (issue #522): the request carries `input_delay_ns` /
# `output_delay_ns` taken from the flow-of-record SDC -- the same source
# `flow/run-post-layout-sdf.sh` aligns its bench to (the Tiny Tapeout
# LibreLane `gds` run's own `final/sdc/<top>.sdc`, frozen under the
# post-layout-sdf-regression artifacts). Without them every top-level
# output port (`uo_out[*]`, `uio_out[*]`, `uio_oe[*]` -- 24 endpoints) is
# an unconstrained timing endpoint, `constraint_completeness.status`
# stays `incomplete` and the reported slack covers register-to-register
# and SRAM-boundary paths only. The values are PARSED from that SDC --
# never invented here: the runner fails if the SDC is missing, has no
# single `create_clock` on `clk`, or carries non-uniform IO delays (the
# same fail-loud contract run-post-layout-sdf.sh applies). Override the
# source with --sdc <path> (default: the newest frozen
# post-layout-sdf-regression SDC).
#
# Usage:
#   ./flow/run-sta-corner-sweep.sh                    # all 6 shipped corners
#   ./flow/run-sta-corner-sweep.sh slow_1p08V_125C    # a single named corner
#   ./flow/run-sta-corner-sweep.sh --sdc <frozen.sdc> # another SDC freeze
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

# The declared corner set (issue #20, DR 0007): the three corners the program
# memory macro (RM_IHPSG13_1P_256x16_c2_bm_bist) ships a liberty for. The
# stdcell fast corner is -40C but the macro's is -55C; the pairing below is
# DR 0007's, not invented here. The other three shipped stdcell corners
# (1.35/1.50/1.65 V) have no macro liberty and are recorded as
# uncharacterized, not passed. Pass a corner name to run just that one.
ALL_CORNERS=(
  slow_1p08V_125C
  typ_1p20V_25C
  fast_1p32V_m40C
)

CORNER_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --sdc)
      SDC_SRC_ARG="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,95p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)
      CORNER_ARGS+=("$1"); shift ;;
  esac
done
CORNERS=("${CORNER_ARGS[@]}")
if [ "${#CORNERS[@]}" -eq 0 ]; then
  CORNERS=("${ALL_CORNERS[@]}")
fi

# --- IO delays from the flow-of-record SDC (issue #522) -------------------
# Same source of truth `flow/run-post-layout-sdf.sh` uses for its drive/
# sample alignment: the LibreLane `gds` run's own final SDC, taken from
# the newest freeze under the post-layout-sdf-regression artifacts (or an
# explicit --sdc). Parsed, never hardcoded; non-uniform IO delays or a
# missing/unparsable SDC are FATAL -- inventing figures here would
# silently mis-constrain the sweep.
if [ -n "${SDC_SRC_ARG:-}" ]; then
  SDC_FILE="$SDC_SRC_ARG"
else
  SDC_FILE="$(find "${REPO_ROOT}"/verification/records/post-layout-sdf-regression/artifacts -mindepth 2 -maxdepth 2 -name "${HDL_TOPLEVEL}.sdc" -type f 2>/dev/null | sort | tail -1)"
fi
if [ -z "$SDC_FILE" ]; then
  echo "FATAL: no flow-of-record SDC found (expected a frozen verification/records/post-layout-sdf-regression/artifacts/*/tt_um_2amlogic_protocol_emulator.sdc, or pass --sdc <path>): no IO delays to constrain the sweep with." >&2
  exit 1
fi
eval "$(python3 - "$SDC_FILE" <<'PYEOF'
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
clocks = re.findall(r"create_clock\s+-name\s+clk\s+-period\s+([0-9.]+)", text)
if len(clocks) != 1:
    sys.exit(f"FATAL: expected exactly one create_clock -name clk in {sys.argv[1]}, found {clocks}")
ins = re.findall(r"set_input_delay\s+([0-9.]+)\s+-clock\s+\[get_clocks\s+\{?clk\}?\]\s+-add_delay\s+\[get_ports\s+\{([^}]+)\}\]", text)
outs = re.findall(r"set_output_delay\s+([0-9.]+)\s+-clock\s+\[get_clocks\s+\{?clk\}?\]\s+-add_delay\s+\[get_ports\s+\{([^}]+)\}\]", text)
if not ins or not outs:
    sys.exit(f"FATAL: {sys.argv[1]} has no set_input_delay or no set_output_delay on clk")
in_vals = sorted({v for v, _ in ins})
out_vals = sorted({v for v, _ in outs})
if len(in_vals) > 1 or len(out_vals) > 1:
    sys.exit(f"FATAL: non-uniform IO delays in {sys.argv[1]}: inputs {in_vals}, outputs {out_vals}")
print(f"SDC_INPUT_DELAY_NS={in_vals[0]}")
print(f"SDC_OUTPUT_DELAY_NS={out_vals[0]}")
print(f"SDC_INPUT_DELAY_PORT_COUNT={len(ins)}")
print(f"SDC_OUTPUT_DELAY_PORT_COUNT={len(outs)}")
PYEOF
)" || exit 1
echo "== IO delays (from $(basename "$SDC_FILE")): input +${SDC_INPUT_DELAY_NS} ns on ${SDC_INPUT_DELAY_PORT_COUNT} ports, output +${SDC_OUTPUT_DELAY_NS} ns on ${SDC_OUTPUT_DELAY_PORT_COUNT} ports ==" >&2

# shellcheck source=./_klt.sh
source "${FLOW_DIR}/_klt.sh"

klt_resolve

# Resolves/exports PDK_ROOT and sets PDK_ARGS -- see _klt.sh's
# klt_export_pdk_root for why this is exported even though klt itself can
# resolve the PDK without it (the openroad docker wrapper's mount).
klt_export_pdk_root "$PDK_VARIANT"

mkdir -p "$NETLIST_SCRATCH"

# --- Step 1: synthesize ONCE at the recipe's nominal corner -------------
# `klt synthesize` drives this itself at the pinned revision -- the
# direct-Yosys stopgap (flow/run_synthesize_direct_yosys.py, kept for the
# record) is no longer on this leg's path since klayout-tools#1786's fix
# landed (see flow/README.md).
echo "== synthesizing (nominal corner, once per sweep) ==" >&2
"$KLT" synthesize "$SYNTH_RECIPE" "${PDK_ARGS[@]}" --format json \
  > "${NETLIST_SCRATCH}/synthesize-response.json" 2> "${NETLIST_SCRATCH}/synthesize.log"
NETLIST_ABS="$(klt_response_path "${NETLIST_SCRATCH}/synthesize-response.json" netlist_path)"
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
  python3 - "$request_path" "$corner" "$NETLIST_FOR_STA" "$PDK_ROOT_RESOLVED" "$SDC_INPUT_DELAY_NS" "$SDC_OUTPUT_DELAY_NS" <<'PYEOF'
import json
import os
import sys

request_path, corner, netlist_abs, pdk_root = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
input_delay_ns, output_delay_ns = sys.argv[5], sys.argv[6]
sram = os.path.join(pdk_root, "ihp-sg13cmos5l", "libs.ref", "sg13cmos5l_sram")
cell = "RM_IHPSG13_1P_256x16_c2_bm_bist"
# Per-corner macro liberty, keyed by the stdcell corner name (DR 0007 pairing).
macro_lib = {
    "slow_1p08V_125C": "slow_1p08V_125C",
    "typ_1p20V_25C": "typ_1p20V_25C",
    "fast_1p32V_m40C": "fast_1p32V_m55C",
}
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
        "input_delay_ns": float(sys.argv[5]),
        "output_delay_ns": float(sys.argv[6]),
        "wire_load_model": "1k",
        "wire_load_mode": "top",
    },
    "macros": [
        {
            "cell": cell,
            "lef": os.path.join(sram, "lef", cell + ".lef"),
            "lib": {
                k: os.path.join(sram, "lib", f"{cell}_{v}.lib")
                for k, v in macro_lib.items()
            },
        }
    ],
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
