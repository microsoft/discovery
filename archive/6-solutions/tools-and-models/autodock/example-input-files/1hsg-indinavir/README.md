# HIV-1 Protease Docking Example (1HSG + HIV Protease Inhibitors)

This example demonstrates molecular docking of FDA-approved HIV protease inhibitors to HIV-1 protease (PDB: 1HSG).

## Files

### Receptor Files

| File | Description |
|------|-------------|
| `1hsg.pdb` | Complete HIV-1 protease crystal structure from RCSB PDB |
| `1hsg_protein.pdb` | HIV-1 protease protein only (chains A+B, no waters/ligands) - **use as receptor** |
| `mk1_ligand.pdb` | Co-crystallized MK1 ligand (indinavir) from crystal structure |
| `reference_ligand.pdb` | Same as mk1_ligand.pdb - **use for grid box calculation** |
| `config.txt` | Pre-configured Vina docking parameters |

### Ligand Files (FDA-Approved HIV Protease Inhibitors)

| File | Drug Name | PubChem CID | Description |
|------|-----------|-------------|-------------|
| `indinavir.sdf` | Indinavir (Crixivan) | 5362440 | First-generation HIV protease inhibitor (3D) |
| `ritonavir.sdf` | Ritonavir (Norvir) | 392622 | Often used as pharmacokinetic booster (2D) |
| `saquinavir.sdf` | Saquinavir (Invirase) | 441243 | First HIV protease inhibitor approved by FDA (2D) |
| `nelfinavir.sdf` | Nelfinavir (Viracept) | 64143 | Second-generation HIV protease inhibitor (3D) |

> **Note**: 2D ligands will have 3D coordinates generated automatically by `prepare_ligand()` during docking.

## Source

- **PDB ID**: 1HSG
- **Citation**: Chen et al. (1994) "Crystal structure of a human immunodeficiency virus type 1 protease in complex with a novel inhibitor"
- **Resolution**: 2.0 Å
- **Ligand**: Indinavir (FDA-approved HIV protease inhibitor)

## Expected Results

Typical docking should produce:
- Best binding affinity: approximately -10 to -12 kcal/mol
- RMSD to crystal pose: < 2.0 Å (successful redocking)

## Usage

```python
from autodock_utils import (
    quick_setup, quick_finish, save_final_results,
    pdb_to_pdbqt_receptor, prepare_ligand,
    calculate_grid_box_from_ligand, run_vina
)

quick_setup()

# Prepare files
receptor = pdb_to_pdbqt_receptor("1hsg_protein.pdb")
ligand = prepare_ligand("indinavir.sdf")

# Calculate grid box from reference ligand
grid_box = calculate_grid_box_from_ligand("reference_ligand.pdb", padding=5.0)

# Run docking
results = run_vina(
    receptor=receptor,
    ligand=ligand,
    grid_box=grid_box,
    exhaustiveness=32
)

save_final_results({"best_affinity": results.best_affinity}, {}, {})
quick_finish()
```

## Download Original Files

To obtain the actual PDB files:

```bash
# Download from RCSB PDB
wget https://files.rcsb.org/download/1HSG.pdb

# Or use BioPython
from Bio.PDB import PDBList
pdbl = PDBList()
pdbl.retrieve_pdb_file('1HSG', pdir='.', file_format='pdb')
```

## Binding Site Residues

Key active site residues for grid box definition:
- Catalytic aspartates: ASP25 (A), ASP25 (B)
- Flap region: ILE50 (A), ILE50 (B)
- S1 pocket: LEU23, ILE84
- S1' pocket: VAL82, ILE84

## Notes

- Remove waters before docking
- Remove co-crystallized ligand for blind docking tests
- Keep ligand for grid box calculation in redocking experiments
