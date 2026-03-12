#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/start-api.sh"
"$SCRIPT_DIR/start-worker.sh"
"$SCRIPT_DIR/start-scheduler.sh"
