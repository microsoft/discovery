# TorchANI Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Molecular structures
- ANI model selection
- Optimization or dynamics settings

## Expected output contract

- Energies and forces
- Optimized geometries
- Trajectories when requested

## Validation

Enforce the selected model's supported elements and chemistry; report energy conversion and molecular charge limitations.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
