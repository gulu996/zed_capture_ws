#!/usr/bin/env bash
set -euo pipefail
source /home/jetson/zed_capture_ws/scripts/env.sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
exec python3 -B /home/jetson/zed_capture_ws/diagnostics/zed_jpeg_benchmark/benchmark.py "$@"
