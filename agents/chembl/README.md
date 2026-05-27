# ChEMBL Tool & Agent Deployment Guide

This guide provides step-by-step instructions for deploying the ChEMBL tool and its associated agent to the Microsoft Discovery platform.

## Overview

ChEMBL provides access to chemical and bioactivity data from the ChEMBL database, supporting drug discovery and chemical biology workflows. This deployment includes:

- **Dockerfile**: Used for creation of the ChEMBL tool container image
- **Tool Definition**: Configuration for the ChEMBL tool
- **Agent Definition**: AI agent configuration for ChEMBL

## Prerequisites

Before starting the deployment, ensure you have:

1. Access to Microsoft Discovery platform
2. Azure Container Registry (ACR) with appropriate permissions
3. Docker installed locally for image building
4. Azure CLI or PowerShell for resource management

## Build Docker Image

1. **Build the image**:

   ```bash
   docker build -t chembl:latest .
   ```

2. **Tag the image** for your Azure Container Registry:

   ```bash
   docker tag chembl:latest mycontainerregistry.azurecr.io/chembl:latest
   ```

   > Replace `mycontainerregistry` with your actual ACR name

3. **Login to Azure Container Registry**:

   ```bash
   az acr login --name mycontainerregistry
   ```

4. **Push the image** to your container registry:

   ```bash
   docker push mycontainerregistry.azurecr.io/chembl:latest
   ```

## File Structure

```text
chembl/
├── Dockerfile                          # Container image definition
├── ChEMBL-tool-definition.yaml         # Tool configuration (YAML)
├── ChEMBL-agent-definition.yaml        # Agent configuration (YAML)
├── chembl_utils.py                     # ChEMBL utility functions
└── README.md                           # This deployment guide
```

## Key Configuration Details

### Agent Capabilities

The ChEMBL agent provides:

- **Compound Search**: Search by name, SMILES, InChI, or ChEMBL ID
- **Target Search**: Find biological targets by name or ID
- **Bioactivity Data**: Retrieve activity measurements and assay data
- **PDB Cross-Reference**: Link ChEMBL data with PDB structures
- **Congeneric Series Analysis**: Identify series of structurally related compounds
- **Flexible File Management**: Saves results with appropriate naming conventions

## API Libraries Included

### Requests

- HTTP library for RESTful API access
- Handles GET/POST requests to ChEMBL endpoints
- JSON response parsing

### Pandas

- Data manipulation and structuring
- Convert API responses to structured dataframes
- Filter and aggregate bioactivity data
- Export to CSV, JSON, and other formats

### RDKit

- Comprehensive cheminformatics toolkit
- Molecular structure manipulation
- Property calculations and descriptors
- SMILES validation and InChI conversion
- **Note**: Visualization features (Draw module) require X11 and are not available in this container

## Important: Search Result Field Names

**CRITICAL**: Search functions return different field names than bioactivity data.

### Search Results Structure

**`search_compounds()`** returns dictionaries with:

- `chembl_id` - Use this field (NOT `molecule_chembl_id`)
- `pref_name` - Preferred compound name
- `max_phase` - Maximum development phase
- `molecule_type` - Type of molecule
- `smiles` - Canonical SMILES (NOTE: field is `smiles`, NOT `canonical_smiles`)
- `molecular_formula` - Molecular formula
- `molecular_weight` - Molecular weight
- `inchi` - Standard InChI
- `inchi_key` - Standard InChI key
- `alogp` - Calculated LogP
- `psa` - Polar surface area
- `num_ro5_violations` - Rule of Five violations

**`search_targets()`** returns dictionaries with:

- `chembl_id` - Use this field (NOT `target_chembl_id`)
- `pref_name` - Preferred target name
- `target_type` - Type of target
- `organism` - Source organism
- `tax_id` - Taxonomy ID
- `target_components` - List of target component details

**IMPORTANT: Bioactivity records do NOT contain SMILES or compound properties.**
To get SMILES for bioactive compounds, you must join via `molecule_chembl_id`:
```python
# Bioactivity dicts contain molecule_chembl_id but NOT smiles
activities, total = utils.get_bioactivities_for_target(target_chembl_id="CHEMBL203", limit=100)
chembl_ids = list({a['molecule_chembl_id'] for a in activities})
compounds = utils.get_compounds_by_chembl_ids(chembl_ids=chembl_ids)
# Or use the convenience method:
enriched = utils.enrich_bioactivities_with_compound_info(activities, max_compounds=100)
```

### Correct Usage Pattern

```python
# CORRECT - accessing search results with keyword arguments:
targets, total = utils.search_targets(query="hemoglobin", limit=1)
target_id = targets[0]['chembl_id']  # Use 'chembl_id'
bioactivities, bio_total = utils.get_bioactivities_for_target(target_chembl_id=target_id, limit=100)

# INCORRECT - will cause TypeError:
targets = utils.search_targets("hemoglobin", limit=1)  # ❌ Missing keyword argument
```

## Usage

### Basic Compound Search

```python
from chembl_utils import ChEMBLUtils
import json
import os

os.makedirs("/output", exist_ok=True)

utils = ChEMBLUtils()

# Search for compounds (note: returns tuple)
compounds, total = utils.search_compounds(query="aspirin", limit=10)

# Save results
with open("/output/final_results.json", "w") as f:
    json.dump({"compounds": compounds, "total_available": total}, f, indent=2)

print(f"Found {len(compounds)} out of {total} total compounds")
```

### Bioactivity Analysis

```python
from chembl_utils import ChEMBLUtils
import json
import os

os.makedirs("/output", exist_ok=True)

utils = ChEMBLUtils()

# Get bioactivity data for a target (returns tuple)
activities, total = utils.get_bioactivities_for_target(target_chembl_id="CHEMBL2095", limit=100)

# Filter for high-affinity compounds (pChEMBL > 7)
high_affinity = [
    a for a in activities 
    if a.get('pchembl_value') and float(a['pchembl_value']) > 7
]

final_results = {
    "total_activities": len(activities),
    "high_affinity_count": len(high_affinity),
    "high_affinity_compounds": high_affinity
}

with open("/output/final_results.json", "w") as f:
    json.dump(final_results, f, indent=2)

print(f"Found {len(high_affinity)} high-affinity compounds")
```

### Cross-Reference with PDB

```python
from chembl_utils import cross_reference_analysis
import json
import os

os.makedirs("/output", exist_ok=True)

# Complete cross-reference workflow
results = cross_reference_analysis("EGFR", output_dir="/output")

print(f"Analysis complete!")
print(f"Targets analyzed: {results['targets_analyzed']}")

# Results automatically saved to final_results.json
```

### Congeneric Series Analysis

```python
from chembl_utils import ChEMBLUtils
import json
import os

os.makedirs("/output", exist_ok=True)

utils = ChEMBLUtils()

# Analyze congeneric series
results = utils.analyze_congeneric_series(target_chembl_id="CHEMBL2095", output_dir="/output")

# Find largest series
largest_series = max(
    results['congeneric_series'], 
    key=lambda x: x['series_size']
)

print(f"Largest congeneric series: {largest_series['series_size']} compounds")
print(f"Total series found: {results['total_congeneric_groups']}")
```

### Working with PDB Files

Extract and use protein/target information from PDB file headers:

```python
from chembl_utils import parse_pdb_files, ChEMBLUtils
import json
import os

os.makedirs("/output", exist_ok=True)

# Parse PDB files to extract protein/target information
pdb_files = parse_pdb_files("/input")

print(f"Found {len(pdb_files)} PDB file(s)")

# Each pdb_info contains: pdb_id, molecule_name, organism, 
# uniprot_ids, ligands, classification, deposition_date, etc.

for pdb_info in pdb_files:
    print(f"\nPDB: {pdb_info['pdb_id']}")
    print(f"  Molecule: {pdb_info['molecule_name']}")
    print(f"  Organism: {pdb_info['organism']}")
    print(f"  UniProt IDs: {pdb_info['uniprot_ids']}")
    print(f"  Ligands: {len(pdb_info['ligands'])}")
    
    # Use extracted information for further analysis
    # (e.g., search ChEMBL for targets, analyze bioactivity data)
```

### Analyzing Bioactivity Data

Use pandas to analyze bioactivity data with proper field checking:

```python
from chembl_utils import ChEMBLUtils
import pandas as pd
import json
import os

os.makedirs("/output", exist_ok=True)

utils = ChEMBLUtils()

# Get bioactivity data for a target (returns tuple)
bioactivities, total = utils.get_bioactivities_for_target(target_chembl_id="CHEMBL1234", limit=1000)

if bioactivities:
    # Convert to DataFrame for analysis
    df = pd.DataFrame(bioactivities)
    
    # IMPORTANT: Always check field existence before using
    summary = {}
    
    if 'molecule_chembl_id' in df.columns:
        summary['unique_compounds'] = df['molecule_chembl_id'].nunique()
    
    if 'standard_type' in df.columns:
        summary['measurement_types'] = df['standard_type'].value_counts().to_dict()
    
    if 'assay_type' in df.columns:
        summary['assay_types'] = df['assay_type'].value_counts().to_dict()
    
    # Perform additional analysis based on available fields
    
    with open("/output/final_results.json", "w") as f:
        json.dump(summary, f, indent=2)
```

### PDB File Structure

The PDB parser extracts:

- **pdb_id**: PDB identifier
- **classification**: Molecule classification (e.g., TRANSFERASE, HYDROLASE)
- **deposition_date**: Structure deposition date
- **title**: Structure title/description
- **molecule_name**: Protein/molecule name from COMPND records
- **organism**: Source organism from SOURCE records
- **ec_number**: EC number if available
- **uniprot_ids**: List of UniProt IDs from DBREF records
- **ligands**: HET records with ligand IDs, chains, and atom counts

## ChEMBL API Endpoints

The ChEMBL REST API provides access to:

- **Molecules**: `/molecule` - Compound data and structures
- **Molecule Search**: `/molecule/search` - Full-text compound search via the `q` parameter
- **Targets**: `/target` - Biological target information
- **Target Search**: `/target/search` - Full-text target search via the `q` parameter
- **Activities**: `/activity` - Bioactivity measurements
- **Assays**: `/assay` - Assay protocols and descriptions
- **Documents**: `/document` - Source publications
- **Cell Lines**: `/cell_line` - Cell line information
- **Tissues**: `/tissue` - Tissue and organ data

## Important Notes

- **No Authentication**: ChEMBL API is publicly accessible, no API key required
- **Rate Limiting**: Be respectful of ChEMBL servers; implement delays for large queries
- **Data Usage**: Respect ChEMBL's terms of service and cite appropriately
- **RDKit**: Available for advanced cheminformatics operations when needed
- **PDB Integration**: Automatic cross-referencing with PDB structures
- **Congeneric Series**: Uses InChI key connectivity layer for structural grouping

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → ChEMBL (LLM) → ChEMBL Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** ChEMBL container for chemical and bioactivity database queries via REST API

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{model}}` | Azure AI Foundry model deployment name | `gpt-4o` |


## Support

For issues or questions, open a GitHub issue:
<https://github.com/microsoft/discovery-catalog/issues>

Microsoft Discovery team contact: discovery-catalog@microsoft.com


## Tools

| Tool | Path | Description |
|---|---|---|
| `chembl` | `tools/ChEMBL/` | ChEMBL is a tool for accessing chemical and bioactivity data from the ChEMBL database, providing a comprehensive interface to search compounds, tar... |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.