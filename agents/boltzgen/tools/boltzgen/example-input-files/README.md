# BoltzGen Example Input Files

## Structure Files

BoltzGen design specifications reference target structure files (CIF or PDB format).
These files must be **real, valid structures** from RCSB PDB or experimental data.

### How to get target structures

Download from RCSB PDB:
```bash
# Download mmCIF format (recommended)
curl -o 1g13.cif https://files.rcsb.org/download/1g13.cif

# Download PDB format
curl -o 1g13.pdb https://files.rcsb.org/download/1g13.pdb
```

### Included examples

- **protein_binder_design.yaml** — Design a protein binder (60-100 residues) against a target.
  Requires a target `.cif` file referenced in the YAML. Download `1g13.cif` from RCSB PDB.

- **peptide_binder_design.yaml** — Design a peptide binder (12-25 residues) with binding
  site specification. Requires a target `.cif` file. Download `6m1u.cif` from RCSB PDB.

### Important notes

- **Residue indices** in YAML files use `label_asym_id` (canonical mmCIF index), NOT `auth_asym_id`.
  Check your indices in [Mol* viewer](https://molstar.org/viewer/).
- **File paths** in YAML are interpreted **relative to the YAML file location**.
- Always run `boltzgen check your_spec.yaml` to validate before the full pipeline.
