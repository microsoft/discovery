#!/bin/bash
# chip-functional-verification tool entrypoint -- ensures I/O dirs exist, then runs the command.
set -e
mkdir -p /input /output /workdir
if [ "$#" -ge 1 ] && printf '%s' "$1" | grep -q '^[[:space:]]*{'; then
  exec python3 -u /app/run.py "$@"
fi
exec "$@"
