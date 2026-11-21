#!/usr/bin/env bash
#
# flow/run-sta-post-route-sweep.sh -- run a standalone multi-corner static
# timing analysis (`klt sta`, **def mode**) over the **flow-of-record
# post-route geometry** of the current top: the routed DEF, the extracted
# SPEF and the final SDC of the Tiny Tapeout LibreLane `gds` workflow run,
# at the three corners the program-memory macro ships a liberty for
# (issue #522, T1 item 5).
#
# Why this runner exists next to `flow/run-sta-corner-sweep.sh`: that
# runner times a *netlist estimate* (verilog mode, ideal clock, liberty
# wire-load, no placement/CTS/routing), so its hold numbers are a
# pre-route estimate -- its records could never be cited as routed-timing
# evidence, and its own header says to switch to `def` mode "when a
# routed DEF exists". This runner is that switch: a klt verb measuring the
# flow-of-record result, the same shape T1 item 7 already uses (item 7
# simulates the LibreLane post-route netlist under SDF; this runner times
# the LibreLane post-route DEF under its own extracted SPEF). The two
# runners stay separate because they answer different questions on
# different artifacts; every timing number each reports names its flow
# and geometry stage.
#
# What one run does, per corner (`slow_1p08V_125C`, `typ_1p20V_25C`,
# `fast_1p32V_m40C` -- the DR 0007 macro pairing, macro fast liberty
# `fast_1p32V_m55C` against stdcell `fast_1p32V_m40C`, exactly as the
# netlist-estimate runner declares it):
#
#   - loads the routed DEF (`read_lef` x2 + `read_def`), so
#     `geometry_source` is `"routed"`, never `"netlist_estimate"`;
#   - annotates the run's own extracted SPEF via `read_spef` (LibreLane
#     extracts ONE nominal-RC SPEF for the whole run -- `final/spef/nom/`
#     -- which is the same SPEF its own `stapostpnr` corner STA reads, so
#     using it at every PVT corner is like-for-like with the flow of
#     record; a run emitting more than one interconnect key is refused,
#     not guessed at);
#   - propagates the clock (`constraints.propagated_clock`: the DEF's
#     clock-tree insertion delay and skew are in the timing);
#   - applies the run's own final SDC boundary constraints, PARSED from
#     that SDC -- never invented here: uniform `input_delay_ns` /
#     `output_delay_ns`, `clock_uncertainty_ns`, the driving cell and the
#     output pin load. This is what makes
#     `constraint_completeness.status` `complete` (the 24 top-level
#     output endpoints `uo_out[*]`/`uio_out[*]`/`uio_oe[*]` plus the
#     input->register paths all become constrained endpoints). The runner
#     FAILS if the SDC is missing, has no single `create_clock` on `clk`,
#     lacks `set_propagated_clock`, or carries non-uniform IO delays --
#     the same fail-loud contract `flow/run-post-layout-sdf.sh` applies
#     to the same file.
#
# SDC subset the `klt sta` request schema cannot express (recorded, not
# silently dropped): `set_clock_transition` and `set_timing_derate`. The
# runner detects them, prints a warning naming them, and records them in
# the derived-constraints JSON it writes beside its results -- the
# residual offset vs the LibreLane corner STA on the same geometry/SPEF
# is attributable to exactly these (klt's slack runs without the SDC's
# derating), which is why the LibreLane figure and the klt figure stay
# separately labelled wherever both are quoted. `sdc_check` is
# deliberately NOT used: against this SDC dialect (`-add_delay`, braced
# `[get_ports {x}]`) klt's checked-subset reader punts every line to
# `unchecked` and then reports the request's own constraints as `drift`
# mismatches with `sdc_value: null` -- a misleading verdict in frozen
# evidence (2AMLogic/klayout-tools issue linked from the record).
#
# Environment requirements (docs/environment.md):
#   - `klt` on $PATH at the fleet version (KLT_BIN override honored).
#   - An `openroad` binary on $PATH (docker wrapper fine -- this script
#     keeps every input inside the repo/scratch and exports PDK_ROOT for
#     the wrapper's mount, like run-sta-corner-sweep.sh).
#   - A resolvable `ihp-sg13cmos5l` PDK (klt pdk find).
#   - `gh` (authenticated) for --run-id mode only; --from needs neither.
#
# Usage:
#   ./flow/run-sta-post-route-sweep.sh --run-id 44797672107        # all 3 corners
#   ./flow/run-sta-post-route-sweep.sh --from <dir> slow_1p08V_125C # one corner
#   KLT_BIN=.venv/bin/klt ./flow/run-sta-post-route-sweep.sh --from <dir>
#
# <dir> for --from is a directory holding an unpacked `GDS_logs` artifact
# (with `final/def/<top>.def`, `final/spef/<key>/<top>.spef` and
# `final/sdc/<top>.sdc` somewhere under it) -- exactly what
# `gh run download` leaves behind. --run-id <gds-workflow-run-id>
# downloads that artifact itself (nothing else is needed: the DEF is the
# geometry of record; the routed netlist is item 7's input, not this
# runner's).
#
# Writes flow/sta-post-route-sweep-results.json (gitignored; the evidence
# record under verification/records/sta-corner-sweep/artifacts/ freezes a
# copy, and the DEF/SPEF bytes go to the artifact store via
# verification/artifact_store.py). Per corner the runner also freezes the
# request, the response and the log next to the results, plus a
# constraints-derived.json pinning what was parsed from the SDC.
#
# Exit codes: non-zero if any `klt sta` run fails or any post-run
# invariant is violated (geometry_source not "routed", clock_mode not
# "propagated", timing_status not "constrained",
# constraint_completeness.status not "complete"). NEGATIVE SLACK IS A
# RESULT, NOT A RUN FAILURE -- a failing corner is recorded as measured
# and does not affect the exit code. `spef_annotation.annotation_complete`
# is reported, not gated: the flow-of-record SPEF structurally lacks the
# power nets (VGND/VPWR never appear in a signal SPEF) and the unused
# `ena` input's net, which this runner cannot fix without editing
# flow-of-record bytes -- the per-corner annotation evidence block is
# frozen for the record to quote honestly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLOW_DIR="${REPO_ROOT}/flow"
SCRATCH_DIR="${FLOW_DIR}/sta-post-route-sweep"
REQUEST_DIR="${SCRATCH_DIR}/corners"
RESULTS_FILE="${FLOW_DIR}/sta-post-route-sweep-results.json"
DOWNLOAD_DIR="${SCRATCH_DIR}/download"
PDK_VARIANT="ihp-sg13cmos5l"
HDL_TOPLEVEL="tt_um_2amlogic_protocol_emulator"

# The declared corner set (issue #522, DR 0007): the three corners the
# program memory macro (RM_IHPSG13_1P_256x16_c2_bm_bist) ships a liberty
# for. The stdcell fast corner is -40C but the macro's is -55C; the
# pairing below is DR 0007's, not invented here. The other three shipped
# stdcell corners (1.35/1.50/1.65 V) have no macro liberty and are
# recorded as uncharacterized, not passed. Pass a corner name to run just
# that one.
ALL_CORNERS=(
  slow_1p08V_125C
  typ_1p20V_25C
  fast_1p32V_m40C
)

RUN_ID_ARG=""
FROM_DIR=""
CORNERS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --run-id)
      RUN_ID_ARG="$2"; shift 2 ;;
    --from)
      FROM_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,105p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)
      CORNERS+=("$1"); shift ;;
  esac
done
if [ "${#CORNERS[@]}" -eq 0 ]; then
  CORNERS=("${ALL_CORNERS[@]}")
fi

if [ -z "$RUN_ID_ARG" ] && [ -z "$FROM_DIR" ]; then
  echo "FATAL: exactly one of --run-id <gds-workflow-run-id> or --from <downloaded-artifacts-dir> is required." >&2
  exit 1
fi
if [ -n "$RUN_ID_ARG" ] && [ -n "$FROM_DIR" ]; then
  echo "FATAL: --run-id and --from are mutually exclusive." >&2
  exit 1
fi

# shellcheck source=./_klt.sh
source "${FLOW_DIR}/_klt.sh"

klt_resolve
klt_require_verbs "sta"

# Resolves/exports PDK_ROOT and sets PDK_ARGS. Mandatory here even though
# klt resolves the PDK itself: the openroad docker wrapper mounts only
# $PWD and $PDK_ROOT, and without the mount read_lef fails inside the
# container with ORD-0001 on a file that exists on the host.
klt_export_pdk_root "$PDK_VARIANT"

# --- Acquire the flow-of-record post-route artifacts ----------------------
mkdir -p "$SCRATCH_DIR"
if [ -n "$RUN_ID_ARG" ]; then
  if [ -d "$DOWNLOAD_DIR" ] && [ -n "$(ls -A "$DOWNLOAD_DIR" 2>/dev/null)" ]; then
    echo "FATAL: ${DOWNLOAD_DIR} is not empty -- move it aside before re-downloading." >&2
    exit 1
  fi
  mkdir -p "$DOWNLOAD_DIR"
  echo "== downloading GDS_logs artifact of gds run ${RUN_ID_ARG} ==" >&2
  gh run download "$RUN_ID_ARG" -n GDS_logs -D "$DOWNLOAD_DIR"
  ACQUIRE_DIR="$DOWNLOAD_DIR"
else
  ACQUIRE_DIR="$FROM_DIR"
fi

DEF_FILE="$(find "$ACQUIRE_DIR" -path "*final/def/*" -name "${HDL_TOPLEVEL}.def" -type f | sort | head -1)"
if [ -z "$DEF_FILE" ]; then
  echo "FATAL: final/def/${HDL_TOPLEVEL}.def not found under ${ACQUIRE_DIR} (expected in the GDS_logs artifact): no routed geometry to time." >&2
  exit 1
fi
SDC_FILE="$(find "$ACQUIRE_DIR" -path "*final/sdc/*" -name "${HDL_TOPLEVEL}.sdc" -type f | sort | head -1)"
if [ -z "$SDC_FILE" ]; then
  echo "FATAL: final/sdc/${HDL_TOPLEVEL}.sdc not found under ${ACQUIRE_DIR} (expected in the GDS_logs artifact): no constraints to align the sweep to." >&2
  exit 1
fi
# The SPEF key axis: LibreLane extracts one nominal-RC SPEF per run
# (final/spef/nom/). More than one distinct key is refused -- picking one
# interconnect corner per PVT corner would be a policy decision this
# runner does not make.
SPEF_KEYS="$(find "$ACQUIRE_DIR" -path "*final/spef/*" -name "*.spef" -type f | sed 's|.*/final/spef/||; s|/[^/]*$||' | sort -u)"
SPEF_KEY_COUNT="$(echo "$SPEF_KEYS" | wc -l)"
if [ -z "$SPEF_KEYS" ] || [ "$SPEF_KEYS" = "" ]; then
  echo "FATAL: no SPEF found under ${ACQUIRE_DIR} (expected final/spef/<key>/${HDL_TOPLEVEL}.spef in the GDS_logs artifact): a post-route claim needs real parasitics." >&2
  exit 1
fi
if [ "$SPEF_KEY_COUNT" -ne 1 ]; then
  echo "FATAL: more than one SPEF interconnect key under ${ACQUIRE_DIR}: got [$SPEF_KEYS]. This runner times every PVT corner against the run's single extracted SPEF; choosing among interconnect corners is not done here." >&2
  exit 1
fi
SPEF_FILE="$(find "$ACQUIRE_DIR" -path "*final/spef/*" -name "*.spef" -type f | sort | head -1)"

# --- Derive the boundary constraints from the run's own SDC ---------------
# Same source `flow/run-post-layout-sdf.sh` aligns to; parsed, never
# hardcoded. Fails on: no single create_clock on clk; no uniform IO
# delays; no set_propagated_clock; non-uniform driving cell / output load
# / clock uncertainty. Detects (and warns about, recording them in the
# derived JSON) the SDC subset the request schema cannot express.
CONSTRAINTS_JSON="${SCRATCH_DIR}/constraints-derived.json"
eval "$(python3 - "$SDC_FILE" "$CONSTRAINTS_JSON" <<'PYEOF'
import json
import re
import sys

sdc_path, out_path = sys.argv[1], sys.argv[2]
text = open(sdc_path, encoding="utf-8").read()

clocks = re.findall(r"create_clock\s+-name\s+clk\s+-period\s+([0-9.]+)", text)
if len(clocks) != 1:
    sys.exit(f"FATAL: expected exactly one create_clock -name clk in {sdc_path}, found {clocks}")

ins = re.findall(r"set_input_delay\s+([0-9.]+)\s+-clock\s+\[get_clocks\s+\{?clk\}?\]\s+-add_delay\s+\[get_ports\s+\{([^}]+)\}\]", text)
outs = re.findall(r"set_output_delay\s+([0-9.]+)\s+-clock\s+\[get_clocks\s+\{?clk\}?\]\s+-add_delay\s+\[get_ports\s+\{([^}]+)\}\]", text)
if not ins or not outs:
    sys.exit(f"FATAL: {sdc_path} has no set_input_delay or no set_output_delay on clk")
in_vals = sorted({v for v, _ in ins})
out_vals = sorted({v for v, _ in outs})
if len(in_vals) > 1 or len(out_vals) > 1:
    sys.exit(f"FATAL: non-uniform IO delays in {sdc_path}: inputs {in_vals}, outputs {out_vals}")

if "set_propagated_clock" not in text:
    sys.exit(f"FATAL: {sdc_path} has no set_propagated_clock -- a post-route SDC without it would silently change what is measured")

# Clock uncertainty: scalar form (applies to setup and hold) or the
# -setup/-hold pair; both map onto the request schema.
unc_scalar = re.findall(r"set_clock_uncertainty\s+([0-9.]+)\s+clk", text)
unc_setup = re.findall(r"set_clock_uncertainty\s+-setup\s+([0-9.]+)", text)
unc_hold = re.findall(r"set_clock_uncertainty\s+-hold\s+([0-9.]+)", text)
if len(unc_scalar) + len(unc_setup) + len(unc_hold) > 1:
    sys.exit(f"FATAL: {sdc_path} carries multiple set_clock_uncertainty forms; refusing to pick one")
if unc_scalar:
    uncertainty = float(unc_scalar[0])
elif unc_setup or unc_hold:
    uncertainty = {}
    if unc_setup:
        uncertainty["setup_ns"] = float(unc_setup[0])
    if unc_hold:
        uncertainty["hold_ns"] = float(unc_hold[0])
else:
    uncertainty = None

drivers = set(re.findall(r"set_driving_cell\s+-lib_cell\s+(\S+)\s+-pin\s+\{(\S+)\}", text))
if len(drivers) > 1:
    sys.exit(f"FATAL: non-uniform set_driving_cell in {sdc_path}: {sorted(drivers)}")
driving_cell = [{"cell": c, "pin": p} for (c, p) in drivers]
loads = sorted({v for v in re.findall(r"set_load\s+-pin_load\s+([0-9.]+)", text)})
if len(loads) > 1:
    sys.exit(f"FATAL: non-uniform set_load -pin_load in {sdc_path}: {loads}")

not_expressible = []
if re.search(r"^\s*set_clock_transition\b", text, re.M):
    not_expressible.append("set_clock_transition")
if re.search(r"^\s*set_timing_derate\b", text, re.M):
    not_expressible.append("set_timing_derate")

derived = {
    "source": f"final/sdc/{sdc_path.rsplit('/', 1)[-1]} of the gds workflow run (frozen beside this file)",
    "clock_period_ns": float(clocks[0]),
    "input_delay_ns": float(in_vals[0]),
    "input_delay_ports": sorted(p for _, p in ins),
    "output_delay_ns": float(out_vals[0]),
    "output_delay_ports": sorted(p for _, p in outs),
    "clock_uncertainty": uncertainty,
    "driving_cell": driving_cell[0] if driving_cell else None,
    "output_load_pf": float(loads[0]) if loads else None,
    "propagated_clock": True,
    "not_expressible_in_request": not_expressible,
}
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(derived, handle, indent=2)
    handle.write("\n")

print(f"SDC_CLOCK_PERIOD_NS={clocks[0]}")
print(f"SDC_INPUT_DELAY_NS={in_vals[0]}")
print(f"SDC_OUTPUT_DELAY_NS={out_vals[0]}")
if unc_scalar:
    print(f"SDC_CLOCK_UNCERTAINTY_JSON='{unc_scalar[0]}'")
elif isinstance(uncertainty, dict):
    print(f"SDC_CLOCK_UNCERTAINTY_JSON='{json.dumps(uncertainty)}'")
else:
    print("SDC_CLOCK_UNCERTAINTY_JSON=None")
if driving_cell:
    print(f"SDC_DRIVING_CELL_JSON='{json.dumps(driving_cell[0])}'")
else:
    print("SDC_DRIVING_CELL_JSON=None")
if loads:
    print(f"SDC_OUTPUT_LOAD_PF={loads[0]}")
else:
    print("SDC_OUTPUT_LOAD_PF=None")
print(f"SDC_NOT_EXPRESSIBLE={','.join(not_expressible)}")
PYEOF
)" || exit 1

echo "== constraints (from $(basename "$SDC_FILE")): period ${SDC_CLOCK_PERIOD_NS} ns, input +${SDC_INPUT_DELAY_NS} ns, output +${SDC_OUTPUT_DELAY_NS} ns, uncertainty ${SDC_CLOCK_UNCERTAINTY_JSON}, driving ${SDC_DRIVING_CELL_JSON}, load ${SDC_OUTPUT_LOAD_PF} pF ==" >&2
if [ -n "$SDC_NOT_EXPRESSIBLE" ]; then
  echo "WARNING: the SDC carries constraint forms the klt sta request schema cannot express (${SDC_NOT_EXPRESSIBLE}); they are recorded in ${CONSTRAINTS_JSON} and NOT applied -- the LibreLane figure and this klt figure stay separately labelled wherever both are quoted." >&2
fi

# Freeze the analysed inputs beside the results so the evidence record
# copies the exact bytes every corner run loaded (they are identical
# across the sweep by construction; the DEF and SPEF are large and also
# go to the artifact store, but a local copy keeps this scratch dir
# self-describing).
cp "$DEF_FILE" "${SCRATCH_DIR}/${HDL_TOPLEVEL}.def"
cp "$SPEF_FILE" "${SCRATCH_DIR}/${HDL_TOPLEVEL}.spef"
cp "$SDC_FILE" "${SCRATCH_DIR}/${HDL_TOPLEVEL}.sdc"
DEF_FOR_STA="${SCRATCH_DIR}/${HDL_TOPLEVEL}.def"
SPEF_FOR_STA="${SCRATCH_DIR}/${HDL_TOPLEVEL}.spef"

# --- One `klt sta` run per corner, over that one DEF/SPEF -----------------
echo "[" > "${RESULTS_FILE}"
first=1
FAILED=0

for corner in "${CORNERS[@]}"; do
  corner_dir="${REQUEST_DIR}/${corner}"
  mkdir -p "${corner_dir}"
  request_path="${corner_dir}/sta-protocol-emulator.json"
  python3 - "$request_path" "$corner" "$DEF_FOR_STA" "$SPEF_FOR_STA" "$PDK_ROOT_RESOLVED" \
    "$SDC_CLOCK_PERIOD_NS" "$SDC_INPUT_DELAY_NS" "$SDC_OUTPUT_DELAY_NS" \
    "$SDC_CLOCK_UNCERTAINTY_JSON" "$SDC_DRIVING_CELL_JSON" "$SDC_OUTPUT_LOAD_PF" <<'PYEOF'
import json
import os
import sys

(request_path, corner, def_abs, spef_abs, pdk_root, period_ns, input_delay_ns,
 output_delay_ns, uncertainty_json, driving_cell_json, output_load_pf) = sys.argv[1:12]
sram = os.path.join(pdk_root, "ihp-sg13cmos5l", "libs.ref", "sg13cmos5l_sram")
cell = "RM_IHPSG13_1P_256x16_c2_bm_bist"
# Per-corner macro liberty, keyed by the stdcell corner name (DR 0007 pairing).
macro_lib = {
    "slow_1p08V_125C": "slow_1p08V_125C",
    "typ_1p20V_25C": "typ_1p20V_25C",
    "fast_1p32V_m40C": "fast_1p32V_m55C",
}
request_dir = os.path.dirname(request_path)
def_rel = os.path.relpath(def_abs, request_dir)
spef_rel = os.path.relpath(spef_abs, request_dir)

constraints = {
    "clock_port": "clk",
    "clock_period_ns": float(period_ns),
    "propagated_clock": True,
    "input_delay_ns": float(input_delay_ns),
    "output_delay_ns": float(output_delay_ns),
}
if uncertainty_json != "None":
    constraints["clock_uncertainty_ns"] = json.loads(uncertainty_json)
if driving_cell_json != "None":
    constraints["driving_cell"] = json.loads(driving_cell_json)
if output_load_pf != "None":
    constraints["output_load_pf"] = float(output_load_pf)

request = {
    "schema": "klt.sta.request/1",
    "def": def_rel,
    "spef": spef_rel,
    "hdl_toplevel": "tt_um_2amlogic_protocol_emulator",
    "geometry_source": "routed",
    "pdk": {"cell_library": "sg13cmos5l_stdcell", "corner": corner},
    "constraints": constraints,
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

# --- Post-run invariants: what makes this a post-route claim --------------
# Negative slack passes through as a measured result; a response that is
# not a routed, propagated, fully constrained measurement fails the run.
python3 - "${RESULTS_FILE}" <<'PYEOF'
import json
import sys

bad = 0
with open(sys.argv[1], encoding="utf-8") as handle:
    entries = json.load(handle)
for entry in entries:
    corner = entry["corner"]
    resp = entry.get("response") or {}
    checks = {
        "geometry_source=routed": resp.get("geometry_source") == "routed",
        "clock_mode=propagated": resp.get("clock_mode") == "propagated",
        "timing_status=constrained": resp.get("timing_status") == "constrained",
        "constraint_completeness=complete": (resp.get("constraint_completeness") or {}).get("status") == "complete",
        "spef read": (resp.get("spef_path") or {}).get("path") is not None,
    }
    for name, ok in checks.items():
        if not ok:
            print(f"FATAL: {corner}: post-route invariant violated: {name}.", file=sys.stderr)
            bad = 1
    ann = resp.get("spef_annotation") or {}
    if not ann.get("annotation_complete", False):
        print(f"NOTE: {corner}: spef_annotation.annotation_complete is false "
              f"({ann.get('design_nets_annotated')}/{ann.get('design_nets_total')} design nets named; "
              f"unannotated drivers: {[d.get('pin') for d in ann.get('unannotated_driver_detail') or []]}); "
              "reported, not gated -- see the runner header for why.", file=sys.stderr)
    ws, wh = resp.get("worst_slack_ns"), resp.get("worst_hold_slack_ns")
    print(f"{corner}: setup WNS {ws:+.5f} ns, hold WNS {wh:+.5f} ns, "
          f"violations {resp.get('setup_violation_count')}/{resp.get('hold_violation_count')}")
sys.exit(bad)
PYEOF
