#!/usr/bin/env bash
# xyce_run.sh -- Run Xyce SPICE simulation
# Expects environment variables:
#   FILE       -- SPICE netlist filename
#   TESTBENCH  -- Optional testbench filename
#   PDK        -- Target PDK: sky130 (default) or gf180mcu
#   SIM_TYPE   -- Simulation type: tran (default), noise, tran+noise
#   SIM_TIME   -- Transient sim end time (default: 100n)
#   SIM_STEP   -- Transient sim step (default: 0.1n)
set -euo pipefail

FILE="${FILE:-}"
if [ -z "${FILE}" ]; then
  echo "ERROR: FILE environment variable not set"
  exit 2
fi

# --- Resolve input file (6-case fallback) ---
SRC_FILE=""
TB_FILE=""

echo "=== Input Resolution Debug ==="
echo "  FILE=${FILE}"
echo "  TESTBENCH=${TESTBENCH:-<not provided>}"
echo "  /mnt/input exists: $(test -e /mnt/input && echo yes || echo no)"
echo "  /mnt/input is dir: $(test -d /mnt/input && echo yes || echo no)"
echo "  /mnt/input is file: $(test -f /mnt/input && echo yes || echo no)"
if [ -d "/mnt/input" ]; then
  echo "  /mnt/input contents:"
  find /mnt/input -type f \( -name "*.cir" -o -name "*.spice" -o -name "*.sp" -o -name "*.net" \) 2>/dev/null | head -20 | sed 's/^/    /'
fi
echo "  /input exists: $(test -e /input && echo yes || echo no)"
if [ -d "/input" ]; then
  echo "  /input contents:"
  ls -la /input/ 2>/dev/null | head -10 | sed 's/^/    /'
fi
echo ""

# Case 1-6: same pattern as OpenSTA
if [ -d "/mnt/input" ] && [ -f "/mnt/input/${FILE}" ]; then
  SRC_FILE="/mnt/input/${FILE}"
elif [ -d "/mnt/input" ]; then
  FOUND=$(find /mnt/input -type f -name "${FILE}" 2>/dev/null | head -1)
  [ -n "${FOUND}" ] && SRC_FILE="${FOUND}"
fi
if [ -z "${SRC_FILE}" ] && [ -f "/mnt/input" ]; then
  SRC_FILE="/mnt/input"
fi
if [ -z "${SRC_FILE}" ] && [ -d "/input" ] && [ -f "/input/${FILE}" ]; then
  SRC_FILE="/input/${FILE}"
fi
if [ -z "${SRC_FILE}" ] && [ -d "/input" ]; then
  FOUND=$(find /input -type f -name "${FILE}" 2>/dev/null | head -1)
  [ -n "${FOUND}" ] && SRC_FILE="${FOUND}"
fi
if [ -z "${SRC_FILE}" ]; then
  for DIR in /mnt/input /input; do
    if [ -d "${DIR}" ]; then
      FOUND=$(find "${DIR}" -type f \( -name "*.cir" -o -name "*.spice" -o -name "*.sp" \) 2>/dev/null | head -1)
      if [ -n "${FOUND}" ]; then
        echo "WARNING: Could not find '${FILE}' but found '${FOUND}', using it."
        SRC_FILE="${FOUND}"
        break
      fi
    fi
  done
fi

if [ -z "${SRC_FILE}" ]; then
  echo "ERROR: Could not find netlist '${FILE}'"
  ls -laR /mnt/ 2>/dev/null | head -30 || true
  ls -laR /input/ 2>/dev/null | head -30 || true
  exit 2
fi
echo "Resolved netlist: ${SRC_FILE}"

# --- Resolve testbench file (if provided) ---
TESTBENCH="${TESTBENCH:-}"
if [ -n "${TESTBENCH}" ]; then
  for DIR in /mnt/input /input; do
    if [ ! -d "${DIR}" ]; then continue; fi
    if [ -f "${DIR}/${TESTBENCH}" ]; then
      TB_FILE="${DIR}/${TESTBENCH}"
      break
    fi
    FOUND=$(find "${DIR}" -type f -name "${TESTBENCH}" 2>/dev/null | head -1)
    if [ -n "${FOUND}" ]; then
      TB_FILE="${FOUND}"
      break
    fi
  done
  if [ -n "${TB_FILE}" ]; then
    echo "Resolved testbench: ${TB_FILE}"
  else
    echo "WARNING: Testbench '${TESTBENCH}' not found, will auto-generate."
  fi
fi

# --- Parameters ---
PDK="${PDK:-sky130}"
SIM_TYPE="${SIM_TYPE:-tran}"
SIM_TIME="${SIM_TIME:-100n}"
SIM_STEP="${SIM_STEP:-0.1n}"
BASENAME=$(basename "${FILE}" .cir)
BASENAME=$(basename "${BASENAME}" .spice)
BASENAME=$(basename "${BASENAME}" .sp)

mkdir -p /output

# --- Determine what to simulate ---
# If user provided a testbench, use it directly
# If the netlist already has .tran/.dc/.ac, run it directly
# Otherwise, auto-generate a testbench
RUN_FILE=""

if [ -n "${TB_FILE}" ]; then
  echo "Using user-provided testbench: ${TB_FILE}"
  RUN_FILE="${TB_FILE}"
elif grep -qiE '^\.(tran|dc|ac|noise)\b' "${SRC_FILE}" 2>/dev/null; then
  echo "Netlist contains analysis statements."
  # Check if netlist already has PDK includes (user-provided complete testbench)
  if grep -qiE '^\.(lib|include).*pdk|^\.(lib|include).*(sky130|gf180|sm141064)' "${SRC_FILE}" 2>/dev/null; then
    echo "Netlist already has PDK includes, running directly."
    RUN_FILE="${SRC_FILE}"
  else
    echo "Prepending PDK includes for ${PDK}..."
    WRAPPED="/tmp/${BASENAME}_wrapped.cir"
    python3 /app/xyce_utils.py prepend-pdk \
      --netlist "${SRC_FILE}" \
      --pdk "${PDK}" \
      --output "${WRAPPED}" 2>&1
    echo "Wrapped netlist: ${WRAPPED}"
    cat "${WRAPPED}" | head -20
    echo "..."
    RUN_FILE="${WRAPPED}"
  fi
else
  echo "Auto-generating testbench..."
  TB_GEN="/tmp/${BASENAME}_tb.cir"
  python3 /app/xyce_utils.py generate-testbench \
    --netlist "${SRC_FILE}" \
    --pdk "${PDK}" \
    --sim-type "${SIM_TYPE}" \
    --sim-time "${SIM_TIME}" \
    --sim-step "${SIM_STEP}" \
    --output "${TB_GEN}" 2>&1
  echo "Generated testbench: ${TB_GEN}"
  cat "${TB_GEN}"
  echo ""
  RUN_FILE="${TB_GEN}"
fi

echo "=== Xyce Simulation ==="
echo "  Netlist:   ${SRC_FILE}"
echo "  Run file:  ${RUN_FILE}"
echo "  PDK:       ${PDK}"
echo "  Sim type:  ${SIM_TYPE}"
echo "  Sim time:  ${SIM_TIME}"
echo "  Sim step:  ${SIM_STEP}"
echo ""

# --- Run transient simulation ---
LOG="/output/${BASENAME}_sim.log"
Xyce -hspice-ext all -o "/output/${BASENAME}" "${RUN_FILE}" 2>&1 | tee "${LOG}"
XYCE_EXIT=$?

if [ ${XYCE_EXIT} -ne 0 ]; then
  echo "WARNING: Xyce exited with code ${XYCE_EXIT}"
fi

# --- Run noise simulation if requested ---
if [[ "${SIM_TYPE}" == *"noise"* ]] && [ "${SIM_TYPE}" != "tran" ]; then
  echo ""
  echo "=== Noise Analysis ==="
  NOISE_TB="/tmp/${BASENAME}_noise.cir"
  python3 /app/xyce_utils.py generate-noise-testbench \
    --netlist "${SRC_FILE}" \
    --pdk "${PDK}" \
    --output "${NOISE_TB}" 2>&1 || echo "WARNING: Could not generate noise testbench"

  if [ -f "${NOISE_TB}" ]; then
    Xyce -hspice-ext all -o "/output/${BASENAME}_noise" "${NOISE_TB}" 2>&1 | tee -a "${LOG}"
  fi
fi

# --- Copy auto-generated testbench to output ---
if [ -f "/tmp/${BASENAME}_tb.cir" ]; then
  cp "/tmp/${BASENAME}_tb.cir" "/output/${BASENAME}_testbench.cir"
fi

# --- Parse results and generate summary ---
SUMMARY="/output/${BASENAME}_summary.txt"
python3 /app/xyce_utils.py parse-results \
  --basename "/output/${BASENAME}" \
  --log "${LOG}" \
  --output "${SUMMARY}" 2>&1 || {
  echo "Warning: Could not parse results, copying raw log"
  cp "${LOG}" "${SUMMARY}"
}

echo ""
echo "=== Done ==="
echo "Output files:"
ls -la /output/ 2>/dev/null
echo ""
cat "${SUMMARY}"
