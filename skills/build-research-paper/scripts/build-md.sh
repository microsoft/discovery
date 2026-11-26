#!/usr/bin/env bash
# Build a paper with pandoc (escape hatch: markdown source).
#
# Usage: build-md.sh [report-dir] [source.md]
#   defaults: ./report/manuscript.md, header ./report/header.tex
#
# Requires: pandoc, tectonic (used as the pdf-engine).

set -euo pipefail

DIR="${1:-report}"
SRC="${2:-manuscript.md}"

if [[ ! -f "${DIR}/${SRC}" ]]; then
  echo "error: ${DIR}/${SRC} not found" >&2
  exit 1
fi

for bin in pandoc tectonic; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "error: $bin not installed" >&2
    exit 1
  fi
done

cd "$DIR"

HEADER_ARGS=()
if [[ -f header.tex ]]; then
  HEADER_ARGS+=(--include-in-header=header.tex)
fi

BIB_ARGS=()
if [[ -f references.bib ]]; then
  BIB_ARGS+=(--citeproc --bibliography=references.bib)
fi

echo "→ pandoc ${SRC} → main.pdf (tectonic engine)…"
pandoc "$SRC" \
  -o main.pdf \
  --pdf-engine=tectonic \
  --pdf-engine-opt=--keep-logs \
  "${HEADER_ARGS[@]}" \
  "${BIB_ARGS[@]}"

echo "✓ ${DIR}/main.pdf"
