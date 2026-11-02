# scGPT Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Single-cell expression data
- Matching gene vocabulary and checkpoint
- Task and preprocessing settings

## Expected output contract

- Cell or gene embeddings
- Task predictions
- Fine-tuned models when requested

## Validation

Match gene symbols, vocabulary, normalization, and binning to the checkpoint; pretrained embeddings are not validated clinical labels.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
