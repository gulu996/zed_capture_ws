#!/usr/bin/env bash
set -euo pipefail
capture_ws="$(cd -- "$(dirname -- "$0")/.." && pwd)"
source /opt/ros/noetic/setup.bash
source /home/jetson/catkin_ws/devel/setup.bash
cd "$capture_ws"
catkin_make -j2 -DCMAKE_BUILD_TYPE=Release
