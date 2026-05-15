# ============================================================================
# Stage 1: Builder - Build Quantum ESPRESSO
# ============================================================================
FROM ubuntu:22.04 AS builder

LABEL maintainer="Discovery Platform"
LABEL description="Versatile Quantum ESPRESSO 7.3 build for AKS/HPC"

# Quantum ESPRESSO - CPU-only build using gfortran + MPI
# Note: GPU-accelerated QE requires NVIDIA HPC SDK (nvfortran >= 21.7)
# which adds ~10GB to image size. CPU builds work well for most calculations.

ENV DEBIAN_FRONTEND=noninteractive
ENV APPS=/opt/apps
ARG MAKE_JOBS=8

# Install build-time dependencies
# Uses OpenBLAS/ScaLAPACK for universality across Intel and AMD nodes
ARG BUILD_PACKAGES="ca-certificates build-essential gfortran cmake git wget tar \
    libfftw3-dev libopenblas-dev liblapack-dev libscalapack-mpi-dev \
    libhdf5-dev libhdf5-mpi-dev openmpi-bin libopenmpi-dev"

RUN apt-get update && apt-get install -y --no-install-recommends $BUILD_PACKAGES && rm -rf /var/lib/apt/lists/*

RUN mkdir -p ${APPS} /opt/src
WORKDIR /opt/src

ENV QE_VERSION=7.3
ENV QE_PREFIX=${APPS}/qe/${QE_VERSION}

# =========================================================================
# PERFORMANCE OPTIMIZATION GUIDE
# -------------------------------------------------------------------------
# Default: -mavx2 (Works on almost all Azure, AWS, and GCP HPC nodes)
#
# To optimize for specific Azure HB-series:
# HBv1 (EPYC 7001):   Use -march=znver1
# HBv2 (EPYC 7002):   Use -march=znver2
# HBv3 (EPYC 7003):   Use -march=znver3
# HBv4/Genoa:         Use -march=znver4
# HC (Intel Xeon):    Use -march=skylake-avx512
# =========================================================================
ARG OPT_FLAGS="-O3 -mavx2 -mfma"

# Download and build Quantum ESPRESSO
# NOTE: QE 7.x is hosted on GitLab, not GitHub
RUN set -eux; \
    wget -q https://gitlab.com/QEF/q-e/-/archive/qe-${QE_VERSION}/q-e-qe-${QE_VERSION}.tar.gz -O qe.tar.gz; \
    mkdir -p qe-src; \
    tar -xzf qe.tar.gz -C qe-src --strip-components=1; \
    rm -f qe.tar.gz; \
    cd qe-src; \
    mkdir build && cd build; \
    # Find scalapack library path (works for both arm64 and amd64)
    SCALAPACK_LIB=$(find /usr/lib -name "libscalapack-openmpi*.so*" -type f 2>/dev/null | head -1); \
    cmake .. \
        -DCMAKE_INSTALL_PREFIX=${QE_PREFIX} \
        -DCMAKE_Fortran_COMPILER=mpif90 \
        -DCMAKE_C_COMPILER=mpicc \
        -DQE_ENABLE_MPI=ON \
        -DQE_ENABLE_OPENMP=ON \
        -DQE_ENABLE_SCALAPACK=ON \
        -DSCALAPACK_LIBRARIES="${SCALAPACK_LIB}" \
        -DQE_ENABLE_HDF5=ON \
        -DCMAKE_Fortran_FLAGS="${OPT_FLAGS}" \
        -DCMAKE_C_FLAGS="${OPT_FLAGS}" \
        -DCMAKE_BUILD_TYPE=Release; \
    make -j${MAKE_JOBS}; \
    make install; \
    cd /opt/src; \
    rm -rf qe-src

# Download standard pseudopotential library (SSSP Efficiency v1.3.0)
# Source: https://archive.materialscloud.org/record/2023.65 (record ID: rcyfm-68h65)
# Coverage: All elements H-Bi plus At, Fr, Ra (~90 pseudopotentials)
# Mixed library: PSLibrary (e.g., Si.pbe-n-rrkjus_psl.1.0.0.UPF) and GBRV styles
RUN mkdir -p ${QE_PREFIX}/pseudo && \
    cd ${QE_PREFIX}/pseudo && \
    # Try multiple URL formats (Materials Cloud has changed URLs over time)
    (wget --no-check-certificate -q "https://archive.materialscloud.org/records/rcyfm-68h65/files/SSSP_1.3.0_PBE_efficiency.tar.gz?download=1" -O sssp.tar.gz || \
     wget --no-check-certificate -q "https://archive.materialscloud.org/api/records/rcyfm-68h65/files/SSSP_1.3.0_PBE_efficiency.tar.gz/content" -O sssp.tar.gz) && \
    tar -xzf sssp.tar.gz && \
    # Handle case where tarball extracts to a subdirectory
    find . -name "*.UPF" -exec mv {} . \; 2>/dev/null || true && \
    find . -type d -empty -delete 2>/dev/null || true && \
    rm -f sssp.tar.gz *.json *.md 2>/dev/null || true && \
    echo "SSSP Efficiency v1.3.0 installed: $(ls -1 *.UPF 2>/dev/null | wc -l) pseudopotentials" && \
    ls *.UPF 2>/dev/null | head -5 && echo "..." && \
    # Verify critical pseudopotentials exist
    test -f Si.pbe-n-rrkjus_psl.1.0.0.UPF || echo "WARNING: Silicon pseudopotential not found!"

# ============================================================================
# Stage 2: Runtime - Minimal image with only runtime dependencies
# ============================================================================
FROM ubuntu:22.04 AS runtime

ENV APPS=/opt/apps
ENV QE_VERSION=7.3
ENV QE_PREFIX=${APPS}/qe/${QE_VERSION}
ENV PATH="${QE_PREFIX}/bin:${PATH}"
ENV ESPRESSO_PSEUDO="${QE_PREFIX}/pseudo"
ENV PSEUDO_DIR="${QE_PREFIX}/pseudo"

# Install only runtime dependencies and apply security updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates python3 python3-pip \
    libfftw3-3 libopenblas0 liblapack3 libscalapack-openmpi2.1 \
    libhdf5-openmpi-103-1 libhdf5-openmpi-fortran-102 \
    openmpi-bin libopenmpi3 libgomp1 && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*

# Scientific Python stack for self-sufficient computational chemistry workflows
# Core: numpy, scipy, matplotlib, ase (structure manipulation)
# Materials: pymatgen (structure generation, file I/O), spglib (symmetry)
# Phonons: phonopy (phonon calculations post-processing)
# Band structure: seekpath (automatic high-symmetry k-paths)
# Data: pandas, h5py (HDF5 support for large QE outputs)
# Cloud: azure-storage-blob, azure-identity
# Note: Using -q and --progress-bar off to avoid Unicode issues in Azure CLI log streaming
RUN pip3 install -q --no-cache-dir --progress-bar off \
    numpy scipy matplotlib ase \
    pymatgen spglib phonopy seekpath \
    pandas h5py \
    azure-storage-blob azure-identity \
    "cryptography>=46.0.5" "pillow>=12.1.1" || true

# Copy Quantum ESPRESSO installation from builder stage
COPY --from=builder ${QE_PREFIX} ${QE_PREFIX}

# QE utilities library (lightweight, may change frequently)
COPY qe_utils.py /usr/local/lib/qe_utils.py
# Install to Python site-packages
RUN cp /usr/local/lib/qe_utils.py /usr/lib/python3/dist-packages/ 2>/dev/null || \
    cp /usr/local/lib/qe_utils.py $(python3 -c "import site; print(site.getsitepackages()[0])")/

# =============================================================================
# MPI NETWORKING CONFIGURATION
# -----------------------------------------------------------------------------
# Current setup: Single-node operation over TCP/ethernet (no Infiniband)
#
# This configuration ensures reliable MPI operation in containerized AKS
# environments on standard VM types (D-series, NC-series without IB).
#
# To enable Infiniband auto-detection (for HB-series VMs):
#   1. Comment out OMPI_MCA_btl_tcp_if_include=eth0
#   2. Optionally add: ENV OMPI_MCA_btl=self,vader,openib,tcp
#   3. Rebuild image and update tool definition with infiniband: true
#
# See README.md "Networking and Infiniband" section for details.
# =============================================================================

# Allow MPI to run as root (necessary for container runtimes)
ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1

# Disable Vader shared memory single-copy mechanism (container compatibility)
ENV OMPI_MCA_btl_vader_single_copy_mechanism=none

# Force MPI to use TCP over eth0 (works on all node types without IB drivers)
# Comment out this line to enable Infiniband auto-detection on HB-series VMs
ENV OMPI_MCA_btl_tcp_if_include=eth0

# Create workspace
RUN mkdir -p /app/workdir /input /output
WORKDIR /app/workdir

# Verify build (pw.x doesn't have --version flag, just check it's in PATH)
RUN which pw.x && echo "Quantum ESPRESSO pw.x found in PATH"

CMD ["/bin/bash"]
