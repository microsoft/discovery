#!/usr/bin/env bash
# check-deps.sh — verify the build-research-paper skill's external dependencies.
# Exits non-zero if any required tool or Python module is missing.

set -uo pipefail

missing=0
have() { command -v "$1" >/dev/null 2>&1; }

os_hint() {
  case "$(uname -s)" in
    Darwin) echo "macOS" ;;
    Linux)  echo "Linux" ;;
    *)      echo "unknown" ;;
  esac
}
OS="$(os_hint)"

report_ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
report_miss() { printf "  \033[31m✗\033[0m %s — %s\n" "$1" "$2"; missing=$((missing+1)); }

echo "build-research-paper skill: checking dependencies…"
echo

# --- binaries ---
if have tectonic; then
  report_ok "tectonic ($(tectonic --version 2>&1 | head -1))"
else
  if [ "$OS" = "macOS" ]; then
    report_miss "tectonic" "install: brew install tectonic"
  else
    report_miss "tectonic" "install: cargo install tectonic  (or your distro pkg)"
  fi
fi

if have pandoc; then
  report_ok "pandoc ($(pandoc --version | head -1))"
else
  if [ "$OS" = "macOS" ]; then
    report_miss "pandoc" "install: brew install pandoc  (optional — only needed for markdown escape hatch)"
  else
    report_miss "pandoc" "install: apt install pandoc  (optional — only needed for markdown escape hatch)"
  fi
fi

if have python3; then
  report_ok "python3 ($(python3 --version 2>&1))"
else
  report_miss "python3" "install python3 via your OS package manager"
fi

# --- python modules ---
if have python3; then
  for mod in matplotlib numpy; do
    if python3 -c "import ${mod}" 2>/dev/null; then
      ver="$(python3 -c "import ${mod}; print(${mod}.__version__)" 2>/dev/null)"
      report_ok "python: ${mod} ${ver}"
    else
      report_miss "python: ${mod}" "install: pip install ${mod}  (or: pip install -r $(dirname "$0")/../requirements.txt)"
    fi
  done
fi

echo
if [ "$missing" -eq 0 ]; then
  printf "\033[32mAll dependencies satisfied.\033[0m\n"
  exit 0
else
  printf "\033[31m%d missing dependency(ies).\033[0m See install hints above.\n" "$missing"
  exit 1
fi
