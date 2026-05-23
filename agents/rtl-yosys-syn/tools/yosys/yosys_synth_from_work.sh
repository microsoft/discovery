#!/usr/bin/env bash
# yosys_synth_from_work.sh -- Studio integration wrapper
# Copies Verilog files from /mnt/work to /input, then calls yosys_synth.sh
set -euo pipefail

WORK_DIR="/mnt/work"
INPUT_DIR="/input"

mkdir -p "${INPUT_DIR}"

if [ ! -d "${WORK_DIR}" ]; then
  echo "ERROR: /mnt/work not found -- this action requires Studio storage assets"
  exit 2
fi

# Copy all Verilog files
COPIED=0
for ext in v sv vh svh; do
  for f in "${WORK_DIR}"/*.${ext} "${WORK_DIR}"/**/*.${ext}; do
    if [ -f "$f" ] 2>/dev/null; then
      cp "$f" "${INPUT_DIR}/"
      echo "Copied: $(basename $f)"
      COPIED=$((COPIED + 1))
    fi
  done
done

if [ "${COPIED}" -eq 0 ]; then
  echo "ERROR: No .v/.sv/.vh/.svh files found in /mnt/work"
  ls -la "${WORK_DIR}/" 2>/dev/null || true
  exit 2
fi

echo "Copied ${COPIED} file(s) from /mnt/work to /input"

# Re-export so yosys_synth.sh reads from /input
export INPUT="/input"
exec bash /app/yosys_synth.sh
