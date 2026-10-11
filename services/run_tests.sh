#!/usr/bin/env bash
# Corre pytest de cada servicio por separado (todos tienen un modulo `handler`). Usa $PYTHON (venv con las dependencias).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
rc=0
for d in "$HERE"/../libs/voltera_common "$HERE"/*/ "$HERE"/../experiments/seed; do
  [ -d "$d/tests" ] || continue
  echo "== $(basename "$d")"; (cd "$d" && "$PY" -m pytest -q 2>&1 | tail -1) || rc=1
done
exit $rc
