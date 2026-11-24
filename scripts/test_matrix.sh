#!/usr/bin/env bash
# test_matrix.sh — run PhaseForgeStudio test suite in two environments:
#
#   1. full  — .venv with all optional deps (orchid, sage, MF, PFP, blade, ase, …)
#   2. minimal — fresh venv with only pytest + phaseforge-studio core (no optional deps)
#
# Usage:
#   bash scripts/test_matrix.sh           # both environments
#   bash scripts/test_matrix.sh full      # only env 1
#   bash scripts/test_matrix.sh minimal   # only env 2
#
# Requires: uv on PATH

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUI_DIR="$(dirname "$SCRIPT_DIR")"
FULL_VENV="$GUI_DIR/.venv"
MINIMAL_VENV="$GUI_DIR/.venv-minimal"

PASS=0
FAIL=0
RESULTS=()

run_suite() {
  local label="$1"
  local python="$2"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ENV: $label"
  echo "  Python: $python"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if "$python" -m pytest "$GUI_DIR/tests/" -q --tb=short 2>&1; then
    PASS=$((PASS + 1))
    RESULTS+=("PASS  $label")
  else
    FAIL=$((FAIL + 1))
    RESULTS+=("FAIL  $label")
  fi
}

build_minimal_venv() {
  echo ""
  echo "Building minimal venv at $MINIMAL_VENV …"
  if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found — install uv to run minimal env tests" >&2
    exit 1
  fi
  uv venv --python 3.12 "$MINIMAL_VENV" --seed
  # Install only: pytest + the package itself (no optional deps)
  "$MINIMAL_VENV/bin/uv" pip install pytest
  "$MINIMAL_VENV/bin/uv" pip install -e "$GUI_DIR" --no-deps
  echo "Minimal venv ready."
}

MODE="${1:-both}"

if [[ "$MODE" == "full" || "$MODE" == "both" ]]; then
  if [[ ! -x "$FULL_VENV/bin/python" ]]; then
    echo "ERROR: .venv not found — run: cd $GUI_DIR && uv venv && uv pip install -e ." >&2
    exit 1
  fi
  run_suite "full (.venv — all optional deps)" "$FULL_VENV/bin/python"
fi

if [[ "$MODE" == "minimal" || "$MODE" == "both" ]]; then
  if [[ ! -x "$MINIMAL_VENV/bin/python" ]]; then
    build_minimal_venv
  fi
  run_suite "minimal (.venv-minimal — no optional deps)" "$MINIMAL_VENV/bin/python"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo ""
if [[ $FAIL -gt 0 ]]; then
  echo "  $FAIL environment(s) failed."
  exit 1
else
  echo "  All $PASS environment(s) passed."
fi
