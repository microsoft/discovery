# CHGNet Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Periodic inorganic structures
- Checkpoint and relaxation or dynamics parameters

## Expected output contract

- Energies and forces
- Relaxed structures or trajectories
- Magnetic moment estimates when supported

## Validation

Limit interpretation to the model training domain; predicted charge-related quantities are not direct experimental charge measurements.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
