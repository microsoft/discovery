# DNABERT-2 Discovery Agent

## Overview

DNA sequence representation and downstream task modeling using DNABERT-2.

**This folder is a source-only catalog template, not a release build context.**
Its Dockerfile intentionally blocks builds until a scientific runtime is
provisioned and reviewed. Actual runtime recipes and current cloud deployment
state are tracked separately in the [deployment workflow](../../deployment/README.md).
Do not infer the live cloud agent's state from this template's scaffold status.

Upstream: <https://github.com/MAGICS-LAB/DNABERT_2>.

## Architecture

Discovery prompt agent -> associated Python code-environment tool -> future
GPU worker container -> explicitly registered results.

This standalone folder follows the `agents/<name>/tools/<name>/` layout in
[microsoft/discovery](https://github.com/microsoft/discovery/tree/a7d5fef00a8d15e0705c88f2c53a61c02e738526/agents).
Its [agent definition](agent.yaml), [catalog metadata](metadata.yaml), and
[tool definition](tools/dnabert-2/tool.yaml) use the reference catalog schema.
Copy this folder unchanged to a Discovery catalog's `agents/dnabert-2/` directory;
`associated_tools` paths are relative to that destination catalog root, not
to the root of this knowledge-base repository.

## Tools

- **dnabert-2**: [tool configuration](tools/dnabert-2/tool.yaml).
- [Execution utilities](tools/dnabert-2/dnabert_2_utils.py): dependency-free workspace,
  GPU visibility, checked subprocess, and result-manifest helpers.
- [Runtime plan](tools/dnabert-2/runtime-plan.yaml): upstream interfaces, planned
  dependencies, input/output contracts, and release prerequisites.
- [Dockerfile](tools/dnabert-2/Dockerfile): deliberately gated source scaffold.
- [Unit tests](tools/dnabert-2/test_dnabert_2_utils.py): CPU-only helper contract tests,
  not tests of the scientific model.
- [Input guide](tools/dnabert-2/example-input-files/README.md).

## Prerequisites

- Microsoft Discovery project access and an Azure Container Registry.
- GPU worker capacity; the initial sizing mirrors the reference agents.
- A pinned compatible upstream runtime, authorized model/data artifacts,
  and tool-specific GPU smoke tests before image publication.
- Code, checkpoint, dependency, and redistribution license review.
- Confirm publisher ownership and contact values inherited from the Microsoft
  catalog templates before publishing this scaffold as a catalog entry.

## Usage

Current use is configuration review and source scaffolding only. After a future
validated release, request a workflow in the scope below:

> DNA sequence representation and downstream task modeling using DNABERT-2. Use my supplied inputs and return the native
> scientific outputs plus an explicit result manifest and provenance.

### Inputs

- DNA sequences
- Matching tokenizer and checkpoint
- Task configuration

### Outputs

- Sequence embeddings
- Task predictions
- Fine-tuned models when requested

### Local helper tests

From this folder, using the catalog's development requirements:

```powershell
py -m pytest tools\dnabert-2\test_dnabert_2_utils.py -q
```

No GPU, scientific packages, image build, or model download is needed.

## Configuration

- Model deployment: `{{CHAT-MODEL}}`; temperature `0`, topP `0`.
- Associated deployed tool ID: `{{dnabert2ToolId}}`.
- Future ACR image: `{name}.azurecr.io/dnabert-2:0.1.0`.
- Worker: container, static pool, pool size `1`, InfiniBand `false`.
- Minimum: `4` CPUs, `32Gi` RAM, `1` GPU, `0Gi` explicit scratch request.
- Maximum: `96` CPUs, `1800Gi` RAM, `8` GPUs, `0Gi` explicit scratch request.
- Recommended SKUs: `Standard_NC40ads_H100_v5`,
  `Standard_NC80adis_H100_v5`, `Standard_NC24ads_A100_v4`.
- Paths: `/input` (mounted inputs), `/workdir` (working files),
  `/output` (durable results), `/cache` (future authorized model cache).
- Python launcher retains logs and preserves script failure exit codes, following
  the hardened reference tool rather than the older success-masking launcher.

Resource values are scaffold defaults, not measured requirements or assurances
of multi-GPU support. Revisit RAM, GPU VRAM, CPU preprocessing, disk, quota,
checkpoint size, and GPU/CUDA compatibility when provisioning the cloud project.
The CUDA base tag is borrowed from the reference; it is not a compatibility
claim for this tool. TensorFlow, PyTorch, native CUDA, and plugin tools need
their own version-pinned environment and base-image review.

## Known Limitations

Review any trust_remote_code requirement before use; pin and inspect checkpoint-provided source and sequence-length limits.

The installed scientific runtime, exact upstream revision, CUDA/framework
versions, model artifacts, CLI signatures, and integration tests are deliberately
deferred. The generic helper does not implement DNABERT-2.
Do not remove the build gate until those release prerequisites are completed.
Some upstream tools also support CPU modes; this configuration targets their
GPU workflows only, and actual GPU use must be independently verified.

License hint from the candidate list: **Apache-2.0 (candidate listing); verify code and checkpoint terms**.
This is not a verified SPDX assertion or a right to redistribute weights.
See [third-party review notes](THIRD_PARTY_NOTICES.md).

## Contributing

This is generated from the catalog's [candidate manifest](../../scaffolding/candidates.yaml)
and [generator](../../scaffolding/generate.py). Update those sources, then
regenerate; do not hand-edit generated files. Shared helper changes belong in
the [runtime template](../../scaffolding/templates/runtime_utils.py).
The generator references are valid in this knowledge base; after copying an
individual folder to another catalog, maintain it there as a standalone agent.
