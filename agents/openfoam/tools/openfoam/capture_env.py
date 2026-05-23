#!/usr/bin/env python3
"""Capture OpenFOAM environment variables to a flat shell file."""
import os

with open('/app/openfoam_env.sh', 'w') as f:
    f.write('# OpenFOAM env snapshot (captured at build time)\n')
    for k, v in sorted(os.environ.items()):
        if any(k.startswith(p) for p in ('FOAM_', 'WM_', 'MPI_')) or k in ('PATH', 'LD_LIBRARY_PATH'):
            escaped = v.replace("'", "'\"'\"'")
            f.write(f"export {k}=\'{escaped}\'\n")

print("Captured env vars to /app/openfoam_env.sh:")
print(open('/app/openfoam_env.sh').read())
