# NVIDIA ALCHEMI Toolkit

Expert agent for high-throughput, GPU-first AI atomic simulation using the
[NVIDIA ALCHEMI Toolkit](https://github.com/NVIDIA/nvalchemi-toolkit) — a batch-first
Python framework for machine-learned interatomic potentials (MLIPs).

The agent plans and writes a single Python workflow script, then executes it inside a
CUDA container. It relaxes and simulates many structures in one batched GPU pass rather
than looping over them, which is where the toolkit's throughput advantage comes from.

## Overview

- **Intended users**: computational chemists and materials scientists running MLIP-driven
  relaxation, molecular dynamics and screening campaigns; ML researchers training or
  fine-tuning potentials.
- **Successful outcome**: relaxed structures, MD trajectories, screening summaries or a
  trained checkpoint written to `/output`, together with `final_results.json`.

## Architecture

This agent operates as a `kind: prompt` agent within Discovery Studio.

    User Input → NVIDIA ALCHEMI Toolkit (LLM) → nvidiaAlchemi Tool (Container) → Results

- **Model**: configured via the `{{CHAT-MODEL}}` parameter at deploy time
- **Potentials**: MACE (foundation checkpoints `small-0b` and `medium-0b2` baked into
  the image), AIMNet2 (`aimnet2` checkpoint, also baked in), Lennard-Jones, DFT-D3(BJ),
  Ewald, PME — composable with the `+` operator or an explicit pipeline
- **Dynamics**: FIRE / FIRE2 optimizers and NVE, NVT (Langevin, Nosé-Hoover), NPT and
  NPH integrators sharing one execution loop with nine hook points per step
- **Scaling**: fused multi-stage pipelines and inflight batching on one GPU;
  `DistributedPipeline` and domain decomposition across GPUs via `torchrun`
- **Output**: extended XYZ / CIF structures, Zarr trajectories, CSV summaries, plots,
  and training checkpoints

## Prerequisites

- Azure subscription with a Discovery workspace
- GPU nodepool (H100 or A100 recommended); multi-GPU SKU for distributed workflows
- Model deployment for the agent LLM (e.g. GPT-4o)
- An Azure Container Registry with push permission, and a Docker/Podman or
  `az acr build` environment with internet access to the public package indexes,
  model download sites and roughly 40 GB of free build disk

## Configuration

| Parameter | Description | Example |
|---|---|---|
| `{{CHAT-MODEL}}` | Model deployment name for the agent LLM | `gpt-4o-deployment` |

## Build and deploy the tool image

The single build recipe is [tools/nvidia-alchemi/Dockerfile](tools/nvidia-alchemi/Dockerfile).
**Use this agent directory as the build context, not the nested tool directory**,
because the image also records the agent instructions and tool definition:

```bash
docker build -f tools/nvidia-alchemi/Dockerfile -t <registry>.azurecr.io/nvidia-alchemi:1.1.2 .
az acr login --name <registry>
docker push <registry>.azurecr.io/nvidia-alchemi:1.1.2
```

or, without a local Docker daemon,
`az acr build --registry <registry> --image nvidia-alchemi:1.1.2 --file tools/nvidia-alchemi/Dockerfile .`

The build starts from the public `nvidia/cuda:13.0.1-devel-ubuntu24.04` image pinned
by digest, installs the exact package versions in
[requirements-build.txt](tools/nvidia-alchemi/requirements-build.txt) without
further dependency resolution, and runs `pip check`. It downloads the MACE
`small-0b` and `medium-0b2` and AIMNet2 checkpoints and fails unless every file
matches the size and SHA-256 in [checkpoints.json](tools/nvidia-alchemi/checkpoints.json).
It then writes `/app/release-manifest.json` (base digest, package inventory,
checkpoint and source hashes), preserves distribution license files under
`/app/licenses`, and runs the regression suite. Jobs need no network access.

Deploy the tool from `tools/nvidia-alchemi/tool.yaml`; the deployer substitutes
`{name}` with your registry. Prefer referencing the pushed image by digest.
Prompt updates and container updates are separate operations; verify both.

### Package layout

This package contains the agent/tool definitions, runtime helpers, build inputs,
provenance generator, smoke test, regression tests, examples, and third-party notices.

### Verified output contract

- Declare every deliverable in `save_final_results(output_files=...)` using its
  existing source path. NPZ, Python, text, arbitrary other extensions, and nested
  directories are supported. Relative paths resolve under the configured work directory.
- Declared sources are copied into the captured output directory and SHA-256/size
  verified. Returned paths and the saved result point at exported destinations.
  An artifact manifest records every delivered file, including directory contents.
- Missing sources, collisions, symlinks, and corrupted copies fail explicitly.
  A failed export cannot advertise a completed result. `quick_finish()` repeats
  final export/verification so declared logs updated after an earlier save are current.
- Close writers before finalization. Once results are saved, undeclared scratch
  files are not exported. Scripts that only call `quick_finish()` retain a limited,
  top-level legacy artifact-discovery mode; explicit declarations are preferred.
- Use `write_json_atomic()` for auxiliary JSON. Nonfinite values are encoded as
  diagnostic objects with `value: null`, `finite: false`, and an `encoding` of
  `nan`, `+inf`, or `-inf`. Unsupported objects are rejected, not stringified.
- Use `output_files={}` explicitly when clearing broken declarations in an error
  handler. A later save with `output_files=None` retains previous declarations.

### Screening identity and independent checks

`screen()` returns structures in graduation order. Match them with
`atoms.info['input_index']`, the original zero-based input position. The separate
`system_id` is assigned by the toolkit in admission order and can differ from
input order for mixed-size batches. Caller metadata is restored; pre-existing
caller IDs are retained as `source_system_id` and `source_input_index`. Missing,
duplicate, or out-of-range returned identities raise rather than misattribute data.

`batch_to_atoms()` retains these IDs, masses, and toolkit-native velocities in
`atoms.arrays['alchemi_velocities']`. It deliberately does not label the latter
as ASE velocities without a unit conversion.

The [reviewed validators](tools/nvidia-alchemi/alchemi_validators.py) provide
finite/shape-aware numeric comparison, NumPy float64 kinetic energy and drift
references, and actual paired-hook-event auditing. Verdicts distinguish `pass`,
`fail`, `unverified`, and `unexercised`. Provenance labels and alias detection
cannot alone prove logical independence; callers must retain real observations.

### Evaluation, recording and model lookup

- `single_point(batch, model)` evaluates energies and forces for fixed geometries.
  It builds the neighbor list itself; model wrappers have no `compute()`, calling
  `model(batch)` directly fails without a neighbor list, and a zero-step `run()`
  silently leaves energies at zero.
- `step_recorder()` is a ready-made hook for `run_md(..., hooks=[recorder])`.
  `recorder.rows` holds energy, kinetic energy, temperature and maximum force for
  every step and structure. Custom hooks must provide integer `frequency`, a
  `stage`, and `__call__(ctx, stage)`.
- `write_structures()` accepts a `Batch`, a single `ase.Atoms`, or a list of them.
- `/app/release-manifest.json` names each cached checkpoint by `loader` and `name`
  next to its path, size and SHA-256. Look models up by name, not by filename.
- Batch field names: the atom-to-structure index is `batch_idx` and masses are
  `atomic_masses`.

Tests are in [tools/nvidia-alchemi/tests](tools/nvidia-alchemi/tests). Run them using
Python's `unittest` discovery with the tool directory on `PYTHONPATH`; no pytest
dependency is required. Real toolkit identity tests run in the release image;
set `ALCHEMI_TEST_GPU=1` to require GPU execution rather than the CPU test path.
The [release smoke runner](tools/nvidia-alchemi/release_smoke.py) requires a GPU
by default and produces an artifact manifest for post-download verification.

## Tools

| Tool | Path | Description |
|---|---|---|
| `nvidiaAlchemi` | `tools/nvidia-alchemi/` | NVIDIA ALCHEMI Toolkit container for batched MLIP relaxation, molecular dynamics, screening, training and multi-GPU simulation |

**Compute requirements**: 1–8 GPUs, 8–96 vCPU, 64 Gi–1800 Gi RAM. Recommended SKUs:
`Standard_NC40ads_H100_v5`, `Standard_NC80adis_H100_v5`, `Standard_ND96isr_H100_v5`,
`Standard_NC24ads_A100_v4`, `Standard_NC48ads_A100_v4`.

**Supported inputs**: XYZ, extended XYZ, CIF, PDB, POSCAR/CONTCAR, ASE trajectory files.
**Outputs**: extended XYZ / CIF structures, Zarr trajectory stores, CSV summaries, PNG
plots, training checkpoints, and `final_results.json`.

## Usage

### Example inputs

The image includes small sample structures in `/app/example-input-files`:
`water.xyz`, `ethanol.xyz`, `si_bulk.cif` and `cu_bulk.extxyz`. They are also in
[tools/nvidia-alchemi/example-input-files](tools/nvidia-alchemi/example-input-files).

```
Relax the water and ethanol examples in /app/example-input-files with MACE and report their energies.
```

### Batched geometry relaxation

```
Relax all the structures in my input directory with MACE to a maximum force of 0.03 eV/Å.
```

### Molecular dynamics

```
Run 50 ps of NVT molecular dynamics at 300 K on this system with MACE and save the trajectory.
```

### Multi-stage pipeline

```
Relax this structure, equilibrate it at 300 K, then run a 20 ps production trajectory.
```

### High-throughput screening

```
Screen these 5,000 candidate structures: relax each one and rank them by energy per atom.
```

### Model composition

```
Run MD on this molecular crystal using MACE with a DFT-D3 dispersion correction.
```

### Fine-tuning

```
Fine-tune the MACE small-0b checkpoint on the trajectory in train.zarr for 20 epochs,
weighting forces ten times more than energies.
```

### Multi-GPU

```
Screen these structures across 4 GPUs using a relaxation stage feeding an NVT stage.
```

## Support

For questions and bug reports, use the Microsoft Discovery community discussions:
<https://techcommunity.microsoft.com/category/azure/discussions/microsoft-discovery-discussions>

Microsoft Discovery team contact: discovery-catalog@microsoft.com

## Known Limitations

- **GPU required.** There is no CPU fallback for the accelerated neighbor-list and
  interaction kernels.
- **Screening returns only converged structures.** `screen()` collects systems that
  reached `fmax`; anything still above the threshold when the step budget runs out is
  not collected. The helper logs a warning naming the shortfall — raise `max_steps` or
  loosen `fmax` to capture the remainder.
- **UMA / fairchem-core is not available.** Upstream declares the `uma` extra mutually
  exclusive with the `mace`, `cu12` and `cu13` extras (incompatible `e3nn` / `torch`
  pins), and its checkpoints require gated HuggingFace access. Use MACE or AIMNet2.
- **Multi-GPU workflows require `torchrun`** and a multi-GPU SKU. `DistributedPipeline`
  and `DomainParallel` run in a separate script launched as one process per GPU, not
  inline in the main workflow script.
- **Distributed communication is one-to-one.** Each rank talks to at most one upstream
  and one downstream neighbour; fan-out and fan-in topologies are not yet supported.
- **Upstream is a public beta (0.2.0)** and its API is subject to change between
  releases. The helper library resolves symbols defensively and reports the installed
  version when one moves.
- **`Batch` → `ase.Atoms` conversion is provided by this agent**, not by the toolkit;
  it carries geometry, energies, forces, stress, identity, masses and separately
  labelled toolkit-native velocities, not arbitrary tensor metadata. `screen()`
  restores caller `info` metadata using its checked input index.
- **Accuracy is bounded by the chosen potential.** Foundation MLIPs are not a substitute
  for DFT on chemistry far outside their training distribution, and the classical
  potentials ship with generic parameters (argon for LJ, the PBE damping set for
  DFT-D3) that should be overridden for the system under study.

## Verification status

This release (1.1.2) was validated on one H100 NVL, using the agent itself:

- **Regression smoke:** all **32 tests** passed with no skips; independent download
  verification checked all 30 declared files, input-identity mapping and NumPy
  reference calculations.
- **Offline models:** MACE `small-0b`, MACE `medium-0b2` and AIMNet2 were each
  selected by name from the release manifest, hash-checked, and evaluated with
  `single_point()`; all outputs were finite on CUDA and agreed with CPU results to
  about $2\times10^{-6}$ eV.
- **MACE dynamics:** 100 steps of nonperiodic NVT on three water molecules with
  `medium-0b2` completed with all values finite. The final kinetic energy recomputed
  independently from the saved velocities and masses matched the recorded value
  to $8\times10^{-9}$ eV.

Earlier H100 evaluations also exercised Lennard-Jones and demo workflows, NPT
response, exact trajectory readback and defensive hooks. See the
[changelog](CHANGELOG.md) for what changed in each release.

This is not physical-accuracy certification. Multi-GPU execution, full training,
periodic/multi-system MACE, cuEquivariance acceleration, explicit compiled MACE,
and drift-triggered warning branches remain outside completed validation coverage.

## License

The agent definitions and wrapper code are governed by the catalog repository's
[MIT license](https://github.com/microsoft/discovery/blob/main/LICENSE). Bundled
third-party components keep their own licenses (see below).

## Third-Party Components

| Component | Version | License | Source |
|---|---|---|---|
| NVIDIA ALCHEMI Toolkit | 0.2.0 | Apache-2.0 | <https://github.com/NVIDIA/nvalchemi-toolkit> |
| NVIDIA CUDA base image | 13.0.1 | NVIDIA Deep Learning Container License | <https://docs.nvidia.com/cuda/eula/> |
| MACE (+ `small-0b` / `medium-0b2` checkpoints) | 0.3.15 | MIT | <https://github.com/ACEsuit/mace> |
| AIMNet2 (+ `aimnet2` checkpoint) | 0.2.0 | MIT | <https://github.com/isayevlab/aimnetcentral> |
| PyTorch | 2.13.0+cu130 | BSD-3-Clause | <https://github.com/pytorch/pytorch> |

> Full attribution, citation requirements and license-file locations are in
> [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Contributing

This project welcomes contributions and suggestions. Please see the catalog's
[CONTRIBUTING guidelines](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md)
for details on how to contribute.
