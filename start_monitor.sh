#!/bin/bash
set -euo pipefail

sleep 15
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export DISPLAY=:0
export GDK_BACKEND=x11
export NO_AT_BRIDGE=1

echo "--- Start programu: $(date) ---" >> start_log.txt
/usr/bin/python3 monitor_boost.py >> start_log.txt 2>&1
