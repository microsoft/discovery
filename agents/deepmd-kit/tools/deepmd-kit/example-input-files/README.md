# DeePMD-kit Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- DeepMD-formatted training data or trained model
- Element mapping
- Training or MD configuration

## Expected output contract

- Trained and exported models
- Energy and force predictions
- Training metrics and trajectories

## Validation

Record backend, model format, element order, units, and supported simulation plugin versions.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
