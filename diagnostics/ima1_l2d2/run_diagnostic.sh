#!/usr/bin/env bash
set -euo pipefail
l2d2_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
case "${1:-}" in off|on) ;; *) echo 'Usage: run_diagnostic.sh off|on (one 30-second hardware run)' >&2; exit 2;; esac
python3 - "$l2d2_dir" <<'PY'
import pathlib,json,sys,os
root=pathlib.Path(sys.argv[1]);status=json.loads((root/'software_status.json').read_text())
if status.get('software_validation')!='PASS':
    raise SystemExit('Not ready for hardware: '+str(status))
for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        exe=pathlib.Path(os.readlink(p/'exe')).name
        if exe=='zed_capture_node':raise SystemExit('Existing capture PID '+p.name+'; no process was stopped')
    except (FileNotFoundError,PermissionError):continue
PY
exec /home/jetson/clock_diag/run_joint_test.sh --duration 30 --config "$l2d2_dir/capture_ima1_diag_$1.yaml"
