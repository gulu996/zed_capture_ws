#!/bin/bash
set -eo pipefail
export PYTHONDONTWRITEBYTECODE=1
source /home/jetson/catkin_ws/devel/setup.bash
exec /usr/bin/python3 -B /home/jetson/zed_capture_ws/diagnostics/gnss_usb/independent_probe.py "$@"
