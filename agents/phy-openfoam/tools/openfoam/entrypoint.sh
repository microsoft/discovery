#!/bin/bash
set -eo pipefail
# The command is an argument vector from trusted host code, never a case string.
source /opt/openfoam14/etc/bashrc
export PATH="/opt/physics-venv/bin:${PATH}"
exec "$@"