#!/bin/bash
# chip-rtl-design tool entrypoint -- ensures I/O dirs exist, then runs the command.
set -e
mkdir -p /input /output /workdir
# Fail-closed arg routing: if the first argument looks like a JSON params blob
# (starts with '{') rather than an executable, the caller passed params as the
# command by mistake. Route it through run.py so the tool still emits a
# well-formed CDE instead of the shell failing with "exec: {json}: not found".
if [ "$#" -ge 1 ] && printf '%s' "$1" | grep -q '^[[:space:]]*{'; then
  exec python3 -u /app/run.py "$@"
fi
exec "$@"