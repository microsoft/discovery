# Changelog

All notable changes to the NVIDIA ALCHEMI Toolkit agent are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
agent uses [Semantic Versioning](https://semver.org/). Versions match `version` in
`metadata.yaml` and `tools/nvidia-alchemi/tool.yaml` and the container image tag.

## [1.1.2] - 2026-10-01

Catalog-policy and security-hardening release. Scientific algorithms and bundled
checkpoint bytes are unchanged from 1.1.1.

### Security

- Updated GitPython, hydra-core, multidict and urllib3 to patched versions after
  dependency review identified published advisories.
- Checkpoints are downloaded, size/hash verified, and only then deserialized.
- Runtime learned-model aliases resolve only to hash-verified checkpoints baked
  into the image; explicit existing local paths remain available for training
  checkpoints.
- Cached learned-model files are read-only, and `logs.out` is reserved from
  artifact replacement.

### Changed

- The pinned dependency list is renamed from `requirements-build.lock` to
  `requirements-build.txt`, a file type the catalog accepts.
- CPU execution must be explicitly requested for validation; deployed workflows
  fail when CUDA is unavailable.
- Experimental workflows outside completed validation coverage are identified in
  catalog descriptions and require explicit user confirmation.
- Catalog tags use the catalog vocabulary: `machine-learning`, `gpu` and
  `simulation` replace `machine-learned-potential`, `gpu-accelerated` and
  `high-throughput`.

### Fixed

- Image-build tests can import the checkpoint downloader from `/app/build`
  without adding that directory to the runtime import path.
- Screening validation tests explicitly use the selected test device, and the
  release-manifest test checks the shared AIMNet cache under `/opt/cache/aimnet`.

### Validation

- Rebuilt from a clean image: 43 regression tests passed on CPU and on one H100 NVL
  with no skips, and the GPU release smoke passed.
- MACE `small-0b`, MACE `medium-0b2` and AIMNet2 inference, MACE relaxation and
  100-step nonperiodic NVT were revalidated on H100 with independent numerical
  checks. See the README verification status.

## [1.1.1] - 2026-10-01

### Added

- `single_point(batch, model)`: the supported way to evaluate energies and forces for
  fixed geometries. It builds the neighbor list itself and rejects missing or
  non-finite outputs.
- `step_recorder()`: a ready-made dynamics hook that records energy, kinetic energy,
  temperature and maximum force for every step and structure.
- The release manifest now names each cached checkpoint (`loader` and `name`) next
  to its path, size and SHA-256, so models can be looked up by name.
- Distribution license and notice files are copied into the image under
  `/app/licenses/`, and their per-package counts are recorded in the manifest.
- Regression tests for the new helpers and the manifest, bringing the suite to 32.

### Changed

- The image is built from the public `nvidia/cuda:13.0.1-devel-ubuntu24.04` image,
  pinned by digest, instead of a private parent image. Anyone can now rebuild it.
  It installs the same 198 package versions as 1.1.0 from
  `requirements-build.lock`, without further dependency resolution.
- MACE `small-0b`, MACE `medium-0b2` and AIMNet2 checkpoints are downloaded at build
  time, and the build fails unless every file matches its recorded SHA-256.
  Jobs still run offline.
- The release manifest records the actual base image, build inputs and release
  version. The smoke test reports the release and the helper-library version
  separately.
- Agent instructions document the new helpers, the custom-hook requirements, batch
  field names (`batch_idx`, `atomic_masses`) and checkpoint lookup by name.
- The README is self-contained for the catalog: support links point to the
  Microsoft Discovery community, and build and deployment steps are documented.
- The release smoke test is renamed from `hardening_smoke.py` to `release_smoke.py`.
- The build fails if any source file has Windows line endings, so the recorded
  source hashes always match the repository.
- Sample structures in `/app/example-input-files` are documented for users and the agent.

### Fixed

- `write_structures()` crashed when given a single `ase.Atoms`; it now accepts a
  `Batch`, a single `Atoms`, or a list.
- The instructions no longer suggest that model wrappers have a `compute()` method.

### Validation

Validated on one H100 NVL through the agent: 32 regression tests with no skips; all
three cached models selected by name, hash-checked and evaluated on CUDA; and a
100-step MACE NVT run whose final kinetic energy, recomputed independently, matched
the recorded value to $6\times10^{-9}$ eV.

## [1.1.0] - 2026-09-22

### Added

- `alchemi_validators`: NumPy reference calculations for kinetic energy and energy
  drift, finite and shape-aware numeric comparison, and hook-event auditing. Results
  distinguish `pass`, `fail`, `unverified` and `unexercised`.
- `screen()` results carry `input_index`, the original input position, separately
  from the toolkit's admission-order `system_id`.

### Changed

- Declared outputs of any file type, including nested directories, are copied to
  the output folder and verified by SHA-256 and size before results are published.
  An artifact manifest lists every delivered file.
- Results JSON is strict: non-finite values are encoded explicitly and unsupported
  objects are rejected.
- The tool reports the script's real exit status.

### Fixed

- Outputs such as NPZ, Python and text files were silently left out of results.
- Screening results could be matched to the wrong inputs for mixed-size batches.
