# ============================================================================
# AmberTools Docker Image for Discovery Platform
# ============================================================================
# AmberTools is a free suite of programs for biomolecular simulation:
# - sander: Molecular dynamics engine
# - tleap: System preparation (topology, solvation, ions)
# - cpptraj: Trajectory analysis (RMSD, RMSF, H-bonds, etc.)
# - antechamber: Small molecule parameterization (AM1-BCC charges)
# - parmchk2: Missing parameter detection
# - pdb4amber: PDB file cleanup
# - parmed/pytraj: Python interfaces
# ============================================================================

FROM condaforge/mambaforge:latest AS builder

LABEL maintainer="Discovery Platform"
LABEL description="AmberTools for biomolecular simulations on Discovery Platform"

# Apply security patches and install build dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create conda environment with AmberTools
# AmberTools from conda-forge includes: sander, tleap, cpptraj, antechamber,
# parmchk2, pdb4amber, reduce, parmed, pytraj
RUN mamba create -n amberenv -c conda-forge -y \
    python=3.11 \
    ambertools \
    openmpi \
    numpy \
    scipy \
    matplotlib \
    pandas \
    h5py \
    && mamba clean -afy

# Install additional Python packages via pip into the conda env
RUN /opt/conda/envs/amberenv/bin/pip install --no-cache-dir \
    mdanalysis \
    ase \
    networkx

# ============================================================================
# Runtime Stage
# ============================================================================
FROM condaforge/mambaforge:latest AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/opt/conda/envs/amberenv/bin:/opt/conda/bin:${PATH}"
ENV CONDA_DEFAULT_ENV=amberenv

# Apply all available security patches and install runtime dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy conda environment from builder
COPY --from=builder /opt/conda/envs/amberenv /opt/conda/envs/amberenv

# Set AmberTools environment variables
ENV AMBERHOME=/opt/conda/envs/amberenv
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib

# Thread control defaults — let scripts override at runtime
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled
ENV GOMP_CPU_AFFINITY=""

# Copy utilities library
COPY ambertools_utils.py /usr/local/lib/ambertools_utils.py

# Install to Python site-packages for easy importing
RUN cp /usr/local/lib/ambertools_utils.py \
    /opt/conda/envs/amberenv/lib/python3.11/site-packages/

# Copy test file for container testing
COPY test_ambertools_utils.py /app/test_ambertools_utils.py

# Create workspace directories
RUN mkdir -p /app/workdir /input /output /tmp/ambertools_scratch /tmp/matplotlib

WORKDIR /app/workdir

# Verify installation
RUN /opt/conda/envs/amberenv/bin/python -c \
    "import pytraj; import parmed; print(f'pytraj {pytraj.__version__}, parmed OK')"
RUN /opt/conda/envs/amberenv/bin/python -c \
    "from ambertools_utils import quick_setup; print('ambertools_utils OK')"
RUN which sander && which tleap && which cpptraj && which antechamber && echo "All executables found"

# Set default shell
SHELL ["/bin/bash", "-c"]

# CRITICAL: Must use CMD, NOT ENTRYPOINT
# The workbench starts containers with command='sleep infinity'
CMD ["/bin/bash"]
