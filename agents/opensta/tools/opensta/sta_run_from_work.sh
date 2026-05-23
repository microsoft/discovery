#!/usr/bin/env bash
# sta_run_from_work.sh -- Studio integration for OpenSTA
# Copies files from /mnt/work to /input/, then calls sta_run.sh
set -euo pipefail

mkdir -p /input

# Copy Verilog and SDC files from /mnt/work to /input/
if [ -d "/mnt/work" ]; then
  FOUND=$(find /mnt/work -maxdepth 2 \( -name "*.v" -o -name "*.sv" -o -name "*.sdc" \) 2>/dev/null | wc -l)
  if [ "$FOUND" -eq 0 ]; then
    echo "ERROR: No .v/.sv/.sdc files found in /mnt/work"
    ls -laR /mnt/work/ 2>/dev/null | head -20
    exit 2
  fi
  find /mnt/work -maxdepth 2 \( -name "*.v" -o -name "*.sv" -o -name "*.sdc" \) -exec cp {} /input/ \;
  echo "Copied files from /mnt/work to /input/:"
  ls -la /input/
  echo ""
else
  echo "ERROR: /mnt/work not found"
  exit 2
fi

# Call the main sta_run.sh (it will find files in /input/)
exec bash /app/sta_run.sh
