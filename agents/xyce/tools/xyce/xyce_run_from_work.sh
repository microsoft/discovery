#!/usr/bin/env bash
# xyce_run_from_work.sh -- Studio integration for Xyce
# Copies files from /mnt/work to /input/, then calls xyce_run.sh
set -euo pipefail

mkdir -p /input

if [ -d "/mnt/work" ]; then
  FOUND=$(find /mnt/work -maxdepth 2 \( -name "*.cir" -o -name "*.spice" -o -name "*.sp" -o -name "*.net" \) 2>/dev/null | wc -l)
  if [ "$FOUND" -eq 0 ]; then
    echo "ERROR: No .cir/.spice/.sp/.net files found in /mnt/work"
    ls -laR /mnt/work/ 2>/dev/null | head -20
    exit 2
  fi
  find /mnt/work -maxdepth 2 \( -name "*.cir" -o -name "*.spice" -o -name "*.sp" -o -name "*.net" \) -exec cp {} /input/ \;
  echo "Copied files from /mnt/work to /input/:"
  ls -la /input/
  echo ""
else
  echo "ERROR: /mnt/work not found"
  exit 2
fi

exec bash /app/xyce_run.sh
