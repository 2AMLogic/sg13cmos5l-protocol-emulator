#!/usr/bin/env bash
#
# flow/run-post-layout-sdf.sh -- re-run this program's own committed cocotb
# bench (`verification/test_protocol_emulator.py`, unmodified) against the
# **post-route gate-level netlist** of the current top, with real post-route
# delays back-annotated from the SDF files the Tiny Tapeout LibreLane flow
# (`gds` GitHub Actions workflow) emits -- the T1 checklist item 7
# ("post-layout verification") leg of this repo's evidence trail, per
# `manifests/design-evidence-tiers.md`: "the functional test suite re-run
# against the post-route gate-level netlist with back-annotated SDF timing".
#
# Where the artifacts come from: the `gds` workflow's LibreLane run. Its
# `tt_submission` artifact carries the final routed netlist (the byte-
# identical netlist the template's own zero-delay `gl_test` job compiles),
# and its `GDS_logs` artifact carries the LibreLane run directory, whose
# `runs/<name>/final/sdf/<corner>/` holds one IEEE-1497 SDF per PVT corner
# written by OpenSTA at the post-route (`stapostpnr`) stage. This script
# consumes exactly those two things and produces one `klt
# functional-verification` run per emitted SDF corner, each with
# `options.sdf` set -- the machine-checkable `environment.sdf.annotated:
# true` shape `klt signoff` grades item 7 on, never mistakable for the
# zero-delay regression the template's `gl_test` already covers.
#
# Same bench, unmodified, is the point (klt functional-verification's SDF
# contract): the coverage signal is "does the testbench's own pass/fail
# outcome change once real delay is present?". A test that passed zero-delay
# and fails annotated is a *finding* to record, not a harness bug.
#
# Environment requirements (docs/environment.md, layout/toolchain.json):
#   - `klt` at the exact commit layout/toolchain.json pins (KLT_BIN
#     override honored). The SDF path needs klayout-tools' `functional-
#     verification` `options.sdf` support plus its Icarus SDF workarounds
#     (klayout-tools #962/#1004/#1056/#1619 era), so the pin must be at
#     1d964cf4 or later.
#   - Icarus Verilog >= 13.0 (options.sdf probes it: -ginterconnect does
#     not exist before 13.0).
#   - A resolvable `ihp-sg13cmos5l` PDK (klt pdk find): the request's
#     cell-model sources point into libs.ref/sg13cmos5l_stdcell/verilog/.
#     The stdcell models carry their specify blocks unconditionally (no
#     FUNCTIONAL define must be set -- klt rejects that combination), so
#     the timing branch of the cells is what simulates.
#   - `gh` (authenticated) for --run-id mode only; --from needs neither.
#
# Usage:
#   ./flow/run-post-layout-sdf.sh --run-id 35659983709            # all corners
#   ./flow/run-post-layout-sdf.sh --from <dir> nom_typ_1p20V_25C  # one corner
#   KLT_BIN=.venv/bin/klt ./flow/run-post-layout-sdf.sh --run-id 35659983709
#
# <dir> for --from is a directory holding an unpacked `tt_submission`
# artifact (with the routed `<top>.v` somewhere under it) and an unpacked
# `GDS_logs` artifact (with `final/sdf/<corner>/*.sdf` somewhere under it)
# -- exactly what `gh run download` leaves behind.
#
# Writes flow/post-layout-sdf-results.json (gitignored; the evidence record
# under verification/records/post-layout-sdf-regression/artifacts/ freezes
# the bytes). Exits non-zero if any klt run fails, if any response's
# `environment.sdf.annotated` is not true, or if the regression itself
# fails -- an annotated run that silently fell back to zero delay is a
# FAILURE here, not a pass.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH_DIR="${REPO_ROOT}/flow/post-layout-sdf"
RESULTS_FILE="${REPO_ROOT}/flow/post-layout-sdf-results.json"
DOWNLOAD_DIR="${SCRATCH_DIR}/download"
PDK_VARIANT="ihp-sg13cmos5l"
CELL_LIBRARY="sg13cmos5l_stdcell"
HDL_TOPLEVEL="tt_um_2amlogic_protocol_emulator"
BENCH_MODULE="test_protocol_emulator"

# The corner set this script sweeps is not chosen here -- it is whatever
# the LibreLane flow itself emitted for this design (the `nom_*` corners of
# `final/sdf/`), discovered from the downloaded artifacts. These defaults
# are only the fallback listing for --help readability and for the error
# message when discovery finds nothing.
EXPECTED_CORNERS="nom_typ_1p20V_25C nom_slow_1p08V_125C nom_fast_1p32V_m40C"

KLT="${KLT_BIN:-klt}"
if ! command -v "$KLT" >/dev/null 2>&1; then
  echo "FATAL: klt ('$KLT') not found on \$PATH -- run scripts/setup-env.sh or set KLT_BIN." >&2
  exit 1
fi
# Required-command check per layout/toolchain.json's contract: fail loudly
# naming the missing verb, never skip silently.
if ! "$KLT" --help 2>/dev/null | grep -q "functional-verification"; then
  echo "FATAL: '$KLT --help' does not list 'functional-verification' -- the install at '$KLT' lacks the verb this runner needs (layout/toolchain.json's klt_required_commands contract)." >&2
  exit 1
fi

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
      sed -n '2,52p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)
      CORNERS+=("$1"); shift ;;
  esac
done

if [ -z "$RUN_ID_ARG" ] && [ -z "$FROM_DIR" ]; then
  echo "FATAL: exactly one of --run-id <gds-workflow-run-id> or --from <downloaded-artifacts-dir> is required." >&2
  exit 1
fi
if [ -n "$RUN_ID_ARG" ] && [ -n "$FROM_DIR" ]; then
  echo "FATAL: --run-id and --from are mutually exclusive." >&2
  exit 1
fi

# --- Resolve the PDK (cell-model sources live under libs.ref) ------------
PDK_ROOT_RESOLVED="$("$KLT" pdk find --pdk "$PDK_VARIANT" --format json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["root"])')"
STDCELL_V="${PDK_ROOT_RESOLVED}/${PDK_VARIANT}/libs.ref/${CELL_LIBRARY}/verilog/${CELL_LIBRARY}.v"
# The UDP primitives file drops the _stdcell suffix in IHP's libs.ref
# layout (sg13cmos5l_udp.v, not sg13cmos5l_stdcell_udp.v) -- the same file
# the TT template's test/Makefile GL branch compiles.
UDP_V="${PDK_ROOT_RESOLVED}/${PDK_VARIANT}/libs.ref/${CELL_LIBRARY}/verilog/sg13cmos5l_udp.v"
for model in "$STDCELL_V" "$UDP_V"; do
  if [ ! -f "$model" ]; then
    echo "FATAL: cell model ${model} not found under the resolved PDK root ${PDK_ROOT_RESOLVED}." >&2
    exit 1
  fi
done

mkdir -p "$SCRATCH_DIR"

# --- Acquire the artifacts ------------------------------------------------
if [ -n "$RUN_ID_ARG" ]; then
  echo "== downloading gds artifacts for run ${RUN_ID_ARG} ==" >&2
  rm -rf "$DOWNLOAD_DIR"
  mkdir -p "$DOWNLOAD_DIR"
  gh run download "$RUN_ID_ARG" -R 2AMLogic/sg13cmos5l-protocol-emulator \
    -n tt_submission -D "${DOWNLOAD_DIR}/tt_submission"
  gh run download "$RUN_ID_ARG" -R 2AMLogic/sg13cmos5l-protocol-emulator \
    -n GDS_logs -D "${DOWNLOAD_DIR}/GDS_logs"
  ACQUIRE_DIR="$DOWNLOAD_DIR"
else
  ACQUIRE_DIR="$FROM_DIR"
fi

ROUTED_NETLIST="$(find "$ACQUIRE_DIR" -path "*tt_submission*" -name "${HDL_TOPLEVEL}.v" -type f | head -1)"
if [ -z "$ROUTED_NETLIST" ]; then
  echo "FATAL: routed netlist ${HDL_TOPLEVEL}.v not found under ${ACQUIRE_DIR} (expected the tt_submission artifact's copy)." >&2
  exit 1
fi

# Freeze the swept netlist once, next to the per-corner runs (every corner
# loads byte-identical netlist content by construction -- the same argument
# flow/run-sta-corner-sweep.sh makes for its one fixed netlist).
mkdir -p "${SCRATCH_DIR}/netlist" "${SCRATCH_DIR}/sdf"
cp "$ROUTED_NETLIST" "${SCRATCH_DIR}/netlist/${HDL_TOPLEVEL}.v"
NETLIST_FOR_FV="${SCRATCH_DIR}/netlist/${HDL_TOPLEVEL}.v"

declare -a SDF_CORNERS=()
while IFS= read -r sdf_path; do
  corner="$(basename "$(dirname "$sdf_path")")"
  cp "$sdf_path" "${SCRATCH_DIR}/sdf/${corner}.sdf"
  SDF_CORNERS+=("$corner")
done < <(find "$ACQUIRE_DIR" -path "*final/sdf/*" -name "*.sdf" -type f | sort)

if [ "${#SDF_CORNERS[@]}" -eq 0 ]; then
  echo "FATAL: no final/sdf/*.sdf found under ${ACQUIRE_DIR} (expected the GDS_logs artifact's runs/*/final/sdf/<corner>/ files: ${EXPECTED_CORNERS})." >&2
  exit 1
fi

if [ "${#CORNERS[@]}" -eq 0 ]; then
  CORNERS=("${SDF_CORNERS[@]}")
fi

echo "== swept netlist: ${NETLIST_FOR_FV}" >&2
echo "== sdf corners: ${CORNERS[*]}" >&2

# --- Normalize each frozen SDF for Icarus 13.0 annotation -----------------
# Two documented, mechanically-audited transforms, neither of which touches
# any nonzero delay (see the normalization report written beside each file):
#
#  1. Header VOLTAGE/PROCESS/TEMPERATURE triplets like `1.200::1.200`
#     (OpenSTA write_sdf omits the typ member) get the typ member filled
#     in -- under `iverilog -T typ` the empty member makes Icarus report
#     `SDF ERROR: Chosen value not defined` and klt (correctly) fails the
#     run. These header fields are documentary, not delays.
#  2. INTERCONNECT entries whose every delay-triplet member is exactly
#     zero are dropped. Icarus cannot insert an intermodpath whose
#     top-level-port endpoint is driven through a netlist `assign` alias
#     (`SDF ERROR: Could not find intermodpath!`), which is exactly the
#     shape a flow's inserted tie cells produce on constant outputs -- and
#     an all-zero entry models no delay, so dropping it cannot change any
#     simulated timing. Every entry dropped is recorded verbatim in the
#     per-corner normalization report.
for corner in "${SDF_CORNERS[@]}"; do
  python3 - "${SCRATCH_DIR}/sdf/${corner}.sdf" \
    "${SCRATCH_DIR}/sdf/${corner}.normalized.sdf" \
    "${SCRATCH_DIR}/sdf/${corner}.normalization.json" <<'PYEOF'
import json
import re
import sys

src_path, dst_path, report_path = sys.argv[1:4]
header_re = re.compile(r"^(\s*\((?:VOLTAGE|PROCESS|TEMPERATURE)\s+.?)((-?\d+(?:\.\d+)?)::(-?\d+(?:\.\d+)?))(.*)$")
triplet_re = re.compile(r"\(\s*([0-9.]+)\s*:\s*([0-9.]+)\s*:\s*([0-9.]+)\s*\)")
interconnect_re = re.compile(r"^(\s*\(INTERCONNECT\s+\S+\s+\S+\s+)(\(.*\))(\s*\)\s*)$")

def all_zero(delay_text):
    nums = [float(n) for n in triplet_re.findall(delay_text) for n in n]
    triplets = triplet_re.findall(delay_text)
    if not triplets:
        return False
    return all(float(m) == 0.0 for t in triplets for m in t)

header_filled = 0
dropped = []
kept_lines = []
with open(src_path, encoding="utf-8") as handle:
    for line in handle:
        m = header_re.match(line)
        if m:
            header_filled += 1
            line = f"{m.group(1)}{m.group(3)}:{m.group(3)}:{m.group(4)}{m.group(5)}\n"
            kept_lines.append(line)
            continue
        m = interconnect_re.match(line)
        if m and all_zero(m.group(2)):
            dropped.append(m.group(0).strip())
            continue
        kept_lines.append(line)

with open(dst_path, "w", encoding="utf-8") as handle:
    handle.writelines(kept_lines)
report = {
    "source": src_path,
    "header_triplets_typ_filled": header_filled,
    "zero_delay_interconnects_dropped": len(dropped),
    "dropped_entries": dropped,
}
with open(report_path, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=2)
    handle.write("\n")
print(f"   normalized {src_path}: header_triplets_filled={header_filled} zero_delay_interconnects_dropped={len(dropped)}")
PYEOF
done

# --- One klt functional-verification run per SDF corner -------------------
echo "[" > "${RESULTS_FILE}"
first=1
FAILED=0

for corner in "${CORNERS[@]}"; do
  corner_dir="${SCRATCH_DIR}/${corner}"
  mkdir -p "$corner_dir"
  request_path="${corner_dir}/request.json"
  sdf_file="${SCRATCH_DIR}/sdf/${corner}.sdf"
  if [ ! -f "$sdf_file" ]; then
    echo "FATAL: no SDF for corner '${corner}' (have: ${SDF_CORNERS[*]})." >&2
    exit 1
  fi

  python3 - "$request_path" "$NETLIST_FOR_FV" "${SCRATCH_DIR}/sdf/${corner}.normalized.sdf" "$STDCELL_V" "$UDP_V" \
    "$REPO_ROOT/verification" "$HDL_TOPLEVEL" "$BENCH_MODULE" <<'PYEOF'
import json
import os
import sys

(request_path, netlist_abs, sdf_abs, stdcell_abs, udp_abs,
 bench_dir, hdl_toplevel, bench_module) = sys.argv[1:9]
request_dir = os.path.dirname(request_path)
netlist_rel = os.path.relpath(netlist_abs, request_dir)
sdf_rel = os.path.relpath(sdf_abs, request_dir)

request = {
    "schema": "klt.functional_verification.request/1",
    "engine": "icarus",
    "sources": [
        netlist_rel,
        stdcell_abs,   # specify blocks unconditional in the IHP models
        udp_abs,
    ],
    "hdl_toplevel": hdl_toplevel,
    "testbench": {
        # The SAME committed bench the RTL request drives, unmodified --
        # resolved by path so this request can live in the sweep scratch dir.
        "module": bench_module,
        "search_path": bench_dir,
        "testcase": None,
    },
    "options": {
        "coverage": False,
        "timescale": ["1ns", "1ps"],
        "random_seed": 1,
        # The whole point: real post-route delays. corner "typ" picks the
        # typ member of each SDF min:typ:max triplet (iverilog -T typ).
        "sdf": {"file": sdf_rel, "corner": "typ"},
    },
}
with open(request_path, "w", encoding="utf-8") as handle:
    json.dump(request, handle, indent=2)
    handle.write("\n")
PYEOF

  echo "== ${corner} ==" >&2
  start_ts=$(date +%s)
  set +e
  "$KLT" functional-verification "$request_path" --format json \
    > "${corner_dir}/klt-functional-verification.json" \
    2> "${corner_dir}/fv-console.txt"
  run_rc=$?
  set -e
  end_ts=$(date +%s)
  elapsed=$((end_ts - start_ts))

  annotated="false"
  status="failed"
  tests_json="null"
  results_xml=""
  if [ "$run_rc" -eq 0 ] && python3 - "${corner_dir}/klt-functional-verification.json" <<'PYEOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    doc = json.load(handle)
sdf = (doc.get("environment") or {}).get("sdf")
ok = bool(sdf) and sdf.get("annotated") is True
sys.exit(0 if ok else 1)
PYEOF
  then
    annotated="true"
    eval "$(python3 - "${corner_dir}/klt-functional-verification.json" <<'PYEOF'
import json
import shlex
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    doc = json.load(handle)
print(f"status={shlex.quote(str(doc.get('status')))}")
print(f"tests_json={shlex.quote(json.dumps({'test_count': doc.get('test_count'), 'passed_count': doc.get('passed_count'), 'failed_count': doc.get('failed_count'), 'skipped_count': doc.get('skipped_count')}))}")
env = doc.get("environment") or {}
print(f"results_xml={shlex.quote(str(env.get('results_xml') or ''))}")
PYEOF
)"
    if [ -n "$results_xml" ] && [ -f "$results_xml" ]; then
      cp "$results_xml" "${corner_dir}/results_icarus.xml"
    fi
  fi
  echo "   rc=${run_rc} annotated=${annotated} status=${status} elapsed_s=${elapsed}" >&2

  if [ "$run_rc" -ne 0 ] || [ "$annotated" != "true" ] || [ "$status" != "pass" ]; then
    FAILED=1
  fi

  if [ "$first" -eq 0 ]; then
    echo "," >> "${RESULTS_FILE}"
  fi
  first=0
  python3 - "$corner" "${corner_dir}/klt-functional-verification.json" \
    "$run_rc" "$annotated" "$status" "$elapsed" >> "${RESULTS_FILE}" <<'PYEOF'
import json
import sys

corner, output_path, run_rc, annotated, status, elapsed = sys.argv[1:7]
try:
    with open(output_path, encoding="utf-8") as handle:
        response = json.load(handle)
except (OSError, json.JSONDecodeError):
    response = None
entry = {
    "corner": corner,
    "run_rc": int(run_rc),
    "sdf_annotated": annotated == "true",
    "status": status,
    "elapsed_s": int(elapsed),
    "response": response,
}
print(json.dumps(entry, indent=2), end="")
PYEOF
done

echo "]" >> "${RESULTS_FILE}"
python3 -c "import json; json.load(open('${RESULTS_FILE}'))" \
  && echo "wrote ${RESULTS_FILE}" >&2

if [ "$FAILED" -ne 0 ]; then
  echo "FATAL: at least one annotated regression run failed (rc!=0, environment.sdf.annotated!=true, or status!=pass) -- see ${RESULTS_FILE} and the per-corner fv-console.txt files under ${SCRATCH_DIR}/." >&2
  exit 1
fi
