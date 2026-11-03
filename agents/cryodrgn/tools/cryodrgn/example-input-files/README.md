# cryoDRGN Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Particle stacks
- Particle poses and CTF data
- Reconstruction and training parameters

## Expected output contract

- Model checkpoints and latent embeddings
- Reconstructed volumes
- Heterogeneity analysis

## Validation

Validate pose/CTF alignment and pixel size; latent trajectories are model interpretations rather than measured molecular dynamics.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
