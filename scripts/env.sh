#!/usr/bin/env bash
# Local shell only. No global profile/LD_LIBRARY_PATH modification.
set -e
capture_ws="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/noetic/setup.bash
source /home/jetson/catkin_ws/devel/setup.bash
source "$capture_ws/devel/setup.bash"
export PYTHONDONTWRITEBYTECODE=1
