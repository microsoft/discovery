# DISTRIBUTION NOTE: This Dockerfile installs MIT-licensed software (RetroChimera,
# PyTorch, RDKit, syntheseus). The party that builds and distributes the resulting
# image is responsible for complying with the licenses of all bundled components.
# The wrapper code under /app/ is MIT. See ../THIRD_PARTY_NOTICES.md.

# RetroChimera requires conda for PyTorch + PyG + rdchiral_cpp
# Pinned to a specific mambaforge release for reproducibility (avoid :latest).
FROM condaforge/mambaforge:24.3.0-0

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV HDF5_USE_FILE_LOCKING=FALSE

# Create conda environment with RetroChimera's heavy dependencies
# Pin Python 3.9 as required by retrochimera's environment.yml
RUN mamba create -n retrochimera python=3.9 -y && \
    mamba clean -afy

# Install conda-only dependencies (PyTorch ecosystem + RDKit + rdchiral)
RUN mamba install -n retrochimera -c pytorch -c nvidia -c pyg -c conda-forge \
    numpy \
    pandas \
    "scipy<1.12" \
    "rdkit=2023.09.6" \
    rdchiral_cpp \
    "pytorch=2.2.2" \
    "pytorch-lightning=2.2.2" \
    "pytorch-sparse=0.6.18" \
    "pytorch-cluster=1.6.3" \
    "pytorch-scatter=2.1.2" \
    "torchvision=0.17.2" \
    "pyg=2.5.2" \
    "torchmetrics<0.11.0" \
    matplotlib \
    requests \
    -y && \
    mamba clean -afy

# Download Pistachio checkpoint (~4.2 GB) from Figshare before switching
# to the conda SHELL. The download script handles 302 redirects.
# Override CHECKPOINT_URL if the default Figshare file ID is stale.
# NOTE: use ndownloader.figshare.com (302→S3), not figshare.com/ndownloader (WAF).
ARG CHECKPOINT_URL="https://ndownloader.figshare.com/files/59468882"
COPY download_checkpoint.py /tmp/download_checkpoint.py
RUN CHECKPOINT_URL="${CHECKPOINT_URL}" python /tmp/download_checkpoint.py && rm /tmp/download_checkpoint.py
# Now activate the conda env for remaining RUN commands
SHELL ["mamba", "run", "-n", "retrochimera", "/bin/bash", "-c"]

# Install retrochimera from PyPI. Version is pinned for reproducibility;
# override via --build-arg RETROCHIMERA_VERSION=<x.y.z> to update.
ARG RETROCHIMERA_VERSION="1.1.0"
ARG SEABORN_VERSION="0.13.2"
RUN pip install --no-cache-dir "retrochimera==$RETROCHIMERA_VERSION" "seaborn==$SEABORN_VERSION"

# Install syntheseus visualization extras (requires graphviz system binary).
# Version is pinned; override via --build-arg SYNTHESEUS_VERSION=<x.y.z>.
ARG SYNTHESEUS_VERSION="0.7.2"
RUN mamba install -n retrochimera -c conda-forge graphviz -y && \
    mamba clean -afy && \
    pip install --no-cache-dir "syntheseus[viz]==$SYNTHESEUS_VERSION"

RUN mkdir -p /app/retrochimera-license && \
    python -c "import retrochimera,os,shutil; pkg=os.path.dirname(os.path.dirname(retrochimera.__file__)); [shutil.copy(os.path.join(pkg,d,'LICENSE'),'/app/retrochimera-license/LICENSE') for d in os.listdir(pkg) if 'retrochimera' in d.lower() and os.path.isdir(os.path.join(pkg,d)) and os.path.exists(os.path.join(pkg,d,'LICENSE'))]" || \
    python -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/microsoft/retrochimera/main/LICENSE','/app/retrochimera-license/LICENSE')" && \
    cat /app/retrochimera-license/LICENSE | head -1

# Copy utilities
COPY retrochimera_utils.py /app/
COPY test_retrochimera_utils.py /app/
RUN mkdir -p /app/data
COPY building_blocks.smi /app/data/building_blocks.smi

# Download and canonicalize eMolecules building blocks (overwrites the small
# bundled fallback on success; keeps it on failure so the build doesn't break).
# Override BUILDING_BLOCKS_URL at build time if the default URL expires.
ARG BUILDING_BLOCKS_URL="https://downloads.emolecules.com/orderbb/2026-04-01/parent.smi.gz"
COPY prepare_building_blocks.py /tmp/prepare_building_blocks.py
RUN python /tmp/prepare_building_blocks.py --url "$BUILDING_BLOCKS_URL" && \
    rm /tmp/prepare_building_blocks.py

# Create working directories
RUN mkdir -p /workdir /input /output /tmp/retrochimera_scratch /tmp/matplotlib

# Activation wrapper: ensure conda env is active when bash starts
RUN echo "conda activate retrochimera" >> ~/.bashrc
ENV PATH=/opt/conda/envs/retrochimera/bin:$PATH

WORKDIR /workdir

CMD ["/bin/bash"]
