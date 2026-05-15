"""Definition Content Creator

Converts a YAML definition file to JSON either as:
    1. An escaped single-line string (suitable for embedding in ARM/Bicep templates), OR
    2. Pretty formatted JSON (when --json is passed)

Enhancements vs. original version:
    * Graceful message when PyYAML is missing instead of a raw ModuleNotFoundError.
    * Clear, copy‑paste install guidance.
    * Corrected filename in usage docs.

Usage:
    python utils/definition-content-creator.py path/to/file.yaml [--output out.txt] [--json]
    python utils/definition-content-creator.py --check

Examples:
        # Produce escaped JSON string (default) and print to stdout
        python utils/definition-content-creator.py 6-solutions/tools-and-models/rdkit-tool/rdkit-tool-definition.yaml

        # Produce pretty JSON and write to a file
        python utils/definition-content-creator.py 6-solutions/tools-and-models/rdkit-tool/rdkit-tool-definition.yaml \
                --json --output rdkit-tool.json

Exit codes:
    0 success / check passed
    1 unexpected internal error
    2 dependency missing / invalid usage / check failed
"""
import sys
import json
import argparse

def yaml_to_json(yaml_file_path, output_file=None, as_string=True):
    """
    Convert YAML file to JSON, either as a string suitable for embedding in ARM templates
    or as proper formatted JSON.
    
    For files that contain a "workflow" object, this function will:
    1. Copy the name from the "agent" object to the "workflow" object
    2. Remove the "agent" object from the data after copying its name
    
    Args:
        yaml_file_path (str): Path to the YAML file.
        output_file (str, optional): Output file path. If not provided, prints to stdout.
        as_string (bool): If True, outputs an escaped JSON string for ARM templates.
                         If False, outputs proper JSON.
    """
    # Lazy import so that running the script with -h or without arguments
    # shows argparse usage instead of a dependency error if PyYAML is missing.
    try:  # pragma: no cover (environment-specific import path)
        import yaml  # type: ignore
    except ModuleNotFoundError:
        sys.stderr.write(
            "ERROR: Missing required dependency 'PyYAML'.\n"
            "Install it with one of:\n"
            "  pip install pyyaml\n"
            "  python -m pip install pyyaml\n"
            "(Consider using a virtual environment.)\n"
        )
        sys.exit(2)

    try:
        with open(yaml_file_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: File not found: {yaml_file_path}\n")
        sys.exit(2)
    except yaml.YAMLError as e:
        sys.stderr.write(f"ERROR: Failed to parse YAML: {e}\n")
        sys.exit(1)
    
    if as_string:
        # First convert to compact JSON
        json_str = json.dumps(data, separators=(',', ':'), ensure_ascii=True)
        
        # Properly escape for ARM templates:
        # 1. Escape backslashes
        # 2. Escape double quotes
        output_content = json_str.replace('\\', '\\\\').replace('"', '\\"')
        print("Generated ARM-ready JSON string")
    else:
        # Output properly formatted JSON
        output_content = json.dumps(data, indent=2, ensure_ascii=True)
        print("Generated properly formatted JSON")
    
    try:
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(output_content)
            print(f"Output written to {output_file}")
        else:
            print(output_content)
    except OSError as e:
        sys.stderr.write(f"ERROR: Unable to write output file: {e}\n")
        sys.exit(1)

def run_env_check():
    """Print environment / dependency diagnostics and exit with an appropriate code."""
    import platform
    print("Definition Content Creator Environment Check")
    print("-------------------------------------------")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {platform.python_version()}")
    try:  # Attempt PyYAML import
        import yaml  # type: ignore
        try:
            ver = getattr(yaml, '__version__', 'unknown')
        except Exception:  # pragma: no cover
            ver = 'unknown'
        print(f"PyYAML: PRESENT (version {ver})")
        return 0
    except ModuleNotFoundError:
        print("PyYAML: MISSING")
        print("Install with: pip install pyyaml")
        return 2


def main():
    parser = argparse.ArgumentParser(
        description='Convert YAML file to JSON with special handling for workflow files (copies agent name to workflow and removes agent object)')
    parser.add_argument('yaml_file', nargs='?', help='Input YAML file path')
    parser.add_argument('--output', '-o', help='Output file (if not provided, prints to stdout)')
    parser.add_argument('--json', '-j', action='store_true', 
                        help='Output properly formatted JSON instead of ARM-compatible JSON string')
    parser.add_argument('--check', action='store_true', help='Run environment/dependency diagnostics and exit')

    args = parser.parse_args()

    if args.check:
        exit_code = run_env_check()
        # If user only wanted a check, we're done.
        if not args.yaml_file:
            sys.exit(exit_code)
        # Otherwise fall through and also process the file (useful for combined usage)

    if not args.yaml_file:
        parser.error('yaml_file is required unless --check is used alone')

    yaml_to_json(args.yaml_file, args.output, not args.json)

if __name__ == "__main__":
    main()