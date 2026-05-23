#!/bin/bash
# OpenFOAM entrypoint — loads pre-captured environment, then runs the command.
#
# We do NOT source the OpenFOAM bashrc at runtime.
# The bashrc triggers a fatal "pop_var_context" error on bash 5.2+.
# Instead, we source /app/openfoam_env.sh which was captured during docker build
# and contains simple export KEY='VALUE' statements — no complex bash functions.

# Prevent any residual BASH_ENV from causing auto-sourcing
unset BASH_ENV

# Load the pre-captured OpenFOAM environment
if [ -f /app/openfoam_env.sh ]; then
    source /app/openfoam_env.sh
else
    echo "[entrypoint] ERROR: /app/openfoam_env.sh not found — OpenFOAM env unavailable" >&2
fi

# Verify OpenFOAM is available
if command -v simpleFoam &>/dev/null; then
    echo "[entrypoint] OpenFOAM environment loaded (pre-captured snapshot)"
    echo "[entrypoint] simpleFoam: $(which simpleFoam)"
else
    echo "[entrypoint] WARNING: OpenFOAM binaries not found after loading env snapshot" >&2
    echo "[entrypoint] PATH=$PATH" >&2
    echo "[entrypoint] Contents of /app/openfoam_env.sh:" >&2
    cat /app/openfoam_env.sh >&2
fi

exec "$@"
