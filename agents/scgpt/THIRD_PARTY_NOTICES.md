# scGPT Third-Party Review Notes

## Source-only status

This scaffold contains no copied upstream scientific implementation, installed
packages, model checkpoints, databases, or built images. This document is a
release-review checklist, not a complete license inventory for a built image.

Upstream: <https://github.com/bowang-lab/scGPT>.

Candidate-list license hint: **MIT (code); verify pretrained model terms**.

## Required review before distribution

- Verify the license text at the selected upstream commit; do not infer rights from this hint.
- Review checkpoints, tokenizer/vocabulary data, databases, and model cards separately.
- Obtain authorization for non-commercial, academic-only, gated, or restricted artifacts.
- Inventory direct/transitive dependencies, plugins, CUDA, and cuDNN redistribution terms.
- Preserve required notices, attribution, and corresponding-source obligations.
- Record versions, artifact hashes, terms, and any required access approval.

## Tool-specific considerations

Match gene symbols, vocabulary, normalization, and binning to the checkpoint; pretrained embeddings are not validated clinical labels.
