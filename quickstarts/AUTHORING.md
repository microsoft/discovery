# Authoring QuickStart Scenarios

Use the [nine-section template](templates/SCENARIO.md). Start from the owner's
actual scenario and files, not a new easier experiment. Read existing source
material before requesting it again. The raw Engineering E2E handoff and this
external package share evidence but are not the same delivery.

## Minimum authoring sequence

1. Freeze the exact scenario prompt, scope, input lineage and owner acceptance.
   Record a digest for the prompt. Label newly proposed prompts as proposed.
2. Inventory every dependency, file, paper, helper, expected output and licence.
   Resolve each to included content, an immutable public repository reference,
   a versioned download with checksum, or an explicit blocker.
3. Keep agent/tool implementations canonical. Pin source revisions and image
   digests where known; a mutable `latest` tag is not a reproducible pin.
   Runtime IDs and per-user tool bindings are configuration, not portable IDs.
4. Write the guide and profile together. Separate OS, hardware architecture,
   interpreter, host capabilities, model access and data/index configuration.
   Required unknowns remain unknown, not invented defaults or unsupported claims.
5. State when setup changes local files, downloads code, installs dependencies,
   creates indexes or spends model/cloud resources. Require appropriate consent.
   Keep read-only inspection separate. Never remove another user's Python or
   environment as automatic version remediation.
6. Test package/link/hash behavior offline, including unsafe paths, changed
   inputs, missing artifacts and unavailable components. Preserve the earlier
   failures and the exact code revision tested.
7. Obtain an approved live scope, then reproduce from a fresh project without
   personal skills, cached data/indexes, hidden source paths or prior consent.
   Record cold/setup/indexing/scientific/validation time separately.
8. Apply actual owner criteria. Separate structural output checks from the
   correctness of scientific claims; keep any required SME review explicit.
9. Obtain owner/maintainer and distribution approval. A ready label, CLA or
   passing CI is not legal clearance or experimental scientific validation.

## Publication boundaries

No confidential decks, credentials, personal transcripts, protected papers,
private storage URLs or virtual environments in the PR. Metadata may describe
withheld inputs without redistributing them. For public papers retain original
attribution/licence notices and check any third-party exclusions. A new public
corpus is a distinct scenario variant with its own validation, never a silent
replacement for an internal control.

Use [the package contract](PACKAGE-CONTRACT.md) for inventories. Do not manually
edit generated registries or bypass current author/path restrictions. This
new top-level area and future CI integration require maintainer agreement.
No GitHub publication or scientific run is part of the offline helper.

## Verification questions

Ask separately: does this preserve the agreed user contract; do changed
safeguards increase future contract-violation risk; and does it perform the
intended function? Use evidence or Unknown, never an average. For this skeleton,
offline file preparation can pass while app activation and science remain
Not run. Sanitized reference evidence must retain that distinction.