#!/usr/bin/env bash
# scripts/run-rtl-benches.sh -- pass/fail gate over the PDK-free RTL-level
# cocotb benches under verification/ (issue #117). Used by ci.yml's
# `rtl-benches` job; also runnable locally.
#
# Each bench is driven by `klt functional-verification` against its
# verification/request-*.json (the requests carry the sources, the recorded
# random seed and the defines the benches assert on, so plain cocotb/make
# is NOT an equivalent route). Needs `klt` + cocotb on PATH (see
# scripts/setup-env.sh) and `iverilog`. No PDK.
#
# This is a gate, not an evidence run: klt's JSON envelope goes to a temp
# dir that is deleted on exit; nothing is written under
# verification/records/ (append-only evidence comes only from deliberate
# local runs). Runs serially. Exit 0 = every bench passed; 1 otherwise.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# The bench list lives in scripts/rtl-bench-inventory.txt (issue #225), which
# classifies every verification/request-*.json as included here or excluded
# with a reason; the check below fails on an unclassified or stale entry.
python3 scripts/check_rtl_bench_inventory.py >&2 || exit 1
# Portable read loop (not `mapfile`, which needs bash >= 4; macOS ships 3.2).
# Capture first so a failing lister is caught rather than hidden by the loop.
bench_list="$(python3 scripts/check_rtl_bench_inventory.py --list-includes)" || exit 1
BENCHES=()
while IFS= read -r line; do
  [ -n "$line" ] && BENCHES+=("$line")
done <<EOF
$bench_list
EOF
if [ "${#BENCHES[@]}" -eq 0 ]; then
  echo "ERROR: bench inventory lists no benches" >&2
  exit 1
fi

command -v klt >/dev/null || { echo "ERROR: klt not on PATH (run scripts/setup-env.sh)" >&2; exit 1; }
command -v iverilog >/dev/null || { echo "ERROR: iverilog not on PATH" >&2; exit 1; }

OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

failed=()
for b in "${BENCHES[@]}"; do
  req="verification/request-$b.json"
  start=$SECONDS
  if klt functional-verification "$req" --format json >"$OUT/$b.json" 2>"$OUT/$b.err"; then
    echo "PASS  $b ($((SECONDS - start))s)"
  else
    echo "FAIL  $b ($((SECONDS - start))s)"
    failed+=("$b")
    grep -h -B1 -A1 '"status": "failed"' "$OUT/$b.json" 2>/dev/null | head -30
    tail -20 "$OUT/$b.err"
  fi
done

if [ "${#failed[@]}" -ne 0 ]; then
  echo "FAILED benches: ${failed[*]}" >&2
  exit 1
fi
echo "all ${#BENCHES[@]} RTL benches passed"
