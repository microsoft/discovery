# Third-Party Notices

This Discovery agent container embeds the following third-party open-source
components. Their licenses are preserved inside the container image at the
paths noted below.

## MatterGen

- **Version**: 1.0.3
- **License**: MIT
- **Source**: https://github.com/microsoft/mattergen
- **Paper**: Zeni et al., "MatterGen: a generative model for inorganic materials
  design", Nature (2025). DOI:10.1038/s41586-025-08628-5
- **Container path**: `/app/mattergen-src/licenses/LICENSE`
- **NOTICE file**: `/app/mattergen-src/licenses/NOTICE`

The upstream NOTICE file contains a comprehensive list of all transitive
dependencies of MatterGen and their respective licenses.

## MatterGen Model Weights

- **Version**: 1.0.3
- **License**: MIT
- **Source**: https://huggingface.co/microsoft/mattergen
- **Models**: mattergen_base, mp_20_base, chemical_system, space_group,
  dft_band_gap, dft_mag_density, ml_bulk_modulus,
  chemical_system_energy_above_hull, dft_mag_density_hhi_score

Model weights are downloaded from HuggingFace Hub at container build time
and cached in the HuggingFace cache directory inside the image.

## PyTorch

- **Version**: 2.2.1+cu118
- **License**: BSD-3-Clause
- **Source**: https://github.com/pytorch/pytorch

## PyTorch Geometric

- **Version**: 2.5+
- **License**: MIT
- **Source**: https://github.com/pyg-team/pytorch_geometric

Includes extensions: torch_scatter, torch_sparse, torch_cluster.

## pymatgen

- **Version**: 2024.6+
- **License**: MIT
- **Source**: https://github.com/materialsproject/pymatgen

## ASE (Atomic Simulation Environment)

- **Version**: 3.25
- **License**: LGPL-2.1-only
- **Source**: https://wiki.fysik.dtu.dk/ase/

ASE is imported as a Python library (dynamic linking). The LGPL-2.1 license
permits use as a library without imposing copyleft on the wrapper code.

## MatterSim

- **Version**: 1.1+
- **License**: MIT
- **Source**: https://github.com/microsoft/mattersim

## Distribution Model

This agent is distributed as source code (Dockerfile + agent YAML + utilities).
The consumer who builds and distributes the resulting container image assumes
responsibility for compliance with the licenses of bundled components. All
bundled components use permissive licenses (MIT, BSD-3-Clause) except ASE
(LGPL-2.1), which is used as a dynamically-linked library. The wrapper code
is licensed under MIT.
