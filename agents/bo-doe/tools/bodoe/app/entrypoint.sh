#!/bin/bash
# Entrypoint for the bo-doe tool container.
#
# The runtime stage copies only the self-contained conda *environment*, not the
# conda installation itself, so there is no `conda.sh` to source and no
# `conda activate` available. Putting the environment's bin directory on PATH
# -- which the Dockerfile already does -- is sufficient, and avoids a hard
# dependency on the conda driver existing in the runtime image.
set -euo pipefail

export PATH="/opt/conda/envs/boenv/bin:${PATH}"
export PYTHONPATH="/app:${PYTHONPATH:-}"

echo "Using Python: $(command -v python)"
echo "Python version: $(python --version 2>&1)"

python - <<'PY'
import importlib

required = ["numpy", "scipy", "pandas", "sklearn", "matplotlib",
            "space", "doe", "models", "acquisition", "optimize", "plots",
            "io_utils", "bodoe_utils"]
optional = ["torch", "botorch", "gpytorch"]

missing = []
for mod in required:
    try:
        importlib.import_module(mod)
        print(f"OK   {mod}")
    except ImportError as exc:
        print(f"MISS {mod}: {exc}")
        missing.append(mod)

for mod in optional:
    try:
        m = importlib.import_module(mod)
        print(f"OK   {mod} {getattr(m, '__version__', '')}")
    except ImportError as exc:
        print(f"WARN {mod} unavailable (sklearn backend will be used): {exc}")

from models import available_backends
print("GP backends:", available_backends())

if missing:
    raise SystemExit(f"missing required modules: {missing}")
PY

exec "$@"
