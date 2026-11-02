# ProteinMPNN Input Guide

No datasets, checkpoints, patient records, or binary example inputs are bundled.
Supply authorized files through the Discovery investigation inputs mounted at `/input`.
The helper does not duplicate large inputs into `/workdir`.

## Required input contract

- Backbone PDB files
- Chain and fixed-position selections
- Model weights and sampling settings

## Expected output contract

- Designed FASTA sequences
- Sequence scores and sampling metadata

## Validation

Preserve chain mappings and fixed residues; scores are not experimental binding affinities.

At release time, add a small authorized fixture and a GPU integration test.
Verify native output contents, identifiers, units, and scientific validity.
