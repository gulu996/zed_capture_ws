#!/usr/bin/env bash
set -euo pipefail
source /home/jetson/zed_capture_ws/scripts/env.sh
export PYTHONDONTWRITEBYTECODE=1
field_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
exec /usr/bin/python3 -B "$field_dir/field_capture.py" stop "$@"
