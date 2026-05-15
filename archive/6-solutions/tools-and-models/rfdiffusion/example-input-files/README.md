# RFDiffusion Example Input Files

Sample PDB files for testing RFDiffusion design workflows. Place these in your
investigation's `inputs/` directory (via `investigation_write_file(category='input')`)
so they are mounted at `/input/` in the container and copied to `/workdir/` by `quick_setup()`.

## Files

### `1UBQ.pdb`
- **Use case**: Binder design (`design_binder()`), motif scaffolding (`scaffold_motif()`)
- **Contents**: Human ubiquitin (PDB: 1UBQ), chain A, 76 residues
- **Source**: RCSB PDB — a real experimental structure (X-ray, 1.8 Å resolution)
- **Why ubiquitin**: Small, well-characterized, single chain — ideal for quick validation
- **Example usage** (binder design targeting the Ile44 hydrophobic patch):
  ```python
  from rfdiffusion_utils import design_binder, get_pdb_chain_info

  chain_info = get_pdb_chain_info('1UBQ.pdb')
  # chain_info → {'A': {'num_residues': 76, 'start': 1, 'end': 76}}

  result = design_binder(
      target_pdb='1UBQ.pdb',
      target_chain='A',
      target_start=1,
      target_end=76,
      binder_length=(70, 100),
      hotspot_residues=['A8', 'A44', 'A68', 'A70'],
      num_designs=5,
  )
  ```
- **Example usage** (motif scaffolding of the β-hairpin):
  ```python
  from rfdiffusion_utils import scaffold_motif

  result = scaffold_motif(
      motif_pdb='1UBQ.pdb',
      motif_spec='A23-34',
      n_term_length=(10, 25),
      c_term_length=(10, 25),
      num_designs=5,
  )
  ```

### `target_helix.pdb`
- **Use case**: Binder design (`design_binder()`)
- **Contents**: 40-residue synthetic alpha helix, chain A, residues 1–40
- **Atoms**: 160 backbone atoms (N, CA, C, O per residue)
- **Example usage**:
  ```python
  from rfdiffusion_utils import design_binder, get_pdb_chain_info

  chain_info = get_pdb_chain_info('target_helix.pdb')
  result = design_binder(
      target_pdb='target_helix.pdb',
      target_chain='A',
      target_start=1,
      target_end=40,
      binder_length=(50, 80),
      hotspot_residues=['A10', 'A15', 'A20'],
      num_designs=10,
  )
  ```

### `motif_fragment.pdb`
- **Use case**: Motif scaffolding (`scaffold_motif()`)
- **Contents**: 18-residue alpha helix fragment, chain A, residues 163–180
- **Atoms**: 72 backbone atoms (N, CA, C, O per residue)
- **Example usage**:
  ```python
  from rfdiffusion_utils import scaffold_motif

  result = scaffold_motif(
      motif_pdb='motif_fragment.pdb',
      motif_spec='A163-180',
      n_term_length=(10, 30),
      c_term_length=(10, 30),
      num_designs=10,
  )
  ```

## Notes

- `1UBQ.pdb` is a **real experimental structure** from RCSB PDB — use it for realistic validation
- `target_helix.pdb` and `motif_fragment.pdb` are **synthetic** structures with idealized
  alpha helix geometry (3.6 residues/turn, 1.5 Å rise per residue, 2.3 Å radius)
- For production binder design, use real PDB structures from RCSB PDB
- Unconditional generation and symmetric oligomer design do **not** require input files
