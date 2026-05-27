# ============================================================================
# Psi4 Quantum Chemistry Docker Image for Discovery Platform
# ============================================================================
# Psi4 is an open-source ab initio quantum chemistry package supporting:
# - Hartree-Fock, DFT, MP2, CCSD, CCSD(T)
# - SAPT for intermolecular interactions
# - Excited states (EOM-CCSD, TD-DFT)
# - Geometry optimization and frequency calculations
# ============================================================================

FROM mambaorg/micromamba:1.5-jammy AS builder

LABEL maintainer="Discovery Platform"
LABEL description="Psi4 quantum chemistry for Discovery Platform"

# Switch to root for installation
USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV MAMBA_ROOT_PREFIX=/opt/conda
ENV PATH="${MAMBA_ROOT_PREFIX}/bin:${PATH}"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create conda environment with Psi4 and commonly needed extensions
# Using psi4 from conda-forge (most reliable installation method)
RUN micromamba create -n psi4env -c conda-forge -c psi4 -y \
    python=3.11 \
    psi4 \
    dftd3-python \
    dftd4-python \
    gcp-correction \
    numpy \
    scipy \
    matplotlib \
    pandas \
    h5py \
    && micromamba clean -afy

# Install less commonly used but useful Psi4 extensions
# These are in a separate step for better layer caching
# - pcmsolver: Implicit solvation (PCM)
# - cppe: Polarizable embedding
# - adcc: ADC methods for excited states
# - chemps2: DMRG calculations for strong correlation
RUN micromamba install -n psi4env -c conda-forge -c psi4 -y \
    pcmsolver \
    cppe \
    adcc \
    chemps2 \
    || echo "Some optional packages may not be available for this platform"

# Activate environment for subsequent commands
ARG MAMBA_DOCKERFILE_ACTIVATE=1
ENV ENV_NAME=psi4env

# ============================================================================
# Runtime Stage
# ============================================================================
FROM mambaorg/micromamba:1.5-jammy AS runtime

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV MAMBA_ROOT_PREFIX=/opt/conda
ENV PATH="${MAMBA_ROOT_PREFIX}/envs/psi4env/bin:${MAMBA_ROOT_PREFIX}/bin:${PATH}"
ENV CONDA_DEFAULT_ENV=psi4env

# Install runtime system dependencies and apply security updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libgomp1 \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# Copy conda environment from builder
COPY --from=builder ${MAMBA_ROOT_PREFIX}/envs/psi4env ${MAMBA_ROOT_PREFIX}/envs/psi4env

# Install additional Python packages
# Note: Using pip in the conda environment
RUN ${MAMBA_ROOT_PREFIX}/envs/psi4env/bin/pip install --no-cache-dir \
    rdkit \
    ase \
    azure-storage-blob \
    azure-identity \
    "cryptography>=46.0.5" \
    "pillow>=12.1.1" \
    || true

# Set Psi4 environment variables
ENV PSI_SCRATCH=/tmp/psi4_scratch
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
# Disable OpenMP CPU affinity - improves compatibility in containerized/virtualized environments
ENV KMP_AFFINITY=disabled

# Copy utilities library
COPY psi4_utils.py /usr/local/lib/psi4_utils.py

# Install to Python site-packages
RUN cp /usr/local/lib/psi4_utils.py ${MAMBA_ROOT_PREFIX}/envs/psi4env/lib/python3.11/site-packages/

# Create workspace directories
RUN mkdir -p /app/workdir /input /output /tmp/psi4_scratch

WORKDIR /app/workdir

# Verify installation
RUN ${MAMBA_ROOT_PREFIX}/envs/psi4env/bin/python -c "import psi4; print(f'Psi4 version: {psi4.__version__}')"
RUN ${MAMBA_ROOT_PREFIX}/envs/psi4env/bin/python -c "from psi4_utils import quick_setup; print('psi4_utils OK')"

# Set default shell to use conda environment
SHELL ["/bin/bash", "-c"]

# Scripts are executed via docker exec with the full Python path
CMD ["/bin/bash"]
