#!/usr/bin/env bash
#
# flow/run-post-layout-sdf-reset-offsets.sh -- issue #305: the `rst_n`
# release-offset bench (verification/sdf_reset_release_offsets.py, offsets
# -3/-1/0/+1/+3 ns around the nominal SDC-aligned release) against the
# post-route netlist with real SDF delays, per corner.
#
# It goes THROUGH flow/run-post-layout-sdf.sh, unchanged: that runner does
# the acquisition (gds run artifacts), the macro-model wrapper, the instance
# renames, the SDF normalization, the SDC alignment and the core-suite klt
# run per corner (which is also the "RTL bench unchanged under SDF" leg).
# This script then reuses the files the runner left in
# flow/post-layout-sdf/ (netlist/*.sim.v, sdf/<corner>.normalized.sdf,
# <corner>/request.json, sdc/alignment.json) and runs one more klt
# functional-verification per corner with only the testbench module swapped
# (sdf_alignment -> sdf_reset_release_offsets), the PE_ALIGN_* variables
# exported from the run's own alignment.json. The runner itself is not
# edited because it is a provenance input of live evidence records
# (verification/check_records.py).
#
# Usage (arguments are the runner's own; corners optional):
#   ./flow/run-post-layout-sdf-reset-offsets.sh --run-id 38550478313
#   ./flow/run-post-layout-sdf-reset-offsets.sh --from <dir> nom_typ_1p20V_25C
#
# Writes flow/post-layout-sdf-reset-offsets-results.json (gitignored) and
# per-corner artifacts under flow/post-layout-sdf/<corner>-reset-offsets/.
# Corners run strictly one at a time. Exit non-zero if the runner fails, a
# run is not SDF-annotated, or any run's status is not pass.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH_DIR="${REPO_ROOT}/flow/post-layout-sdf"
RESULTS_FILE="${REPO_ROOT}/flow/post-layout-sdf-reset-offsets-results.json"
OFFSET_MODULE="sdf_reset_release_offsets"

source "${REPO_ROOT}/flow/_klt.sh"
klt_resolve

# Corners named on the command line (positional, i.e. not a --flag value).
CORNERS=()
args=("$@")
i=0
while [ $i -lt ${#args[@]} ]; do
  case "${args[$i]}" in
    --run-id|--from|--suite|--protocol) i=$((i + 2)) ;;
    -h|--help) sed -n '2,29p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) CORNERS+=("${args[$i]}"); i=$((i + 1)) ;;
  esac
done

"${REPO_ROOT}/flow/run-post-layout-sdf.sh" "$@"

if [ "${#CORNERS[@]}" -eq 0 ]; then
  while IFS= read -r f; do
    CORNERS+=("$(basename "$f" .normalized.sdf)")
  done < <(find "${SCRATCH_DIR}/sdf" -name '*.normalized.sdf' -type f | sort)
fi

ALIGNMENT_JSON="${SCRATCH_DIR}/sdc/alignment.json"
eval "$(python3 - "$ALIGNMENT_JSON" <<'PYEOF'
import json, sys
a = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"export PE_ALIGN_CLK_PERIOD_NS={a['clock_period_ns']!r}")
print(f"export PE_ALIGN_DRIVE_OFFSET_NS={a['drive_offset_ns']!r}")
print(f"export PE_ALIGN_SAMPLE_OFFSET_NS={a['sample_offset_ns']!r}")
PYEOF
)"

echo "[" > "$RESULTS_FILE"
first=1
FAILED=0
for corner in "${CORNERS[@]}"; do
  src_request="${SCRATCH_DIR}/${corner}/request.json"
  if [ ! -f "$src_request" ]; then
    echo "FATAL: ${src_request} missing: the core runner did not produce corner '${corner}'." >&2
    exit 1
  fi
  run_dir="${SCRATCH_DIR}/${corner}-reset-offsets"
  rm -rf "$run_dir"
  mkdir -p "$run_dir"
  python3 - "$src_request" "${run_dir}/request.json" "$OFFSET_MODULE" <<'PYEOF'
import json, os, sys
src, dst, module = sys.argv[1:4]
req = json.load(open(src, encoding="utf-8"))
# Same request, resolved from the same directory depth (sibling of the
# corner dir), only the testbench module differs.
req["testbench"]["module"] = module
json.dump(req, open(dst, "w", encoding="utf-8"), indent=2)
open(dst, "a", encoding="utf-8").write("\n")
PYEOF
  echo "== ${corner} / ${OFFSET_MODULE} ==" >&2
  start_ts=$(date +%s)
  set +e
  "$KLT" functional-verification "${run_dir}/request.json" --format json \
    > "${run_dir}/klt-functional-verification.json" 2> "${run_dir}/fv-console.txt"
  run_rc=$?
  set -e
  elapsed=$(( $(date +%s) - start_ts ))
  [ "$first" -eq 0 ] && echo "," >> "$RESULTS_FILE"
  first=0
  python3 - "$corner" "${run_dir}/klt-functional-verification.json" "$run_rc" "$elapsed" "$run_dir" >> "$RESULTS_FILE" <<'PYEOF' || FAILED=1
import json, shutil, sys
corner, path, rc, elapsed, run_dir = sys.argv[1:6]
try:
    doc = json.load(open(path, encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    doc = None
env = (doc or {}).get("environment") or {}
xml = env.get("results_xml")
if xml:
    try:
        shutil.copy(xml, run_dir + "/results_icarus.xml")
    except OSError:
        pass
annotated = bool((env.get("sdf") or {}).get("annotated") is True)
status = (doc or {}).get("status")
entry = {"corner": corner, "run_rc": int(rc), "sdf_annotated": annotated, "status": status,
         "elapsed_s": int(elapsed), "response": doc}
print(json.dumps(entry, indent=2), end="")
sys.exit(0 if (int(rc) == 0 and annotated and status == "pass") else 1)
PYEOF
  echo "   rc=${run_rc} elapsed_s=${elapsed}" >&2
done
echo "]" >> "$RESULTS_FILE"
python3 -c "import json; json.load(open('${RESULTS_FILE}'))" && echo "wrote ${RESULTS_FILE}" >&2
if [ "$FAILED" -ne 0 ]; then
  echo "FATAL: at least one reset-offset run did not pass annotated (see ${RESULTS_FILE} and ${SCRATCH_DIR}/<corner>-reset-offsets/)." >&2
  exit 1
fi
