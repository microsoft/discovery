# MACE Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Structures with periodicity and cell information
- Model checkpoint
- Relaxation or MD parameters

## Expected output contract

- Energies and forces
- Relaxed structures
- Trajectories and convergence records

## Validation

Match elements and training domain to the checkpoint; record units, dispersion settings, stress conventions, and convergence.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
