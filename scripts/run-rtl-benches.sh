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

BENCHES=(
  protocol-emulator
  control-space
  boot-rom
  program-memory
  protocol-models
  firmware-uart
  firmware-uart-rx
  firmware-spi
  firmware-i2c
  firmware-i2c-sr
  firmware-roundtrip
  random-regression
)

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
