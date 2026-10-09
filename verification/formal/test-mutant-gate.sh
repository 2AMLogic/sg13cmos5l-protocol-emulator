#!/usr/bin/env bash
# Regression for the runner's negative-control gate: a mutant-only solver
# failure (nonzero exit, no assertion counterexample, no trace) must make
# run-no-data-dependent-latency.sh exit nonzero rather than be accepted as
# "counterexample found". The conformant legs run the real yosys-smtbmc; only
# the call on a *mutant*.smt2 model is replaced by an injected failure.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL_SMTBMC="$(command -v yosys-smtbmc)" || { echo "ERROR: yosys-smtbmc not found on PATH" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
cat >"$WORK/bin/yosys-smtbmc" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do
  case "\$a" in
    *mutant*.smt2) echo "ERROR: injected solver failure (no counterexample)"; exit 2;;
  esac
done
exec "$REAL_SMTBMC" "\$@"
EOF
chmod +x "$WORK/bin/yosys-smtbmc"

PATH="$WORK/bin:$PATH" DUT="${DUT:-fixture}" BMC_DEPTH="${BMC_DEPTH:-8}" \
  "$SCRIPT_DIR/run-no-data-dependent-latency.sh" "$WORK/art" >"$WORK/run.log" 2>&1
rc=$?

if [ "$rc" -eq 0 ] || grep -q 'counterexample found as required' "$WORK/run.log"; then
  echo "FAIL: runner accepted an injected mutant-only solver failure (rc=$rc)" >&2
  tail -15 "$WORK/run.log" >&2
  exit 1
fi
if ! grep -q 'solver/tool failure' "$WORK/run.log"; then
  echo "FAIL: runner failed, but not via the solver/tool-failure path (rc=$rc)" >&2
  tail -15 "$WORK/run.log" >&2
  exit 1
fi
echo "PASS: mutant-only solver failure is rejected (runner rc=$rc)"
