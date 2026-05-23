#!/usr/bin/env bash
# yosys_synth.sh -- Synthesize a Verilog design using Yosys
# Called by the yosys_synth action. Expects environment variables:
#   FILE  -- Verilog filename (relative to input mount)
#   TOP   -- top-level module name (optional, auto-detect if empty)
#   PDK   -- target PDK: sky130 (default) or gf180mcu
set -euo pipefail

FILE="${FILE:-}"
if [ -z "${FILE}" ]; then
  echo "ERROR: FILE environment variable not set"
  exit 2
fi

# --- Resolve input file ---
# Studio can mount files in several ways:
#   1. Directory mount: /mnt/input/ is a directory containing the file
#   2. File mount: /mnt/input itself IS the file (single file URI)
#   3. Workbench mount: /input/ is a directory containing the file
#   4. File might be in a subdirectory of /mnt/input/
SRC_FILE=""

# Debug: show what's actually mounted
echo "=== Input Resolution Debug ==="
echo "  FILE=${FILE}"
echo "  /mnt/input exists: $(test -e /mnt/input && echo yes || echo no)"
echo "  /mnt/input is dir: $(test -d /mnt/input && echo yes || echo no)"
echo "  /mnt/input is file: $(test -f /mnt/input && echo yes || echo no)"
if [ -d "/mnt/input" ]; then
  echo "  /mnt/input contents:"
  find /mnt/input -type f -name "*.v" -o -name "*.sv" 2>/dev/null | head -20 | sed 's/^/    /'
  ls -la /mnt/input/ 2>/dev/null | head -10 | sed 's/^/    /'
fi
echo "  /input exists: $(test -e /input && echo yes || echo no)"
if [ -d "/input" ]; then
  echo "  /input contents:"
  ls -la /input/ 2>/dev/null | head -10 | sed 's/^/    /'
fi
echo ""

# Case 1: /mnt/input is a directory and contains the file directly
if [ -d "/mnt/input" ] && [ -f "/mnt/input/${FILE}" ]; then
  SRC_FILE="/mnt/input/${FILE}"

# Case 2: /mnt/input is a directory, file might be in a subdirectory
elif [ -d "/mnt/input" ]; then
  FOUND=$(find /mnt/input -type f -name "${FILE}" 2>/dev/null | head -1)
  if [ -n "${FOUND}" ]; then
    SRC_FILE="${FOUND}"
  fi
fi

# Case 3: /mnt/input itself IS the file (single-file mount)
if [ -z "${SRC_FILE}" ] && [ -f "/mnt/input" ]; then
  SRC_FILE="/mnt/input"
fi

# Case 4: /input directory (workbench mode)
if [ -z "${SRC_FILE}" ] && [ -d "/input" ] && [ -f "/input/${FILE}" ]; then
  SRC_FILE="/input/${FILE}"
fi

# Case 5: search /input recursively
if [ -z "${SRC_FILE}" ] && [ -d "/input" ]; then
  FOUND=$(find /input -type f -name "${FILE}" 2>/dev/null | head -1)
  if [ -n "${FOUND}" ]; then
    SRC_FILE="${FOUND}"
  fi
fi

# Case 6: find ANY .v or .sv file in mounted dirs (last resort)
if [ -z "${SRC_FILE}" ]; then
  for DIR in /mnt/input /input; do
    if [ -d "${DIR}" ]; then
      FOUND=$(find "${DIR}" -type f \( -name "*.v" -o -name "*.sv" \) 2>/dev/null | head -1)
      if [ -n "${FOUND}" ]; then
        echo "WARNING: Could not find '${FILE}' but found '${FOUND}', using it."
        SRC_FILE="${FOUND}"
        break
      fi
    fi
  done
fi

if [ -z "${SRC_FILE}" ]; then
  echo "ERROR: Could not find Verilog file '${FILE}'"
  echo "  Searched: /mnt/input/${FILE}, /input/${FILE}, recursive search"
  echo "  Mount contents:"
  ls -laR /mnt/ 2>/dev/null | head -30 || true
  ls -laR /input/ 2>/dev/null | head -30 || true
  exit 2
fi

echo "Resolved input file: ${SRC_FILE}"

# --- PDK selection ---
PDK="${PDK:-sky130}"
case "${PDK}" in
  sky130)
    LIB_FILE="/app/pdk/sky130_fd_sc_hd__tt_025C_1v80.lib"
    ;;
  gf180mcu)
    LIB_FILE="/app/pdk/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib"
    ;;
  *)
    echo "ERROR: Unknown PDK '${PDK}'. Supported: sky130, gf180mcu"
    exit 2
    ;;
esac

if [ ! -f "${LIB_FILE}" ]; then
  echo "ERROR: Liberty file not found: ${LIB_FILE}"
  exit 2
fi

# --- Build Yosys script ---
TOP_CMD=""
if [ -n "${TOP:-}" ]; then
  TOP_CMD="-top ${TOP}"
fi

BASENAME=$(basename "${FILE}" .v)
BASENAME=$(basename "${BASENAME}" .sv)
NETLIST="/output/${BASENAME}_netlist.v"
REPORT="/output/${BASENAME}_synth_report.txt"
LOG="/output/${BASENAME}_synth.log"

mkdir -p /output

cat > /tmp/synth.ys <<EOF
read_verilog ${SRC_FILE}
synth ${TOP_CMD}
dfflibmap -liberty ${LIB_FILE}
abc -liberty ${LIB_FILE}
clean
write_verilog -noattr ${NETLIST}
stat -liberty ${LIB_FILE}
EOF

echo "=== Yosys Synthesis ==="
echo "  Source:  ${SRC_FILE}"
echo "  PDK:    ${PDK}"
echo "  Liberty: ${LIB_FILE}"
echo "  Top:    ${TOP:-auto-detect}"
echo "  Netlist: ${NETLIST}"
echo ""

# --- Run Yosys ---
yosys -s /tmp/synth.ys -l "${LOG}" 2>&1

# --- Extract report from log ---
echo "=== Synthesis Report ===" > "${REPORT}"
echo "PDK: ${PDK}" >> "${REPORT}"
echo "Source: ${FILE}" >> "${REPORT}"
echo "Top: ${TOP:-auto-detect}" >> "${REPORT}"
echo "" >> "${REPORT}"

# Extract the stat output (cell counts and area)
python3 /app/yosys_utils.py parse-log "${LOG}" >> "${REPORT}" 2>&1 || {
  echo "Warning: Could not parse log, appending raw stat section"
  sed -n '/^=== .* ===/,/^$/p' "${LOG}" >> "${REPORT}"
}

echo ""
echo "=== Done ==="
echo "Netlist: ${NETLIST}"
echo "Report:  ${REPORT}"
echo "Log:     ${LOG}"
cat "${REPORT}"
