# BindingDB Agent

An AI agent for retrieving and analyzing detailed protein-ligand binding data from BindingDB using a local SQLite database with comprehensive data (640 fields per measurement).

## Quick Start

### Building the Docker Image

**Prerequisites**: You must build the SQLite database first (one-time setup):

```bash
# 1. Download the latest BindingDB snapshot into the current folder
#    This script saves the ZIP as `BindingDB_All.zip` by default.
python get_latest_bindingdb.py

# 2. Download and build the database (~25-30 minutes, one-time)
#    Default: 1024-byte pages for ~30% space savings (8-9 GB vs 12-13 GB)
python3 tsv_to_sqlite.py --input BindingDB_All.zip --output bindingdb.db

# 3. Build the Docker image (~2-3 minutes)
docker build -t bindingdb-agent:latest .

# 4. Test the image
docker run --rm bindingdb-agent:latest \
    python3 -c "from bindingdb_utils import BindingDBUtils; \
                db = BindingDBUtils(sqlite_db_path='/app/bindingdb.db'); \
                print(db.get_sqlite_database_stats())"
```

**Note**: The database uses 1024-byte pages by default, providing ~30% space savings compared to the SQLite default (4096 bytes). This is optimal for BindingDB's sparse data structure (640 columns, many NULL values). To use a different page size, add `--page-size 4096` to the conversion command.

### Quick testing with sampling

If you want to build a small sample of the database for quick development or CI tests, use the `--sample-rate` flag. For example, to import roughly 20% of the rows:

```bash
python3 tsv_to_sqlite.py --output bindingdb_sample.db --sample-rate 0.2
```

Add `--sample-seed <int>` to make the sampling deterministic across runs.

### Monthly Database Updates

We provide a small helper script that automatically finds the latest BindingDB snapshot and downloads the ZIP directly into the current directory as `BindingDB_All.zip` (convenient for CI and Docker builds).

Examples:

- Download the latest snapshot into the current directory (default):

```bash
python get_latest_bindingdb.py
```

- Download to a specific directory:

```bash
python get_latest_bindingdb.py --download ./data/
```

- Download to a specific filename:

```bash
python get_latest_bindingdb.py --download ./snapshots/BindingDB_All_202511_tsv.zip
```

- Rebuild the database from the downloaded file (explicit URL also accepted):

```bash
# Using the local file you just downloaded
python tsv_to_sqlite.py --input BindingDB_All.zip --output bindingdb.db

# Or point tsv_to_sqlite.py at a direct URL
python tsv_to_sqlite.py --url https://www.bindingdb.org/rwd/bind/downloads/BindingDB_All_202511_tsv.zip --output bindingdb.db --force-download
```

The helper script prefers to download the real ZIP file (not an HTML wrapper), and
it verifies the direct ZIP URL when possible. Use `--no-verify` to skip HEAD checks
if required by your environment.

## Overview

BindingDB specializes in high-quality protein-ligand binding measurements, with a focus on:
- **Binding constants**: Kd, Ki, IC50, EC50
- **Kinetic parameters**: kon, koff (association and dissociation rates)
- **Protein-ligand interaction data**: UniProt-centric target identification
- **Biophysical measurements**: Comprehensive binding affinity data with experimental conditions
- **Complete metadata**: 640 fields including experimental conditions, PDB structures, and cross-references

**Database Statistics**:
- **640 fields** per measurement
- **<1ms queries** with proper indexing
- **3M+ binding measurements**
- **Complete experimental context** (pH, temperature, kinetics)

## BindingDB vs ChEMBL: When to Use Which?

| **Feature**                | **BindingDB**                                                | **ChEMBL**                                                   |
| -------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **Primary Focus**          | Binding affinity measurements                                | Bioactivity and pharmacological data                         |
| **Core Measurements**      | Kd, Ki, IC50, EC50                                           | IC50, EC50, potency, ADMET                                   |
| **Data Quality**           | High-quality binding constants                               | Large-scale screening data from diverse sources              |
| **Clinical Information**   | ❌ Limited                                                    | ✅ Extensive (max_phase, development status)                 |
| **Compound Properties**    | ❌ Minimal (focus on binding)                                | ✅ Extensive (MW, LogP, PSA, etc.)                           |
| **Target Information**     | UniProt-centric                                              | ChEMBL-centric with extensive annotations                    |
| **Kinetic Parameters**     | ✅ kon, koff available                                       | ❌ Limited                                                   |
| **Experimental Conditions**| ✅ pH, temperature, assay details                            | ⚠️ Limited                                                   |
| **Best For**               | Detailed binding studies, lead optimization, kinetic analysis| SAR analysis, drug discovery pipelines, approved drug search |
| **Typical Use Cases**      | "What's the Kd?", "Compare binding affinities"               | "What compounds are approved?", "What's the SAR trend?"      |

### Decision Guide

**Use BindingDB when you need:**
- Precise binding constants (Kd, Ki) for affinity measurements
- Kinetic parameters (kon, koff) for mechanism studies
- Experimental conditions (pH, temperature) for reproducibility
- To compare binding affinities for lead optimization
- UniProt-centric target identification
- PDB structure IDs for structure-based design

**Use ChEMBL when you need:**
- Broad bioactivity screening data across many targets
- Clinical development phase information
- Compound properties (molecular weight, LogP, etc.)
- Large-scale SAR analysis
- Approved drugs or compounds in clinical trials

**Use Both for comprehensive analysis:**
- BindingDB: Get precise Kd/Ki binding affinity data with experimental context
- ChEMBL: Get compound properties and clinical information
- Cross-reference by InChI key or SMILES

## Agent Capabilities

### Core SQLite Functions

1. **Binding Data Retrieval**: Get detailed binding measurements by UniProt ID (`get_binding_data_by_uniprot_sqlite`)
   - Returns all 640 fields including Kd, Ki, IC50, EC50 measurements
   - Includes 3-field affinity structure (numeric value, raw string, qualifier)

2. **Compound Search**: Find binding data by compound name (`search_by_compound_sqlite`)
   - Search by ligand name or compound identifier
   - Returns all associated binding measurements

3. **SMILES-Based Search**: Find exact SMILES matches (`search_ligands_by_smiles_sqlite`)
   - Exact SMILES string matching (not similarity search)
   - Returns all targets binding the specific compound

4. **Kinetic Data Retrieval**: Get kinetic parameters by UniProt ID (`get_kinetic_data_sqlite`)
   - Returns kon (association rate), koff (dissociation rate)
   - Includes half-life and other kinetic measurements

5. **Database Statistics**: Get database info (`get_sqlite_database_stats`)
   - Returns total measurements, fields available, database size
   - Useful for understanding data coverage

### Key Features

- **Local SQLite Database**: 3M+ measurements with 640 fields per record, <1ms query performance
- **3-Field Affinity Structure**: Handles inequality qualifiers (<, >) in measurements
  - Numeric value (for calculations)
  - Raw string (original with symbols)
  - Qualifier (machine-readable: exact, less_than, greater_than)
- **Comprehensive Data**: Kinetic parameters, experimental conditions, PDB structures
- **Automatic type conversion**: All numeric fields properly typed for analysis
- **Safe JSON serialization**: Built-in NaN handling for DataFrame exports
- **UniProt-centric**: Uses UniProt IDs for target identification

## Example Prompts for the Agent

Here are example prompts you can use when working with the BindingDB agent.

### Basic Binding Affinity Queries

- "Find all ligands with Ki < 100 nM for UniProt ID P00749 (Urokinase)"
- "Show me binding data for P08246 (Neutrophil elastase)"
- "Get binding data for P00734 (Thrombin) with limit 50 records"
- "What is the binding affinity (Ki) of WX-UK1 to P00749?"
- "Show me kinetic data (kon/koff) for P00734"
- "What are the experimental conditions for binding measurements on EGFR?"

### Compound and Structure Queries

**Search by Compound Name:**
- "Find binding data for ibuprofen"
- "Show me all measurements for erlotinib"
- "What targets does aspirin bind to?"

**Exact SMILES Match (finds all targets for specific compound):**
- "Find all protein targets that bind to this exact SMILES: CC(C)CC1=CC=C(C=C1)C(C)C(=O)O"
- "What targets bind to ibuprofen? Use SMILES: CC(C)Cc1ccc(cc1)C(C)C(=O)O"
- "Get all binding measurements for this specific SMILES structure"

### Database Statistics and Exploration

- "What are the BindingDB database statistics?"
- "How many total measurements are in the database?"
- "What fields are available in BindingDB?"
- "Which proteins have binding data for this compound in the database?"

### Lead Optimization and SAR

- "Rank analogs by their Ki values for P00176, limit to top 20"
- "What's the affinity range for compounds binding to P08246?"
- "Identify the tightest binding compounds for P00734 with Ki < 10 nM"
- "Show me the best and worst Ki values for P00176"
- "Find all compounds with Kd < 50 nM for P00734"
- "What are the kinetic parameters (kon/koff) for top binders to P00734?"

### Cross-Database Enrichment

- "Get BindingDB Ki data for compounds from my ChEMBL search"
- "For these ChEMBL compounds with good IC50, what are their Ki values in BindingDB?"
- "Find which targets bind these PubChem compounds"
- "Cross-reference these PubChem compounds with BindingDB affinity data"

### Data Export and Analysis

- "Export all P00176 binding data to JSON with proper NaN handling"
- "Save the top 50 compounds by Ki for P00734"
- "Create a dataset of Ki values filtered for high-quality measurements from P08246"
- "Generate a summary table of binding affinities ranked by strength"

### Best Practice Queries (Combining Multiple Aspects)

- "Find tight binders (Ki < 50 nM) to P00176, rank by affinity, limit to top 20, and export with experimental conditions"
- "Get high-quality Ki measurements for P00734 inhibitors and identify top 10 candidates"
- "Show me binding data with PDB structures for P00734"
- "Get experimental conditions and kinetic data for top 5 binders to P00176"

## Usage Examples

### Example 1: Basic Binding Affinity Query

```python
from bindingdb_utils import BindingDBUtils

utils = BindingDBUtils(sqlite_db_path='/app/bindingdb.db')

# Get binding data for a protein target
data = utils.get_binding_data_by_uniprot_sqlite('P00734', limit=100)  # Thrombin

# Filter for tight binders
tight_binders = [row for row in data if row.get('Ki (nM)') and row['Ki (nM)'] < 50]
print(f"Found {len(tight_binders)} compounds with Ki < 50 nM")
```

### Example 2: Search by Compound Name

```python
from bindingdb_utils import BindingDBUtils

utils = BindingDBUtils(sqlite_db_path='/app/bindingdb.db')

# Search by compound name
data = utils.search_by_compound_sqlite('ibuprofen', limit=50)

# Display results
for row in data:
    print(f"Target: {row.get('Target Name')} (UniProt: {row.get('UniProt (SwissProt) Primary ID of Target Chain')})")
    print(f"  Ki: {row.get('Ki (nM)')} nM")
```

### Example 3: Exact SMILES Match

```python
from bindingdb_utils import BindingDBUtils

utils = BindingDBUtils(sqlite_db_path='/app/bindingdb.db')

# Find all targets that bind this specific compound
smiles = 'CC(C)Cc1ccc(cc1)C(C)C(=O)O'  # Ibuprofen
targets = utils.search_ligands_by_smiles_sqlite(smiles, limit=100)

# Display results
for target in targets:
    print(f"Target: {target.get('Target Name')} (UniProt: {target.get('UniProt (SwissProt) Primary ID of Target Chain')})")
    print(f"  Ki: {target.get('Ki (nM)')} nM")
    print(f"  Kd: {target.get('Kd (nM)')} nM")
```

### Example 4: Get Kinetic Parameters

```python
from bindingdb_utils import BindingDBUtils

utils = BindingDBUtils(sqlite_db_path='/app/bindingdb.db')

# Get kinetic data (kon, koff rates)
kinetic_data = utils.get_kinetic_data_sqlite('P00734', limit=50)  # Thrombin

# Display results
for row in kinetic_data:
    if row.get('kon (M-1s-1)') and row.get('koff (s-1)'):
        print(f"Ligand: {row.get('Ligand SMILES')}")
        print(f"  kon: {row.get('kon (M-1s-1)')} M⁻¹s⁻¹")
        print(f"  koff: {row.get('koff (s-1)')} s⁻¹")
```

## Data Fields Reference

### Affinity Measurement Fields (3-Field Structure)

For each affinity measurement (Kd, Ki, IC50, EC50), **three fields** are provided:

1. **`[Measurement] (nM)`** - Numeric value for calculations (float or None)
   - Example: `Ki (nM)` = 1.0
   - Use this for filtering, sorting, statistics

2. **`[Measurement] (nM) Raw`** - Original string with qualifiers
   - Example: `Ki (nM) Raw` = '<1'
   - Preserves scientific context

3. **`[Measurement] (nM) Qualifier`** - Machine-readable qualifier
   - `'exact'` - Precise measurement (e.g., '5.2')
   - `'less_than'` - Below detection limit (e.g., '<1')
   - `'greater_than'` - Above measurement range (e.g., '>10000')

**Why this matters**:
- ~13% of Ki measurements have inequality qualifiers
- `<1 nM` means very tight binding (below detection limit)
- `>10000 nM` means very weak or no detectable binding
- Critical for proper ranking and data quality assessment

**Example usage**:
```python
# Filter for exact measurements only
exact_ki = df[df['Ki (nM) Qualifier'] == 'exact']

# Find tight binders (including < values)
tight = df[(df['Ki (nM)'] < 10) | (df['Ki (nM) Qualifier'] == 'less_than')]

# Display with qualifiers
for _, row in df.iterrows():
    print(f"{row['BindingDB Ligand Name']}: Ki = {row['Ki (nM) Raw']}")
```

### Comprehensive Field Coverage (640 fields)

The SQLite database includes extensive metadata beyond basic affinity measurements:

**Affinity Measurements**: Kd, Ki, IC50, EC50 (with 3-field structure)
**Kinetic Parameters**: kon, koff, association/dissociation rates
**Target Information**: UniProt ID, target name, organism, gene name
**Ligand Information**: SMILES, InChI, InChI Key, molecular weight
**Experimental Conditions**: pH, temperature, assay type
**PDB Structures**: Structure IDs, ligand IDs, chain IDs
**References**: PubMed ID, DOI, patent numbers, authors
**Metadata**: BindingDB ID, measurement dates, data quality flags

See full 640-field list in the database or use `get_sqlite_database_stats()` for details.

## Best Practices

1. **Use the local SQLite database**: 640 fields per record, <1ms query performance, 3M+ measurements
   ```python
   # Docker container (default)
   db = BindingDBUtils(sqlite_db_path='/app/bindingdb.db')
   ```

2. **Retrieve sufficient data for analysis**: SQLite results are unordered
   ```python
   # ❌ BAD - May miss rare measurements (e.g., Kd when mostly Ki/IC50)
   data = db.get_binding_data_by_uniprot_sqlite('P08246', limit=1000)
   
   # ✅ GOOD - Use high limit or omit for comprehensive analysis
   data = db.get_binding_data_by_uniprot_sqlite('P08246', limit=10000)
   ```

3. **Check which measurement types are available**: Not all targets have all types
   ```python
   kd_count = df['Kd (nM)'].notna().sum()
   ki_count = df['Ki (nM)'].notna().sum()
   ic50_count = df['IC50 (nM)'].notna().sum()
   
   print(f"Kd: {kd_count}, Ki: {ki_count}, IC50: {ic50_count}")
   
   # Use the most abundant measurement type
   if ki_count > kd_count:
       affinity_col = 'Ki (nM)'
   ```

4. **Always check DataFrame state before accessing columns**: Prevent KeyError on empty results
   ```python
   # Check if data exists and has required columns
   if not df.empty and 'Ki (nM)' in df.columns:
       high_affinity = df[df['Ki (nM)'].notna() & (df['Ki (nM)'] < 10)]
   else:
       high_affinity = pd.DataFrame()
       print("Warning: No data or column not available")
   ```

5. **Handle affinity qualifiers properly**: Check the qualifier field for data quality
   ```python
   # Filter for exact measurements only (exclude < and >)
   exact_only = df[df['Ki (nM) Qualifier'] == 'exact']
   
   # Or include less_than for tight binders
   tight_binders = df[
       ((df['Ki (nM) Qualifier'] == 'exact') & (df['Ki (nM)'] < 10)) |
       (df['Ki (nM) Qualifier'] == 'less_than')
   ]
   ```

6. **Use safe JSON serialization**: When saving DataFrame data
   ```python
   utils.save_json(results, '/output/final_results.json')
   ```

7. **Handle None values in string operations**: Use pandas `.str` accessor
   ```python
   df['has_pdb'] = df['pdb_id'].str.startswith('1', na=False)
   ```

8. **Convert to pKd for easier comparison**:
   ```python
   import numpy as np
   df['pkd'] = -np.log10(df['kd'] * 1e-9)  # nM to M, then -log10
   ```

9. **Cross-reference with ChEMBL for compound properties**: BindingDB focuses on binding; use ChEMBL for MW, LogP, etc.

## Common Pitfalls

1. ❌ **Accessing columns without checking DataFrame state**: Always verify data exists
   ```python
   # WRONG: KeyError if df is empty or column doesn't exist
   result = df[df['kd'] < 10]
   
   # RIGHT: Check first
   if not df.empty and 'kd' in df.columns:
       result = df[df['kd'] < 10]
   ```

2. ❌ **Confusing with ChEMBL identifiers**: BindingDB uses UniProt IDs, not ChEMBL IDs
3. ❌ **Expecting compound properties**: BindingDB focuses on binding data, not chemical descriptors

4. ❌ **Not handling NaN in JSON**: Always use `utils.save_json()`
5. ❌ **Mixing units**: BindingDB typically uses nM for binding constants
6. ❌ **Not checking measurement type availability**: Different targets have different measurement types (Kd, Ki, IC50)
   - Some targets have mostly Ki data, others mostly IC50
   - Always check what's available: `df['Ki (nM)'].notna().sum()`
   - Use high limits (≥5000) when searching for rare measurement types
7. ❌ **Ignoring affinity qualifiers**: ~13% of measurements have `<` or `>` symbols
   - `<1 nM` = "very tight binding, below detection limit"
   - `>10000 nM` = "weak or no binding"
   - Check `'Ki (nM) Qualifier'` field for proper interpretation

## Files

- `bindingdb_utils.py`: Core utility library with API wrappers
- `BindingDB-agent-definition.yaml`: Agent configuration and instructions
- `BindingDB-tool-definition.yaml`: Tool definitions (empty - uses direct API)
- `Dockerfile`: Container definition with dependencies
- `README.md`: This file

## Installation

The agent runs in a Docker container with all required dependencies:
- Python 3.12
- pandas (data manipulation)
- sqlite3 (database access, built-in to Python)

The SQLite database is optimized with:
- **Page size**: 1024 bytes (30% space savings vs default 4096)
- **Size**: 8-9 GB (down from 12-13 GB with default page size)
- **Performance**: <1ms queries with proper indexing
- **Measurements**: 3,078,835 rows × 640 fields

## Related Resources

- [BindingDB Website](https://www.bindingdb.org/)
- [BindingDB Database Downloads](https://www.bindingdb.org/rwd/bind/chemsearch/marvin/SDFdownload.jsp)
- [BindingDB Data Download](https://www.bindingdb.org/bind/chemsearch/marvin/SDFdownload.jsp)

## Complementary Agents

- **ChEMBL Agent**: For broader bioactivity data and compound properties
- **PubChem Agent**: For chemical properties and structure searches
- **PDB Agent**: For protein structure information
