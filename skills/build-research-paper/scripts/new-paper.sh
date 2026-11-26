#!/usr/bin/env bash
# Scaffold a report/ directory in a project repo.
#
# Usage: new-paper.sh <target-repo-root> [report-subdir]
#   e.g. new-paper.sh ~/projects/myproj              # creates ~/projects/myproj/report/
#   e.g. new-paper.sh ~/projects/myproj manuscript   # creates .../manuscript/
#
# Copies templates from this skill's sibling templates/ directory into the
# target. Refuses to overwrite an existing main.tex — bail loudly.

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATES="${SKILL_DIR}/templates"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <target-repo-root> [report-subdir]" >&2
  exit 2
fi

TARGET_ROOT="$1"
SUBDIR="${2:-report}"
DEST="${TARGET_ROOT%/}/${SUBDIR}"

if [[ ! -d "$TARGET_ROOT" ]]; then
  echo "error: target repo root does not exist: $TARGET_ROOT" >&2
  exit 1
fi

if [[ -f "${DEST}/main.tex" ]]; then
  echo "error: ${DEST}/main.tex already exists — refusing to overwrite" >&2
  echo "       edit it directly, or delete it if you truly want a fresh start" >&2
  exit 1
fi

mkdir -p "${DEST}/figures"

cp -n "${TEMPLATES}/main.tex"             "${DEST}/main.tex"
cp -n "${TEMPLATES}/references.bib"       "${DEST}/references.bib"
cp -n "${TEMPLATES}/generate_figures.py"  "${DEST}/generate_figures.py"
chmod +x "${DEST}/generate_figures.py"

# Only drop header.tex if the user wants the pandoc escape hatch — leave it out
# by default; they can copy it manually.

cat > "${DEST}/README.md" <<'EOF'
# Report

Manuscript sources for this project. Built with the `build-research-paper` skill.

## Build

```bash
tectonic main.tex          # produces main.pdf
```

## Regenerate figures

```bash
python3 generate_figures.py            # all
python3 generate_figures.py fig1       # one
```

## Files

- `main.tex` — the manuscript
- `references.bib` — bibliography
- `generate_figures.py` — figure pipeline (writes .pdf + .png to `figures/`)
- `figures/` — publication figures (both .pdf and .png variants)
EOF

echo "✓ scaffolded ${DEST}"
echo "  next: cd ${DEST} && tectonic main.tex"
