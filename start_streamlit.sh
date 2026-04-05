#!/usr/bin/env bash
# Uruchom z katalogu streamlit_app:  ./start_streamlit.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="python3"
if [[ -x ../.venv/bin/python ]]; then
  PYTHON="../.venv/bin/python"
elif [[ -x .venv/bin/python ]]; then
  PYTHON=".venv/bin/python"
fi

# Zawsze moduł streamlit z wybranego Pythona (działa gdy brak `streamlit` w PATH)
exec "$PYTHON" -m streamlit run app.py \
  --server.address "${STREAMLIT_ADDRESS:-127.0.0.1}" \
  --server.port "${STREAMLIT_PORT:-8501}"
