#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
exec python3 "$capture_ws/scripts/session.py" "$@"
