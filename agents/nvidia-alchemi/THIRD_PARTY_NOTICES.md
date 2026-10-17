# Third-Party Notices — nvidia-alchemi agent

The wrapper code in this agent, including the
[runtime helpers](tools/nvidia-alchemi/alchemi_utils.py),
[artifact exporter](tools/nvidia-alchemi/alchemi_artifacts.py),
[validators](tools/nvidia-alchemi/alchemi_validators.py),
[Dockerfile](tools/nvidia-alchemi/Dockerfile), build scripts, and YAML definitions,
is published under the catalog repository's
[MIT license](https://github.com/microsoft/discovery/blob/main/LICENSE). The
components below are installed into, or downloaded into, the container image at
build time and carry their own licenses and citation requirements. Exact package
versions are listed in [requirements-build.txt](tools/nvidia-alchemi/requirements-build.txt).

## Base image and runtime

| Component | Version | License | Source |
|---|---|---|---|
| NVIDIA CUDA base image (`nvidia/cuda:13.0.1-devel-ubuntu24.04`) | 13.0.1 | NVIDIA Deep Learning Container License | <https://docs.nvidia.com/cuda/eula/> |
| Ubuntu 24.04 base packages | 24.04 | various (mostly GPL-2.0 / LGPL-2.1) | <https://ubuntu.com/legal> |
| PyTorch (CUDA 13 build) | 2.13.0+cu130 | BSD-3-Clause | <https://github.com/pytorch/pytorch> |

## ALCHEMI Toolkit

| Component | Version | License | Source |
|---|---|---|---|
| NVIDIA ALCHEMI Toolkit (`nvalchemi-toolkit`) | 0.2.0 | Apache-2.0 | <https://github.com/NVIDIA/nvalchemi-toolkit> |
| `nvalchemi-toolkit-ops` (GPU neighbor-list and interaction kernels) | per `cu13` extra | Apache-2.0 | <https://github.com/NVIDIA/nvalchemi-toolkit-ops> |
| NVIDIA Warp (`warp-lang`) | transitive | Apache-2.0 | <https://github.com/NVIDIA/warp> |
| cuEquivariance | transitive (`cu13`) | Apache-2.0 | <https://github.com/NVIDIA/cuEquivariance> |

## Interatomic potentials and model weights

| Component | License | Source |
|---|---|---|
| MACE (`mace-torch`) | MIT | <https://github.com/ACEsuit/mace> |
| MACE-MP-0b foundation checkpoints (`small-0b`, `medium-0b2`), baked into the image | MIT | <https://github.com/ACEsuit/mace-mp> |
| AIMNet2 (`aimnet`) and its `aimnet2` checkpoint, baked into the image | MIT | <https://github.com/isayevlab/aimnetcentral> |
| DFT-D3(BJ) dispersion parameters | as published by the original authors | <https://doi.org/10.1063/1.3382344> |

UMA / `fairchem-core` is **not** included in this image. Its `uma` extra is declared
mutually exclusive with the `mace`, `cu12` and `cu13` extras upstream, and its
checkpoints are distributed through the gated `facebook/UMA` HuggingFace repository.

## Python scientific stack

| Component | License | Source |
|---|---|---|
| ASE (Atomic Simulation Environment) | LGPL-2.1-or-later | <https://gitlab.com/ase/ase> |
| pymatgen | MIT | <https://github.com/materialsproject/pymatgen> |
| Zarr / numcodecs | MIT | <https://github.com/zarr-developers/zarr-python> |
| NumPy | BSD-3-Clause | <https://github.com/numpy/numpy> |
| SciPy | BSD-3-Clause | <https://github.com/scipy/scipy> |
| pandas | BSD-3-Clause | <https://github.com/pandas-dev/pandas> |
| Matplotlib | Matplotlib License (BSD-compatible) | <https://github.com/matplotlib/matplotlib> |
| seaborn | BSD-3-Clause | <https://github.com/mwaskom/seaborn> |
| Rich | MIT | <https://github.com/Textualize/rich> |

## Citations

Cite the original publications for any potential used in published work.

> Batatia, I. et al. "MACE: Higher Order Equivariant Message Passing Neural Networks
> for Fast and Accurate Force Fields." *Advances in Neural Information Processing
> Systems (NeurIPS)*, 2022. <https://openreview.net/forum?id=YPpSngE-ZU>

> Batatia, I. et al. "A foundation model for atomistic materials chemistry."
> arXiv:2401.00096, 2023. DOI:10.48550/arXiv.2401.00096

> Anstine, D. M., Zubatyuk, R. & Isayev, O. "AIMNet2: a neural network potential to
> meet your neutral, charged, organic, and elemental-organic needs."
> *Chem. Sci.* **16**, 10228-10244, 2025. DOI:10.1039/D4SC08572H

> Grimme, S. et al. "A consistent and accurate ab initio parametrization of density
> functional dispersion correction (DFT-D) for the 94 elements H-Pu."
> *J. Chem. Phys.* **132**, 154104, 2010. DOI:10.1063/1.3382344

> Grimme, S., Ehrlich, S. & Goerigk, L. "Effect of the damping function in dispersion
> corrected density functional theory." *J. Comput. Chem.* **32**, 1456-1465, 2011.
> DOI:10.1002/jcc.21759

> Jones, J. E. "On the Determination of Molecular Fields."
> *Proc. R. Soc. Lond. A* **106** (738), 463-477, 1924. DOI:10.1098/rspa.1924.0082

> Ewald, P. P. "Die Berechnung optischer und elektrostatischer Gitterpotentiale."
> *Ann. Phys.* **369** (3), 253-287, 1921. DOI:10.1002/andp.19213690304

> Darden, T., York, D. & Pedersen, L. "Particle mesh Ewald: An N*log(N) method for
> Ewald sums in large systems." *J. Chem. Phys.* **98** (12), 10089-10092, 1993.
> DOI:10.1063/1.464397

## License-file preservation

The build's provenance step (`build_release_manifest.py`) copies the license,
notice, copying and authors files recorded in every installed Python distribution's
metadata into the image, and lists the per-distribution file counts in
`/app/release-manifest.json`:

- `/app/licenses/<distribution>/` — one directory per distribution that ships such files
- `/app/THIRD_PARTY_NOTICES.md` — this file

Distributions that ship no license file in their metadata have no directory; consult
the sources listed above for those. OS package licenses remain under
`/usr/share/doc/` of the base image.

## Distribution model

This agent is distributed as source (Dockerfile, build inputs, agent YAML and
utilities); no container image or model weights are distributed with it. Whoever
builds and distributes the resulting container image assumes responsibility for
compliance with the licenses of the bundled components — in particular the NVIDIA
Deep Learning Container License that governs the CUDA base image.
