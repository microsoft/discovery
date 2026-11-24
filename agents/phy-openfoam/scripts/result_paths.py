"""Source-entry loader for the shared developer router and canonical skill guard.

Load the checkout's router explicitly, not an unrelated installed benchmark
version. Compiling source directly avoids writing bytecode into the contribution.
"""

from pathlib import Path
from types import ModuleType

_source = (Path(__file__).resolve().parents[1]
           / "tools/openfoam/src/discovery_physics/benchmarks/output_paths.py")
_module = ModuleType("phy_openfoam_developer_output_paths")
_module.__file__ = str(_source)
exec(compile(_source.read_text(encoding="utf-8"), str(_source), "exec"), _module.__dict__)

ResultPaths = _module.ResultPaths
add_arguments = _module.add_arguments
load_guard = _module.load_guard
write_bundle = _module.write_bundle
main = _module.main

if __name__ == "__main__":
    raise SystemExit(main())