# OpenMM-ML Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Molecular topology and coordinates
- Potential and supported elements
- ML region and MD settings

## Expected output contract

- Trajectories and thermodynamic logs
- Final structures
- Potential and platform provenance

## Validation

Validate potential-specific plugin requirements and hybrid ML/MM support; select the CUDA platform explicitly.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
