#!/usr/bin/env bash
set -euo pipefail
probe_root="$(cd -- "$(dirname -- "$0")" && pwd)"
capture_root="$(cd "$probe_root/../.." && pwd)"
mkdir -p "$probe_root/build"
g++ -O2 -std=c++14 -Wall -Wextra -UNDEBUG "$probe_root/native_mode_test.cpp" -o "$probe_root/build/native_mode_test"
g++ -O2 -std=c++14 -Wall -Wextra -UNDEBUG -DVIDEO_MOD_AVAILABLE -DSENSORS_MOD_AVAILABLE \
  -I"$capture_root/vendor/zed-open-capture/include" -I"$capture_root/vendor/hidapi/hidapi" \
  "$probe_root/probe.cpp" "$capture_root/devel/lib/libcapture_oc.a" "$capture_root/devel/lib/libcapture_hidapi.a" \
  -lusb-1.0 -pthread -o "$probe_root/build/zed_v4l2_probe"
# Exercise the same production loop with synthetic syscalls; source is read only.
g++ -O2 -std=c++14 -UNDEBUG -DVIDEO_MOD_AVAILABLE -DSENSORS_MOD_AVAILABLE \
  -I"$capture_root/vendor/zed-open-capture/include" -I"$capture_root/vendor/hidapi/hidapi" \
  "$capture_root/src/zed_capture/test/video_io_test.cpp" \
  "$capture_root/devel/lib/libcapture_oc.a" "$capture_root/devel/lib/libcapture_hidapi.a" \
  -lusb-1.0 -pthread -Wl,--wrap=select,--wrap=ioctl -o "$probe_root/build/production_loop_test"
python3 -B - "$probe_root" "$capture_root" <<'PY'
import hashlib,json,pathlib,subprocess,sys
p,w=map(pathlib.Path,sys.argv[1:])
files=[p/'probe.cpp',p/'native_mode.hpp',p/'native_mode_test.cpp',p/'run.py',p/'analyze.py',p/'build.sh',p/'build/zed_v4l2_probe',w/'devel/lib/libcapture_oc.a',w/'devel/lib/libcapture_hidapi.a',w/'vendor/zed-open-capture/include/videocapture.hpp',w/'vendor/zed-open-capture/src/videocapture.cpp']
record={'compiler':subprocess.check_output(['g++','--version'],text=True),'files':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files},'compile_policy':'O2 C++14; unchanged production static archives; no system installation'}
(p/'build/build_manifest.json').write_text(json.dumps(record,indent=2))
PY
