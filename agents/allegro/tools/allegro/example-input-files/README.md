# Allegro Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Atomistic training data or compatible trained model
- Element mapping and model configuration

## Expected output contract

- Trained or exported Allegro models
- Energies and forces
- Validation metrics

## Validation

Allegro depends on the NequIP ecosystem but has a distinct local architecture; verify model/export and LAMMPS compatibility.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
