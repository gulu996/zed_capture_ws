#!/usr/bin/env python3
import argparse,json,os,pathlib,signal
ap=argparse.ArgumentParser();ap.add_argument('session');args=ap.parse_args()
session=pathlib.Path(args.session).resolve();control=json.loads((session/'control.json').read_text());pid=control['manager_pid']
try:
    ticks=pathlib.Path('/proc/%d/stat'%pid).read_text().split(') ',1)[1].split()[19]
    command=pathlib.Path('/proc/%d/cmdline'%pid).read_bytes()
except FileNotFoundError:raise SystemExit('Capture manager already stopped')
if ticks!=control['start_ticks'] or b'/scripts/session.py' not in command:raise SystemExit('PID identity mismatch; nothing signaled')
os.kill(pid,signal.SIGINT);print('Graceful stop requested; allow bag writer to drain and close.')
