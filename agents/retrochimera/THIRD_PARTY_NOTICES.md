# Third-Party Notices

This container image includes the following third-party open-source components.

## Distribution model

This agent ships as source (Dockerfile + agent YAML + utilities). Consumers
build their own container images locally or via cloud build and push them to
their own registries. The consumer who builds and distributes the resulting
image is responsible for complying with all upstream licenses. The wrapper code
under /app/ remains under the MIT License regardless.

## Components

### RetroChimera

- **Version**: latest (PyPI)
- **License**: MIT
- **Source**: https://github.com/microsoft/retrochimera
- **Copyright**: Copyright (c) Microsoft Corporation
- **Attribution required**: Yes (MIT)

### Pistachio Checkpoint (model weights)

- **Version**: v1
- **License**: See upstream RetroChimera/Figshare release terms
- **Source**: https://figshare.com/ndownloader/files/59468882
- **Copyright**: Copyright (c) Microsoft Corporation
- **Notes**: Trained on the Pistachio reaction dataset. Weights are
  downloaded during the container build and unpacked under
  `/app/models/pistachio`.

### syntheseus

- **Version**: >=0.7.2
- **License**: MIT
- **Source**: https://github.com/microsoft/syntheseus
- **Copyright**: Copyright (c) Microsoft Corporation

### syntheseus-root-aligned

- **Version**: 0.2.0
- **License**: MIT
- **Source**: https://github.com/microsoft/syntheseus
- **Copyright**: Copyright (c) Microsoft Corporation

### PyTorch

- **Version**: 2.2.2
- **License**: BSD-3-Clause
- **Source**: https://github.com/pytorch/pytorch
- **Copyright**: Copyright (c) 2016- Facebook, Inc (Meta Platforms, Inc)

### PyG (torch_geometric)

- **Version**: 2.5.2
- **License**: MIT
- **Source**: https://github.com/pyg-team/pytorch_geometric
- **Copyright**: Copyright (c) 2021 Matthias Fey

### pytorch-sparse / pytorch-scatter / pytorch-cluster

- **License**: MIT
- **Source**: https://github.com/rusty1s/pytorch_sparse, pytorch_scatter, pytorch_cluster
- **Copyright**: Copyright (c) 2020 Matthias Fey

### RDKit

- **Version**: 2023.09.6
- **License**: BSD-3-Clause
- **Source**: https://github.com/rdkit/rdkit
- **Copyright**: Copyright (c) 2006-2024 Greg Landrum and other contributors

### rdchiral_cpp

- **License**: MIT
- **Source**: https://github.com/connorcoley/rdchiral
- **Copyright**: Copyright (c) Connor Coley

### NumPy

- **License**: BSD-3-Clause
- **Source**: https://github.com/numpy/numpy

### SciPy

- **License**: BSD-3-Clause
- **Source**: https://github.com/scipy/scipy

### pandas

- **License**: BSD-3-Clause
- **Source**: https://github.com/pandas-dev/pandas

### matplotlib

- **License**: PSF-based (matplotlib license)
- **Source**: https://github.com/matplotlib/matplotlib

### condaforge/mambaforge (base image)

- **License**: BSD-3-Clause
- **Source**: https://github.com/conda-forge/miniforge
