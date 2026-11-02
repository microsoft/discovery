# scvi-tools Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- AnnData with raw counts
- Batch and assay annotations
- Model and training parameters

## Expected output contract

- Trained models
- Latent embeddings
- Model-specific denoised values and differential analysis

## Validation

Preserve raw counts and cell/gene identifiers; assay modalities determine model choice. Explicitly request a GPU accelerator.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
