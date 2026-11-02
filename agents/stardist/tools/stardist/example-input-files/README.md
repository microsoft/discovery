# StarDist Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Microscopy images
- Axis and voxel-size metadata
- Model and normalization configuration

## Expected output contract

- Instance labels
- Object geometry and probabilities
- Segmentation previews

## Validation

Choose 2D versus 3D models explicitly; validate axis order, normalization, tiling, and star-convex shape assumptions.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
