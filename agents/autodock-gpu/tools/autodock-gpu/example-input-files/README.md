# AutoDock-GPU Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Ligand PDBQT
- Receptor field and grid maps
- Search and genetic algorithm parameters

## Expected output contract

- Docking logs and poses
- Cluster and energy summaries

## Validation

Choose and record CUDA versus OpenCL backend; this uses AutoDock4 maps and scores, not Vina scoring.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
