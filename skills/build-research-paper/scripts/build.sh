#!/usr/bin/env bash
# Build a paper with tectonic (default workflow).
#
# Usage: build.sh [report-dir]   (default: ./report)

set -euo pipefail

DIR="${1:-report}"

if [[ ! -f "${DIR}/main.tex" ]]; then
  echo "error: ${DIR}/main.tex not found" >&2
  exit 1
fi

if ! command -v tectonic >/dev/null 2>&1; then
  echo "error: tectonic not installed" >&2
  echo "       run bash $(dirname "$0")/check-deps.sh for platform-specific guidance" >&2
  exit 1
fi

echo "→ building ${DIR}/main.tex with tectonic…"
cd "$DIR"

# --keep-logs so check.sh can inspect main.log afterwards.
tectonic --keep-logs --print main.tex

echo "✓ ${DIR}/main.pdf"
if [[ -f main.pdf ]]; then
  pages=$(mdls -name kMDItemNumberOfPages -raw main.pdf 2>/dev/null || echo "?")
  size=$(ls -lh main.pdf | awk '{print $5}')
  echo "  ${pages} pages, ${size}"
fi
