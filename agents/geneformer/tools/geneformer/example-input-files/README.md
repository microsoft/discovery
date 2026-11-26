# Geneformer Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Supported single-cell expression files
- Gene identifier mapping
- Token dictionary and checkpoint

## Expected output contract

- Tokenized datasets
- Embeddings
- Perturbation or task-specific prediction summaries

## Validation

Match model generation and tokenization conventions; in-silico perturbations do not establish causal biological effects.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
