#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/env.sh"
if [ "$#" -lt 1 ]; then echo 'Usage: replay.sh SESSION_DIR [rosbag play options]' >&2; exit 2; fi
capture_session="$1"
shift
# Remap to /replay to avoid feeding live sensor consumers. No /use_sim_time mutation.
exec rosbag play --pause "$capture_session/data.bag" "$@" \
 /zed2i/left/image_raw:=/replay/zed2i/left/image_raw \
 /zed2i/right/image_raw:=/replay/zed2i/right/image_raw \
 /zed2i/imu/data_raw:=/replay/zed2i/imu/data_raw \
 /livox/lidar:=/replay/livox/lidar /livox/imu:=/replay/livox/imu \
 /zed2i/video_stamp:=/replay/zed2i/video_stamp \
 /zed2i/imu_stamp:=/replay/zed2i/imu_stamp \
 /zed2i/time_anchor:=/replay/zed2i/time_anchor \
 /zed2i/diagnostics:=/replay/zed2i/diagnostics \
 /livox_lidar_publisher2/timestamp_diagnostics:=/replay/livox/timestamp_diagnostics
