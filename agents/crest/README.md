# CREST Agent for Microsoft Discovery

> **CREST 3.0** — Conformer-Rotamer Ensemble Sampling Tool  
> Automated exploration of low-energy molecular chemical space using GFN-xTB semiempirical methods.

## Overview

This agent provides a comprehensive interface to [CREST](https://crest-lab.github.io/crest-docs/), the state-of-the-art tool for conformational sampling developed by the Grimme group. CREST 3.0 features standalone MD/MTD modules, an integrated tblite library, the ANCOPT optimizer, and TOML input file support.

### Key Capabilities

| Feature | Description |
|---------|-------------|
| **Conformational Search** | iMTD-GC and iMTD-sMTD algorithms with automatic convergence |
| **Protonation Screening** | Identify and rank protonation sites |
| **Deprotonation Screening** | Find acidic sites for deprotonation |
| **Tautomer Generation** | Enumerate prototropic tautomers |
| **Conformational Entropy** | Calculate S_conf with rovibrational averaging |
| **NCI Mode** | Sampling for non-covalent complexes (dimers, host-guest) |
| **QCG Solvation** | Quantum cluster growth for explicit microsolvation |
| **MSREACT** | Mass spectral fragmentation prediction |
| **MECP** | Minimum energy crossing points |
| **PCA Clustering** | Identify representative structures from ensembles |
| **Batch Processing** | Process multiple molecules with incremental checkpointing |

### Methods Available

| Method | Speed | Accuracy | Best For |
|--------|-------|----------|----------|
| GFN2-xTB | Baseline | High | Default for most applications |
| GFN1-xTB | ~5x faster | Medium | Organometallics, legacy |
| GFN-FF | ~100x faster | Low-Med | Quick screening, large systems |
| GFN0-xTB | ~50x faster | Low-Med | Fast pre-screening |
| GFN2//GFN-FF | ~10x faster | High | Large molecules (composite) |

## Container Contents

- **CREST 3.0.x** — conformational sampling engine
- **xtb** — semiempirical quantum chemistry (for QCG and legacy features)
- **RDKit** — SMILES parsing and 3D coordinate generation
- **NumPy, SciPy, Matplotlib, Pandas** — scientific Python stack
- **ASE** — Atomic Simulation Environment for file I/O
- **OpenBabel** — file format conversion
- **crest_utils.py** — comprehensive utility library at `/app/crest_utils.py`

## Build Docker Image


```bash
cd crest/
docker build --platform linux/amd64 -t crest:latest .
```

## Usage

### 1. Conformer Search
> "Generate all conformers of ibuprofen within 6 kcal/mol using GFN2-xTB with water solvation. Plot the energy landscape and Boltzmann populations."

### 2. Protonation Sites
> "Find the most favorable protonation sites for caffeine in aqueous solution. Rank them by relative energy and population."

### 3. Tautomer Screening
> "Enumerate all prototropic tautomers of cytosine and rank them by thermodynamic stability."

### 4. Batch Conformer Search
> "Run a conformer search for aspirin, ibuprofen, and naproxen in water. Compare the number of accessible conformers and energy ranges."

### 5. Constrained Conformer Search
> "Search for conformers of alanine dipeptide with the backbone atoms fixed. Use GFN2-xTB with water solvation."

### 6. Explicit Solvation with QCG
> "Build an explicit solvation shell of 15 water molecules around ethanol using quantum cluster growth."

## File Structure

```
crest/
├── Dockerfile                          # Container build
├── crest-tool-definition.yaml          # Tool compute/infra specs
├── crest-agent-definition.yaml         # Agent instructions (<30 KB)
├── crest_utils.py                      # Python utilities library
├── verify_container.py                 # Container import/smoke tests
├── README.md                           # This file
├── SECURITY.md                         # Security scan report
└── example-input-files/
    ├── ethanol.xyz                     # 9 atoms — conformer search test
    ├── glycine.xyz                     # 10 atoms — protonation test
    └── water.xyz                       # 3 atoms — QCG solvent
```

## References

1. P. Pracht, S. Grimme, C. Bannwarth, F. Bohle, S. Ehlert, et al., *J. Chem. Phys.*, **2024**, 160, 114110. [DOI: 10.1063/5.0197592](https://doi.org/10.1063/5.0197592)
2. P. Pracht, F. Bohle, S. Grimme, *Phys. Chem. Chem. Phys.*, **2020**, 22, 7169-7192. [DOI: 10.1039/C9CP06869D](https://doi.org/10.1039/C9CP06869D)
3. S. Grimme, *J. Chem. Theory Comput.*, **2019**, 15, 2847-2862. [DOI: 10.1021/acs.jctc.9b00143](https://doi.org/10.1021/acs.jctc.9b00143)
4. S. Spicher, C. Plett, P. Pracht, A. Hansen, S. Grimme, *J. Chem. Theory Comput.*, **2022**, 18, 3174-3189. [DOI: 10.1021/acs.jctc.2c00239](https://doi.org/10.1021/acs.jctc.2c00239)
5. P. Pracht, C. Bannwarth, *J. Chem. Theory Comput.*, **2022**, 18, 6370-6385. [DOI: 10.1021/acs.jctc.2c00578](https://doi.org/10.1021/acs.jctc.2c00578)

## License

CREST is distributed under the LGPL-3.0 license.

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → CREST (LLM) → CREST Tool (Container) → Results

- **Model:** Configured via the `{{model}}` parameter at deploy time
- **Tool:** CREST 3.0 container for conformational sampling with GFN-xTB semiempirical methods

## Prerequisites

- Azure subscription with Contributor role
- Azure AI Foundry project with a model deployment (e.g. GPT-4o)
- Docker for building the tool container image
- Azure Container Registry (ACR) for hosting the tool image

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
| `crest` | `tools/crest/` | CREST (Conformer-Rotamer Ensemble Sampling Tool) for automated exploration of |

## Known Limitations

No known limitations at this time. If you encounter issues, please report them via the support channel above.

## Contributing

This project welcomes contributions and suggestions. Please see the repository's top-level [CONTRIBUTING guidelines](https://github.com/microsoft/microsoft-discovery-samples/blob/main/CONTRIBUTING.md) for details on how to contribute.