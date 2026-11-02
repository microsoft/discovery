# NequIP Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Energy and force training data or trained model
- Element mapping
- Training or simulation configuration

## Expected output contract

- Trained or exported models
- Energy and force predictions
- Validation metrics

## Validation

Modern and legacy NequIP releases have different configuration and model formats; pin a mutually compatible stack.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
