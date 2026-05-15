# Hazardous Groups Tool

A specialized tool for identifying hazardous and safety-related functional groups in molecular structures.

## Overview

The Hazardous Groups Tool screens molecules for explosive groups, chemical weapon precursors, PFAS compounds, reactive groups, and other safety concerns. It provides comprehensive safety assessment capabilities for chemical compounds.

## Features

- **Comprehensive Screening**: Identifies multiple categories of hazardous functional groups
- **Regulatory Compliance**: Screens for Chemical Weapon Convention (CWC) scheduled compounds
- **Environmental Concerns**: Detects PFAS (per- and polyfluoroalkyl substances)
- **Safety Alerts**: Identifies explosive, self-reactive, and unstable groups
- **Batch Processing**: Processes multiple molecules and files efficiently
- **Risk Assessment**: Categorizes molecules by risk level (safe, low, medium, high)

## Hazard Categories

The tool screens for the following hazard categories:

- **us_pfas_groups**: US PFAS functional groups
- **cwc_groups**: Chemical Weapon Convention scheduled compounds
- **explosive_groups**: Explosive functional groups (azides, nitro, peroxides, etc.)
- **self_reactive_groups**: Self-reactive and unstable groups
- **autorxn_reactive_groups**: Auto-reactive chemical groups
- **pnnl_hazardous_groups**: PNNL hazard classification groups
- **pnnl_air_water_sensitive_groups**: Air and water sensitive compounds
- **pnnl_flourinated_reactive_groups**: Fluorinated reactive groups
- **pnnl_fg_dependent_reactive_groups**: Functional-group dependent reactive patterns
- **richman_reactive_groups**: Richman reactive group patterns
- **cf3_pfas_groups**: CF3-containing PFAS compounds
- **cf2_pfas_groups**: CF2-containing PFAS compounds
- **triple_bond_groups**: Triple bond containing groups

## Actions

### identify_hazardous_groups

Comprehensive safety screening across all hazard categories.

**Parameters:**
- `input_directory` (required): Directory containing molecular data files
- `output_directory` (required): Directory for output results
- `column_name` (optional): Column name for SMILES in CSV files
- `batch_size` (optional): Number of molecules per batch (default: 100)
- `file_pattern` (optional): Glob pattern to filter files (default: *.*)
- `categories` (optional): Comma-separated list of specific categories or "all" (default: all)

### check_category

Focused screening for a specific hazard category.

**Parameters:**
- `input_directory` (required): Directory containing molecular data files
- `output_directory` (required): Directory for output results
- `category` (required): Specific category to check
- `column_name` (optional): Column name for SMILES in CSV files
- `batch_size` (optional): Number of molecules per batch (default: 100)
- `file_pattern` (optional): Glob pattern to filter files (default: *.*)

## Usage Examples

### Using Tool Actions

```python
# Comprehensive screening
result = tool.identify_hazardous_groups(
    input_directory="/input",
    output_directory="/output",
    categories="all"
)

# Check specific category
result = tool.check_category(
    input_directory="/input",
    output_directory="/output",
    category="explosive_groups"
)
```

### Using Code Environment

```python
import sys
sys.path.append('/app')

from mol_hazardous_groups import identify_hazardous_groups
from io_utils import find_smiles_files, read_smiles_from_file

# Screen molecules
input_files = find_smiles_files('/input')
for file_path in input_files:
    smiles_list = read_smiles_from_file(file_path)
    for smiles in smiles_list:
        hazards = identify_hazardous_groups(smiles)
        print(f"{smiles}: {len(hazards)} hazards found")
```

## Output Format

The tool generates structured JSON output with safety assessment results:

```json
{
  "status": "completed",
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
  }
}
```

## Building the Container

```bash
docker build -t hazardous-groups-tool:latest .
```

## Running the Container

```bash
docker run -v $(pwd)/input:/input -v $(pwd)/output:/output \
  hazardous-groups-tool:latest \
  --action identify_hazardous_groups \
  --input /input \
  --output /output \
  --categories all
```

## Safety Considerations

- This tool is designed for safety screening and risk assessment
- Results should be reviewed by qualified safety professionals
- Regulatory compliance may require additional screening beyond this tool
- Handle identified hazardous compounds with appropriate safety precautions

## License

MIT License
