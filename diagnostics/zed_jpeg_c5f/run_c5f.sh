#!/usr/bin/env bash
set -euo pipefail
source /home/jetson/zed_capture_ws/scripts/env.sh
exec python3 -B /home/jetson/zed_capture_ws/diagnostics/zed_jpeg_c5f/run_c5f.py "$@"
