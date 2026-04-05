#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ../.venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source ../.venv/bin/activate
elif [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

exec streamlit run app.py --server.address "${STREAMLIT_ADDRESS:-127.0.0.1}" --server.port "${STREAMLIT_PORT:-8501}"
