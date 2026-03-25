#!/usr/bin/env bash
set -euo pipefail

PIPELINE="${1:-all}"
PROFILE="${2:-smoke}"

cd "$(dirname "$0")/../backend"
uv run python -m evals.run "$PIPELINE" "$PROFILE"
