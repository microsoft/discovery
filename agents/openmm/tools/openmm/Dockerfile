# OpenMM Agent Docker Image for Microsoft Discovery Platform
# GPU-accelerated molecular dynamics with Python API
#
# Includes: OpenMM (CUDA+CPU), MDTraj, ParmEd, PDBFixer, OpenMMForceFields, OpenMMTools
# NOTE: OpenMM CUDA platform plugin is only available via conda-forge, not pip.
#       The pip build is CPU-only. This image uses mambaforge + conda-forge to
#       ensure CUDA acceleration works on GPU nodepools.

FROM condaforge/mambaforge:latest

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# NVIDIA Container Runtime — expose GPU devices to the container.
# Without these, the NVIDIA device plugin will not mount GPU drivers
# even when the job runs on a GPU nodepool.
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Matplotlib headless mode
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib

# Thread control (default 1, scripts override at runtime)
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled
ENV GOMP_CPU_AFFINITY=""

# Layer 1: System update + TLS certificates
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    update-ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Layer 2: OpenMM with CUDA support + full simulation stack via conda-forge
# conda-forge openmm includes CUDA/OpenCL platform plugins; pip version is CPU-only.
# cudatoolkit provides the CUDA runtime libraries; host GPU drivers are mounted by
# the Discovery platform when the job is scheduled on a GPU nodepool.
RUN mamba install -y -c conda-forge \
    openmm \
    cudatoolkit \
    pdbfixer \
    mdtraj \
    parmed \
    openmmforcefields \
    openmmtools \
    numpy scipy pandas matplotlib-base seaborn requests \
    h5py biopython \
    && mamba clean -afy

# Layer 3: Create directories and copy utility library
RUN mkdir -p /workdir /input /output /tmp/openmm_scratch /tmp/matplotlib /app

COPY openmm_utils.py /app/openmm_utils.py

ENV PYTHONPATH="/app:${PYTHONPATH}"

WORKDIR /workdir

CMD ["/bin/bash"]
