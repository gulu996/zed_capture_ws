#!/usr/bin/env bash
set -euo pipefail
probe_root="$(cd -- "$(dirname -- "$0")" && pwd)"
exec python3 -B "$probe_root/run.py" "$@"
