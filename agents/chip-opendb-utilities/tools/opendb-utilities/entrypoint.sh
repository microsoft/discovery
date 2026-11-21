#!/bin/bash
set -euo pipefail
mkdir -p /input /output /workdir
if [ "$#" -ge 1 ] && printf '%s' "$1" | grep -q '^[[:space:]]*{'; then
  exec python3 -u /app/run.py "$@"
fi
exec "$@"
