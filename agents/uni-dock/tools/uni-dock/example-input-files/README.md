# Uni-Dock Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Prepared receptor PDBQT
- Ligand PDBQT files
- Search box and scoring settings

## Expected output contract

- Docked ligand poses
- Docking scores and batch logs

## Validation

Validate ligand preparation, torsions, box dimensions, and batching; input/output mapping must survive failed ligands.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
