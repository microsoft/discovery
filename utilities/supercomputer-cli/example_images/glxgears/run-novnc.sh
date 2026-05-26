#!/bin/bash
set -euo pipefail
VNC_PORT=${VNC_PORT:-5901}
NOVNC_PORT=${NOVNC_PORT:-6080}
WAIT_SECS=${NOVNC_WAIT_SECS:-30}
echo "[novnc] waiting up to ${WAIT_SECS}s for VNC port ${VNC_PORT}"
for i in $(seq 1 "$WAIT_SECS"); do
  if (echo > /dev/tcp/127.0.0.1/${VNC_PORT}) >/dev/null 2>&1; then
    echo "[novnc] VNC is up after ${i}s"
    break
  fi
  sleep 1
done
echo "[novnc] starting noVNC on :${NOVNC_PORT} -> 127.0.0.1:${VNC_PORT}"
exec /opt/noVNC/utils/novnc_proxy --vnc 127.0.0.1:${VNC_PORT} --listen ${NOVNC_PORT}
