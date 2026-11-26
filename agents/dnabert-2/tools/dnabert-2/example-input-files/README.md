# DNABERT-2 Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- DNA sequences
- Matching tokenizer and checkpoint
- Task configuration

## Expected output contract

- Sequence embeddings
- Task predictions
- Fine-tuned models when requested

## Validation

Review any trust_remote_code requirement before use; pin and inspect checkpoint-provided source and sequence-length limits.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
