# PDBInsights

PDBInsights is an agent and accompanying tool that searches RCSB PDB for structures matching a given protein name or UniProt ID, downloads PDB files, cleans and fixes them, computes quality metrics, and selects the best representative structure.

## Overview

The PDBInsights agent provides a complete workflow for PDBInsightsl bioinformatics:

1. **Search**: Find PDB structures by protein name or UniProt ID
2. **Download**: Fetch PDB files from RCSB
3. **Clean**: Remove waters, heteroatoms, select specific chains
4. **Fix**: Add missing atoms/residues using PDBFixer
5. **Assess**: Extract quality metrics (resolution, R-factors)
6. **Report**: Generate summary and select best structure

## Quick Start

### Example: Analyze hemoglobin structures

```bash
cd samples/tools-and-models/PDBInsights
python example_hemoglobin.py
```

This will:
- Search for hemoglobin structures
- Download and process up to 5 structures
- Generate quality report with best structure recommendation
- Output files to `/output/` directory

### Example: Analyze structures by UniProt ID with quality warnings

```bash
python example_uniprot_table_analysis.py
```

This demonstrates:
- **Correct handling of `oligomeric_details` and other list fields**
- Comprehensive table generation with quality warnings
- Proper extraction of oligomeric state from assembly details

**IMPORTANT**: See this example for the correct way to access `oligomeric_details`, which is a list of strings, not a dictionary.

### Using the Agent Script Directly

```bash
python PDBInsights_agent.py hemoglobin --out /output --max 10
```

## Available Utility Functions

The `PDBInsights_utils.py` module provides these core functions:

### Search and Download
- `search_pdb_by_query(query, size=100)` - Search RCSB PDB by protein name or UniProt ID (multi-strategy search)
- `download_pdb(pdb_id, out_dir="/input")` - Download PDB file

### Structure Preparation
- `clean_structure(input_pdb, output_pdb, ...)` - Remove waters/heteroatoms, select chains
- `fix_structure_with_pdbfixer(pdb_path, out_fixed)` - Fix missing atoms/residues

### Quality Assessment
- `parse_pdb_header_metrics(pdb_path)` - Extract resolution, R-free, R-work (with BioPython)
- `fetch_validation_report(pdb_id)` - Get wwPDB validation metrics (clashscore, Ramachandran)
- `compute_simple_geometry_metrics(pdb_path)` - Count chains and atoms

### Biological Context Analysis
- `get_structure_metrics(pdb_path, pdb_id)` - **NEW**: All metrics + domain info in one call (recommended)
- `analyze_domain_coverage(pdb_path, pdb_id)` - Identify ECD, TMD, cytoplasmic domains
- `analyze_biological_assembly(pdb_path, pdb_id)` - Oligomeric state and assembly info
- `detect_ligands_and_binding(pdb_path, pdb_id)` - Detect bound ligands and partners

### Structure Categorization
- `categorize_structures_by_state(results)` - Group by biological state (unliganded, ligand-bound, TMD, etc.)
- `rank_structures(results, biological_context=True)` - Select best structure with biological relevance

### Analysis and Reporting
- `generate_summary(results, out_json, out_csv)` - Create JSON and CSV summaries

## Result Data Structure

### Understanding List Fields

When working with PDBInsights results, several fields return **lists** rather than single values or dictionaries. This is critical to avoid `AttributeError` when accessing results.

#### List Fields (IMPORTANT):
- **`oligomeric_details`**: List of strings containing assembly detail text
  - Example: `["tetrameric state"]`, `["author_and_software_defined_assembly"]`, `["Dimeric complex with ligand"]`
  - **Correct access**: `entry.get('oligomeric_details', [])`
  - **WRONG**: `entry.get('oligomeric_details', {}).get('state')` ❌
  
- **`assembly_ids`**: List of assembly IDs (e.g., `["1", "2"]`)
- **`assembly_alternates`**: List of alternate assembly IDs
- **`ligand_class`**: List of ligand classifications
- **`binding_partners`**: List of binding partner descriptions

#### Example: Correct Access Pattern

```python
from PDBInsights_utils import search_and_analyze_by_uniprot

summary = search_and_analyze_by_uniprot("P19235", limit=50)

for entry in summary['results']:
    # ✅ CORRECT - oligomeric_details is a list
    oligomeric_details = entry.get('oligomeric_details', [])
    if oligomeric_details:
        detail_text = " ".join(oligomeric_details).lower()
        if "dimer" in detail_text:
            print(f"{entry['pdb_id']} is a dimer")
    
    # ✅ CORRECT - other list fields
    assembly_ids = entry.get('assembly_ids', [])
    ligand_classes = entry.get('ligand_class', [])
```

See `example_uniprot_table_analysis.py` for a complete working example with proper list handling.

## Output Files

All outputs are saved to the `/output` directory:

- `final_results.json` - Complete machine-readable results
- `summary.csv` - Spreadsheet-compatible summary table
- `PDBInsights_report.txt` - Human-readable analysis report
- `{PDB_ID}.pdb` - Downloaded PDB files
- `{PDB_ID}_cleaned.pdb` - Cleaned structures
- `{PDB_ID}_fixed.pdb` - Fixed structures (if PDBFixer available)

## Installation

### Local Development

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

   Note: For PDBFixer and OpenMM, you'll need conda:
   ```bash
   conda install -c conda-forge pdbfixer openmm
   ```

3. Run the example:
   ```bash
   python example_hemoglobin.py
   ```

### Docker Container

**Option 1: Mamba Build (RECOMMENDED - Fast & Reliable)**

Uses Mambaforge base image with mamba (faster conda replacement):

```bash
docker build -f Dockerfile.mamba -t PDBInsights:latest .
```

Build time: ~3-5 minutes. Most reliable for network issues.

**Option 2: Conda Build (Standard)**

Uses Miniconda3 base image with staged installation:

```bash
docker build -t PDBInsights:latest .
```

Build time: ~5-10 minutes. Staged installation for better caching.

**Option 3: Lightweight Build (No PDBFixer - Fastest)**

If you don't need structure fixing, use the lightweight version:

```bash
docker build -f Dockerfile.lite -t PDBInsights:lite .
```

Build time: ~2-3 minutes. The agent will skip the fixing step and continue with cleaned structures.

Run in container:

```bash
# Full version
docker run -v $(pwd)/output:/output PDBInsights:latest python /app/PDBInsights_agent.py hemoglobin

# Lite version
docker run -v $(pwd)/output:/output PDBInsights:lite python /app/PDBInsights_agent.py hemoglobin
```

## Advanced Usage

### Process Multiple Targets

```python
from PDBInsights_utils import search_pdb_by_query, download_pdb, generate_summary

targets = ["hemoglobin", "insulin", "lysozyme"]
all_results = []

for target in targets:
    pdb_ids = search_pdb_by_query(target, size=3)
    for pdb_id in pdb_ids:
        pdb_path = download_pdb(pdb_id, out_dir="/output")
        if pdb_path:
            all_results.append({"target": target, "pdb_id": pdb_id, "path": pdb_path})

generate_summary(all_results, out_json="/output/multi_target_results.json")
```

### Select Specific Chains

```python
from PDBInsights_utils import clean_structure

# Keep only chains A and B, remove all heteroatoms and waters
clean_structure(
    "/output/1A3N.pdb",
    "/output/1A3N_AB_only.pdb",
    remove_hetatm=True,
    remove_waters=True,
    chain_ids=["A", "B"]
)
```

### Quality Assessment Only

```python
import glob
from PDBInsights_utils import parse_pdb_header_metrics, rank_structures

results = []
for pdb_file in glob.glob("/input/*.pdb"):
    metrics = parse_pdb_header_metrics(pdb_file)
    results.append({"file": pdb_file, **metrics})

best = rank_structures(results)
print(f"Best structure: {best['file']} with resolution {best['resolution']} Å")
```

## Quality Metrics Explained

### Resolution (Å)
- Lower is better
- < 2.0 Å: Excellent quality
- 2.0-3.0 Å: Good quality  
- > 3.0 Å: Moderate quality

### R-free / R-work
- Cross-validation metrics
- < 0.25: Excellent
- 0.25-0.30: Good
- > 0.30: Check manually

### Ranking Criteria
Structures are ranked by:
1. Resolution (lower = better)
2. R-free value (lower = better)
3. Atom count (higher = more complete)

## Troubleshooting

### PDBFixer Not Available
If PDBFixer/OpenMM are not installed, the agent will skip the fixing step and use the cleaned structure instead. This is normal and the workflow will continue.

### Histidine (HIS) Residue Errors
**Status:** ✅ FIXED

If you see a warning like:
```
Warning: Could not add hydrogens (HIS residue has the wrong set of atoms). Structure saved without explicit hydrogens.
```

This is **expected behavior** and not an error! The structure is still saved successfully without explicit hydrogen atoms, which is:
- ✅ Standard practice in PDBInsightsl biology
- ✅ Suitable for most analyses (resolution comparison, atom counting, visualization, etc.)
- ✅ Compatible with downstream tools (MD software, docking programs add their own hydrogens)

**Why this happens:** Some PDB files have histidine residues with non-standard protonation states or atom naming that prevents automatic hydrogen addition. The fix gracefully handles this.

**To skip hydrogen addition entirely:**
```python
fix_info = fix_structure_with_pdbfixer(cleaned_path, fixed_path, add_hydrogens=False)
```

See `HISTIDINE_FIX.md` for detailed explanation.

### No Structures Found
- Check protein name spelling
- Try UniProt ID instead (e.g., "P69905" for hemoglobin)
- Reduce the `size` parameter if getting too many results

### Download Failures
- Check internet connectivity
- RCSB may be temporarily unavailable
- Some PDB IDs may be obsolete (replaced by newer entries)

## Notes

- The RCSB search currently uses protein name and UniProt ID queries. For more advanced searches (sequence-based, etc.), you may need to extend the search function.
- Header parsing for metrics is intentionally simple. For production use, consider parsing mmCIF format or using wwPDB validation reports.
- PDBFixer requires OpenMM, which may need additional system dependencies in some environments.

## Agent Integration

This tool is designed to work as part of the Microsoft Discovery platform. The agent definition (`PDBInsights-agent-definition.yaml`) provides comprehensive instructions for the LLM to generate appropriate analysis scripts using the utility functions.

Key agent features:
- Single-script workflow (no multiple file generation)
- Automatic error handling and graceful degradation
- Comprehensive reporting with quality assessment
- Follows platform conventions (final_results.json output)

## Support

For issues or questions:
- Check the `PDBInsights_utils.py` source for function documentation
- Review `example_hemoglobin.py` for usage patterns
- See agent definition YAML for complete API reference

## Example Prompts

Use these prompts when interacting with the PDBInsights agent. They cover quick queries, full workflows, and advanced analyses.

- Short / quick question
    - "List high-quality PDB structures for human EPOR (UniProt P19235) with resolution < 3.0 Å and R-free < 0.25. Provide PDB IDs, resolution, R-free, and biological context."

- Complete workflow (download + prepare)
    - "Search RCSB for structures matching UniProt P19235, download up to 200 entries, clean them (remove waters/heteroatoms), protonate for MD readiness, rank by quality, and save results to /output. Return a JSON summary containing counts per biological context and the best structure details."

- Exploratory analysis with context
    - "Analyze all structures for UniProt P19235 and produce a table showing: PDB ID, resolution, R-free, primary domain (ECD/TMD/ICD), has_ligand, oligomeric state, and quality score. Flag any structures with clashscore > 30 or Ramachandran outliers > 1%."

- Targeted comparison
    - "Compare PDB entries 1ERN, 1EER, and 1EBP for their domain coverage, validation metrics, and ligand-binding partners. Which of these is best suited for MD simulation?"

- Advanced / reproducible prompt (preferred for pipelines)
    - "Run search_and_analyze_by_uniprot('P19235', limit=200, outdir='/output', download=True, clean=True, protonate=True). Save JSON and CSV summaries and include a short report describing which biological contexts are most represented and why the selected 'best_overall' was chosen."

- Debug / environment-aware prompt
    - "Perform the full analysis for UniProt P19235 but skip protonation if PDBFixer is unavailable. If protonation is skipped, list which files would be protonated and include a warning in the summary."
