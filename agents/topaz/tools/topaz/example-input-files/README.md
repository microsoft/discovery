# Topaz Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Micrographs
- Pixel size and scale metadata
- Optional labeled particle coordinates or pretrained model

## Expected output contract

- Particle coordinates and scores
- Denoised micrographs when requested
- Training metrics

## Validation

Coordinate scale and image downsampling must be tracked; denoising output should not replace independent quantitative validation.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
