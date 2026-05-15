# Writing Action Scripts

Action scripts are predefined actions that enable the tool publisher to deliver consistent, deterministic behavior, especially for proprietary tools or when strict reproducibility is required. As outlined in [a--identify-action-scenarios.md](../1-identify-scenarios/a--identify-action-scenarios.md), the process begins by identifying the required action, then implementing the corresponding scripts, and finally integrating them into the Docker image.

This section uses the `molecularGroups` tool as a reference implementation. The `molecularGroups` tool demonstrates action-based tool patterns for molecular analysis, providing predefined actions for functional group identification and hazardous group screening. It covers key elements like input format flexibility, batch processing, and structured output generation.

## molecularGroups Tool

The reference implementation for this tool can be found in the following directory:
[6-solutions/tools-and-models/molecularGroups/](../../../6-solutions/tools-and-models/molecularGroups/)

This directory contains all the necessary files and scripts for the `molecularGroups` tool, including the Dockerfile, tool definition, and core implementation scripts.

```text
6-solutions/tools-and-models/molecularGroups/
    ├── Dockerfile                           # Container definition
    ├── README.md                            # Documentation
    ├── molecularGroups-tool-definition.yaml # Tool configuration
    ├── input/                               # Sample input data files
    │   └── molecules.smi                    # SMILES format input
    ├── output/                              # Directory for results output
    └── app/                                 # Core implementation scripts
        ├── entrypoint.py                    # Main entry point for all actions
        ├── io_utils.py                      # Utilities for I/O operations and logging
        ├── mol_functional_groups.py         # Functional group identification logic
        └── mol_hazardous_groups.py          # Hazardous group screening logic
```

### Directory Structure Explained

The directory structure represents a template for action-based containerized tool development. The core components are the entrypoint script, action implementation modules, Dockerfile, and tool definition file.

In this example:

- The **app/** folder contains the core Python modules that implement the tool's functionality
- The **input/** folder contains sample input files for testing purposes
- The **output/** folder is where results and log files are generated

When deploying this tool on the Microsoft Discovery platform, these folders represent mount points to the Docker container:

- Input directories are mounted to provide data to the tool
- Output directories are mounted to collect results from the tool

This approach allows for consistent tool execution while maintaining a clear interface for the Discovery platform.

## Understanding Action-Based Tools

Action-based tools expose predefined operations through a command-line interface. Unlike code environment tools that allow arbitrary code execution, action-based tools provide specific, well-defined operations that agents can invoke.

### Key Components

1. **Entrypoint Script**: The main script that parses arguments and dispatches to the appropriate action
2. **Action Modules**: Python modules containing the logic for each action
3. **Tool Definition**: YAML file that defines available actions and their parameters
4. **I/O Utilities**: Helper functions for reading input files and writing results

## Input Formats

The tool supports several input file formats. Sample input files are provided in the `6-solutions/tools-and-models/molecularGroups/input/` directory:

### 1. SMILES File (`input/molecules.smi`)

A simple text file with one SMILES string per line:

```text
# File: 6-solutions/tools-and-models/molecularGroups/input/molecules.smi
CCO
CC(=O)O
c1ccccc1
CN1C=NC2=C1C(=O)N(C(=O)N2C)C
```

### 2. CSV File

A comma-separated file with headers:

```csv
smiles,name,property
CCO,ethanol,solvent
CC(=O)O,acetic acid,acid
c1ccccc1,benzene,aromatic
CN1C=NC2=C1C(=O)N(C(=O)N2C)C,caffeine,stimulant
```

### 3. JSON File

A JSON file with molecules:

```json
[
    {"smiles": "CCO", "name": "ethanol"},
    {"smiles": "CC(=O)O", "name": "acetic acid"},
    {"smiles": "c1ccccc1", "name": "benzene"},
    {"smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "name": "caffeine"}
]
```

## Running the Tool

The tool operates in action mode, where you specify the action name and required parameters. The entrypoint script handles argument parsing and dispatches to the appropriate action function.

### Available Actions

The `molecularGroups` tool provides two main actions:

1. **identify_functional_groups**: Identifies common functional groups in molecules (carbonyls, amines, alcohols, ethers, halides, etc.)
2. **identify_hazardous_groups**: Screens molecules for hazardous groups (explosives, PFAS, CWC compounds, reactive groups, etc.)

### Running Actions Locally

You can run the tool locally using Python or Docker:

#### Using Python Directly

```bash
# Navigate to the molecularGroups directory
cd 6-solutions/tools-and-models/molecularGroups

# Run functional group identification
python app/entrypoint.py --action identify_functional_groups \
  --input input/ \
  --output output/

# Run hazardous group screening
python app/entrypoint.py --action identify_hazardous_groups \
  --input input/ \
  --output output/ \
  --categories all
```

#### Using Docker

First, build the container image:

```bash
cd 6-solutions/tools-and-models/molecularGroups
docker build -t molecular-groups-tool:latest .
```

Then run the actions:

```bash
# Run functional group identification
docker run --rm \
  -v "$(pwd)/input:/input" \
  -v "$(pwd)/output:/output" \
  molecular-groups-tool:latest \
  python3 /app/entrypoint.py --action identify_functional_groups \
  --input /input --output /output

# Run hazardous group screening with specific categories
docker run --rm \
  -v "$(pwd)/input:/input" \
  -v "$(pwd)/output:/output" \
  molecular-groups-tool:latest \
  python3 /app/entrypoint.py --action identify_hazardous_groups \
  --input /input --output /output \
  --categories "explosive_groups,cwc_groups"
```

### Action Parameters

#### identify_functional_groups

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--input` | Yes | Path to input directory or file |
| `--output` | Yes | Path to output directory |
| `--column-name` | No | Column name for SMILES in CSV files |
| `--batch-size` | No | Number of molecules per batch (default: 100) |
| `--file-pattern` | No | Glob pattern to filter files (default: *.*) |

#### identify_hazardous_groups

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--input` | Yes | Path to input directory or file |
| `--output` | Yes | Path to output directory |
| `--column-name` | No | Column name for SMILES in CSV files |
| `--batch-size` | No | Number of molecules per batch (default: 100) |
| `--file-pattern` | No | Glob pattern to filter files (default: *.*) |
| `--categories` | No | Comma-separated list of hazard categories or "all" (default: all) |

Available hazard categories:
- `us_pfas_groups`: US PFAS functional groups
- `cwc_groups`: Chemical Weapon Convention scheduled compounds
- `explosive_groups`: Explosive functional groups (azides, nitro, peroxides, etc.)
- `self_reactive_groups`: Self-reactive and unstable groups
- `autorxn_reactive_groups`: Auto-reactive chemical groups
- `pnnl_hazardous_groups`: PNNL hazard classification groups
- `pnnl_air_water_sensitive_groups`: Air and water sensitive compounds
- `pnnl_flourinated_reactive_groups`: Fluorinated reactive groups
- `cf3_pfas_groups`: CF3-containing PFAS compounds
- `cf2_pfas_groups`: CF2-containing PFAS compounds
- `triple_bond_groups`: Triple bond containing groups

## Results Format

All actions output results to a `results.json` file in the output directory, along with detailed CSV files.

### Functional Groups Output

```json
{
  "action": "identify_functional_groups",
  "timestamp": "2024-01-15 14:30:00",
  "parameters": {
    "files_processed": 1
  },
  "summary": {
    "total_molecules": 4,
    "total_groups_found": 12,
    "group_distribution": {
      "alcohol": 2,
      "carbonyl": 1,
      "aromatic": 2
    },
    "category_distribution": {
      "oxygen-containing": 3,
      "carbon": 2
    }
  },
  "output_files": {
    "detailed_analysis": "/output/functional_groups_detailed.csv"
  },
  "status": "completed"
}
```

### Hazardous Groups Output

```json
{
  "action": "identify_hazardous_groups",
  "timestamp": "2024-01-15 14:35:00",
  "parameters": {
    "categories": ["all"],
    "files_processed": 1
  },
  "summary": {
    "total_molecules": 150,
    "molecules_with_hazards": 23,
    "hazard_distribution": {
      "explosive_groups": 12,
      "cwc_groups": 3
    },
    "risk_distribution": {
      "safe": 127,
      "low": 15,
      "medium": 6,
      "high": 2
    }
  },
  "output_files": {
    "detailed_assessment": "/output/hazard_assessment_detailed.csv",
    "high_risk_molecules": "/output/high_risk_molecules.csv"
  },
  "status": "completed"
}
```

## Implementing Action Scripts

When creating your own action-based tool, follow these patterns from the `molecularGroups` implementation:

### 1. Entrypoint Script Structure

The entrypoint script should:
- Parse command-line arguments
- Validate required parameters
- Dispatch to the appropriate action function
- Return appropriate exit codes

```python
#!/usr/bin/env python3
"""Entrypoint script for action-based tool."""

import argparse
import sys

# Define available actions
AVAILABLE_ACTIONS = {
    'action_name': {
        'description': 'Description of what this action does'
    }
}

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Tool Description")
    parser.add_argument('--action', choices=AVAILABLE_ACTIONS.keys(),
                       required=True, help='Action to perform')
    parser.add_argument('--input', required=True,
                       help='Path to input directory or file')
    parser.add_argument('--output', required=True,
                       help='Path to output directory')
    # Add action-specific parameters
    return parser.parse_args()

def main():
    """Main entry point."""
    args = parse_arguments()

    # Dispatch to appropriate action
    if args.action == 'action_name':
        success = run_action_name(args.input, args.output, vars(args))

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
```

### 2. Action Function Pattern

Each action function should:
- Set up logging
- Validate and process input files
- Execute the core logic
- Write structured output
- Handle errors gracefully

```python
def run_action_name(input_path: str, output_path: str, params: dict) -> bool:
    """
    Run the action.

    Args:
        input_path: Path to input directory or file
        output_path: Path to output directory
        params: Additional parameters

    Returns:
        bool: True if successful
    """
    try:
        # 1. Set up logging
        io_utils.setup_session_logger('action_name', output_path)

        # 2. Find and validate input files
        input_files = find_input_files(input_path, params)

        # 3. Process files
        results = []
        for file_path in input_files:
            file_results = process_file(file_path, params)
            results.extend(file_results)

        # 4. Write output
        write_results(output_path, results)

        return True

    except Exception as e:
        io_utils.log_error("Error in action", e)
        return False
```

### 3. Tool Definition Integration

Define your actions in the tool definition YAML file with proper schemas:

```yaml
actions:
  - name: action_name
    description: Description of the action for agents to understand
    infra_node: worker
    input_schema:
      type: object
      properties:
        input_directory:
          type: string
          description: "Directory containing input files"
        output_directory:
          type: string
          description: "Directory for output results"
      required:
        - input_directory
        - output_directory
    command: "python3 /app/entrypoint.py --action action_name --input {{input_directory}} --output {{output_directory}}"
```

## Conclusion

This tool provides a template for action-based molecular analysis tools. The key principles demonstrated are:

1. **Clear action definitions**: Each action has well-defined inputs and outputs
2. **Structured output**: Results are written in consistent JSON format
3. **Batch processing**: Automatically handles directories with multiple files
4. **Error handling**: Graceful handling of invalid inputs and processing errors
5. **Logging**: Comprehensive logging for debugging and auditing

For more advanced use cases requiring custom code execution, see the [molToolkit tool](../../../6-solutions/tools-and-models/molToolkit/) which demonstrates code environment patterns.
