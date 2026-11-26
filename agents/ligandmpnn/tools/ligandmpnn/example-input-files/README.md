# LigandMPNN Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Complex PDB files with non-protein atoms retained
- Chain and residue design constraints
- Checkpoint selection

## Expected output contract

- Designed FASTA sequences
- Sequence scores
- Designed structures when supported

## Validation

Preserve ligand and metal atoms; verify supported atom types and checkpoint-specific capabilities.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
