# ChEMBL Agent - Quick Reference

## API Functions

### Compound Operations
```python
from chembl_utils import ChEMBLUtils

utils = ChEMBLUtils()

# Search compounds (returns tuple)
compounds, total = utils.search_compounds(query="aspirin", limit=10)

# Get compound details
compound = utils.get_compound_by_chembl_id(chembl_id="CHEMBL25")

# Get bioactivities for compound (returns tuple)
activities, total = utils.get_bioactivities_for_compound(molecule_chembl_id="CHEMBL25", limit=100)
```

### Target Operations
```python
# Search targets (returns tuple)
targets, total = utils.search_targets(query="kinase", limit=20)

# Get target details
target = utils.get_target_by_chembl_id(chembl_id="CHEMBL2095")

# Get bioactivities for target (returns tuple)
activities, total = utils.get_bioactivities_for_target(target_chembl_id="CHEMBL203", limit=100)
```

### Advanced Analysis
```python
# Cross-reference with PDB
result = utils.cross_reference_with_pdb(target_name="EGFR")

# Analyze congeneric series
results = utils.analyze_congeneric_series(target_chembl_id="CHEMBL2095", output_dir="/output")

# Complete workflow
result = utils.cross_reference_ligands_with_pdb(target_name="EGFR", output_dir="/output")
```

### Convenience Functions (for ad-hoc testing only)
```python
# NOTE: Agent scripts should always use the ChEMBLUtils class pattern above.
# These convenience functions are for quick ad-hoc testing only.
from chembl_utils import search_compounds, search_targets, cross_reference_analysis

# Quick searches (return tuples)
compounds, total = search_compounds(query="imatinib", limit=10)
targets, total = search_targets(query="EGFR", limit=5)

# Complete analysis (one-liner)
results = cross_reference_analysis(target_name="EGFR", output_dir="/output")
```

## Common Queries

### Find Compounds
```python
# By name (returns tuple)
compounds, total = utils.search_compounds(query="aspirin")

# By ChEMBL ID
compound = utils.get_compound_by_chembl_id(chembl_id="CHEMBL25")
```

### Find Targets
```python
# By name (returns tuple)
targets, total = utils.search_targets(query="kinase")

# By ChEMBL ID
target = utils.get_target_by_chembl_id(chembl_id="CHEMBL203")
```

### Get Bioactivity Data
```python
# For a target (returns tuple)
activities, total = utils.get_bioactivities_for_target(target_chembl_id="CHEMBL203")

# For a compound (returns tuple)
activities, total = utils.get_bioactivities_for_compound(molecule_chembl_id="CHEMBL941")

# Filter high-affinity
high_affinity = [a for a in activities 
                 if a.get('pchembl_value') and float(a['pchembl_value']) > 8]
```

### Cross-Reference Analysis
```python
# Complete workflow
results = utils.cross_reference_ligands_with_pdb(target_name="EGFR", output_dir="/output")

# Check results
if results['status'] == 'completed':
    for target_result in results['results']:
        print(f"Target: {target_result['target']['pref_name']}")
        print(f"PDB structures: {len(target_result['pdb_references'])}")
        print(f"Ligands: {target_result['ligand_analysis']['total_ligands']}")
        print(f"Series: {target_result['ligand_analysis']['total_congeneric_groups']}")
```

## Output Format

All results saved as JSON to `/output/final_results.json`:

```json
{
  "status": "completed",
  "target_name": "EGFR",
  "analysis_date": "2025-10-15",
  "targets_analyzed": 5,
  "results": [
    {
      "target": {
        "chembl_id": "CHEMBL203",
        "pref_name": "Epidermal growth factor receptor",
        "organism": "Homo sapiens"
      },
      "pdb_references": [
        {"pdb_id": "1M17", "pdb_url": "..."}
      ],
      "ligand_analysis": {
        "total_ligands": 120,
        "total_congeneric_groups": 5,
        "congeneric_series": [...]
      }
    }
  ]
}
```

## ChEMBL ID Formats

- **Compounds**: CHEMBL25, CHEMBL941, etc.
- **Targets**: CHEMBL203, CHEMBL2095, etc.
- **Assays**: CHEMBL######

## Common Activity Types

- **IC50**: Half-maximal inhibitory concentration
- **Ki**: Inhibition constant
- **EC50**: Half-maximal effective concentration
- **Kd**: Dissociation constant
- **pChEMBL**: Negative log of activity value (standardized)

## Error Handling

```python
try:
    compounds, total = utils.search_compounds(query="aspirin")
    if not compounds:
        print("No compounds found")
except Exception as e:
    print(f"Error: {str(e)}")
```

## Testing

```bash
# Run all tests
docker run --rm -v $(pwd):/test chembl:latest python /test/test_chembl.py

# Run examples
docker run --rm -v $(pwd):/test chembl:latest python /test/example_comprehensive.py
```

## Deployment Commands

```bash
# Build image
docker build -t chembl:latest .

# Tag for ACR
docker tag chembl:latest myregistry.azurecr.io/chembl:latest

# Push to ACR
az acr login --name myregistry
docker push myregistry.azurecr.io/chembl:latest

# Convert definitions
python3 ../../utils/definition-content-creator.py ChEMBL-tool-definition.yaml --output ChEMBL-tool-definition.json --json
python3 ../../utils/definition-content-creator.py ChEMBL-agent-definition.yaml --output ChEMBL-agent-definition.json --json
```

## Sample Investigation Prompts

Once deployed, use these prompts:

1. **Compound Search**:
   - "Search for compounds similar to imatinib"
   - "Get properties for CHEMBL941"

2. **Target Analysis**:
   - "Find all kinase targets"
   - "Get details for EGFR target"

3. **Bioactivity**:
   - "Get bioactivity data for EGFR inhibitors"
   - "Find high-affinity compounds for ABL1"

4. **Cross-Reference** (Main Use Case):
   - "Cross reference the CHEMBL ligand data with the PDB structures of EGFR to identify for which congeneric series the binding mode is minimally ambiguous"

5. **Multi-Target**:
   - "Get the target profile for imatinib"
   - "Analyze selectivity of compound CHEMBL941"
