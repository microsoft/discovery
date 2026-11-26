# Cellpose Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Microscopy images
- Channel and dimensionality metadata
- Model and segmentation settings

## Expected output contract

- Instance masks
- Object-level measurements
- Segmentation previews and model metadata

## Validation

Cellpose releases differ in model and channel APIs; preserve image dimensions, voxel spacing, and mask IDs.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
