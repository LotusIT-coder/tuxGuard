#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/TuxGuard(1.0.0)"
export PYTHONPATH="$ROOT/TuxGuard(1.0.0)${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" tuxguard_refactored.py "$@"
fi
if [[ -x "$ROOT/TuxGuard(1.0.0)/.venv/bin/python" ]]; then
  exec "$ROOT/TuxGuard(1.0.0)/.venv/bin/python" tuxguard_refactored.py "$@"
fi
exec python3 tuxguard_refactored.py "$@"
