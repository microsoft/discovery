# RELION Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- STAR metadata and referenced particle stacks
- CTF and acquisition metadata
- Refinement configuration and optional reference maps

## Expected output contract

- Reconstructed MRC maps
- Updated STAR metadata
- Refinement and resolution diagnostics

## Validation

Preserve pixel size, optics groups, and half-map separation; multi-process and multi-GPU execution require separate validation.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
