# Geneformer Third-Party Review Notes

## Source-only status

This scaffold contains no copied upstream scientific implementation, installed
packages, model checkpoints, databases, or built images. This document is a
release-review checklist, not a complete license inventory for a built image.

Upstream: <https://huggingface.co/ctheodoris/Geneformer>.

Candidate-list license hint: **Apache-2.0 (candidate listing); verify selected code and checkpoint terms**.

## Required review before distribution

- Verify the license text at the selected upstream commit; do not infer rights from this hint.
- Review checkpoints, tokenizer/vocabulary data, databases, and model cards separately.
- Obtain authorization for non-commercial, academic-only, gated, or restricted artifacts.
- Inventory direct/transitive dependencies, plugins, CUDA, and cuDNN redistribution terms.
- Preserve required notices, attribution, and corresponding-source obligations.
- Record versions, artifact hashes, terms, and any required access approval.

## Tool-specific considerations

Match model generation and tokenization conventions; in-silico perturbations do not establish causal biological effects.
