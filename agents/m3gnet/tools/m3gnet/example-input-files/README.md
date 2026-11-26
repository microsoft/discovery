# M3GNet Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Periodic structures
- Compatible M3GNet model
- Relaxation or dynamics settings

## Expected output contract

- Energy and force predictions
- Relaxed structures
- Trajectories

## Validation

Keep legacy TensorFlow M3GNet separate from MatGL; do not mix their model files or assume identical predictions.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
