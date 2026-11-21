#!/bin/sh
# /input is caller-owned and may be read-only.
set -e
mkdir -p /output /workdir
if [ "$#" -ge 1 ] && printf '%s' "$1" | grep -q '^[[:space:]]*{'; then
  exec python3 -u /app/run.py "$@"
fi
exec "$@"
