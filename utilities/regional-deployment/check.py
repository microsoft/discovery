#!/usr/bin/env python3
"""Local tests and Bicep compilation only: never signs in or calls ARM."""

import argparse
import json
from pathlib import Path
import py_compile
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from deploy import assert_resume_template
from workspace import assert_workspace_template

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-bicep", action="store_true", help="Run Python-only checks when Azure CLI/Bicep is not installed.")
    args = parser.parse_args()
    with patch("subprocess.run", side_effect=AssertionError("Unit tests must not execute external commands or Azure CLI.")):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/"tests")))
    if not result.wasSuccessful():
        return 1
    for source in ROOT.glob("*.py"):
        py_compile.compile(str(source), doraise=True)
    if not args.skip_bicep:
        with tempfile.TemporaryDirectory(prefix="discovery-regional-bicep-") as directory:
            compiled = {}
            for name in ("main", "discovery", "workspace", "workspace-core"):
                output = Path(directory)/(name+".json")
                subprocess.run(["az", "bicep", "build", "--file", str(ROOT/"templates"/(name+".bicep")),
                                "--outfile", str(output), "--only-show-errors"], check=True)
                compiled[name] = json.loads(output.read_text())
            assert_resume_template(compiled["discovery"])
            assert_workspace_template(compiled["workspace"])
            assert_workspace_template(compiled["workspace-core"], True)
        print("Four local Bicep builds and bounded resource-shape checks passed.")
    print("No Azure sign-in, ARM validation, resource deployment or inference was performed by these checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
