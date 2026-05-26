
# ============================================================================
# Stage 1: Builder - Build GROMACS with CUDA support
# ============================================================================
FROM nvidia/cuda:12.6.3-devel-ubuntu22.04 AS builder

# GROMACS with GPU support - automatically falls back to CPU when no GPU present
# Compatible with NVIDIA A100 (SM 8.0) and H100 (SM 9.0) GPUs, and CPU-only environments

ENV DEBIAN_FRONTEND=noninteractive
ENV APPS=/opt/apps
ARG MAKE_JOBS=8
ARG CUDA_TARGET_SM="80;90"
ARG BUILD_PACKAGES="ca-certificates build-essential gfortran cmake git wget tar"

# Install only build-time dependencies
RUN apt-get update && apt-get install -y --no-install-recommends $BUILD_PACKAGES && rm -rf /var/lib/apt/lists/*

# Create build directories
RUN mkdir -p ${APPS} /opt/src
WORKDIR /opt/src

# GROMACS build settings
ENV GMX_VERSION=2024.4
ENV GMX_PREFIX=${APPS}/gmx/${GMX_VERSION}
ENV GMX_BINARY_SUFFIX=""

# Download and build GROMACS with GPU support (auto-falls back to CPU)
# Note: GROMACS builds FFTW internally with optimal compiler flags
RUN set -eux; \
		wget -q https://ftp.gromacs.org/pub/gromacs/gromacs-${GMX_VERSION}.tar.gz -O gromacs.tar.gz; \
		mkdir -p gromacs-src; \
		tar -xzf gromacs.tar.gz -C gromacs-src --strip-components=1; \
		rm -f gromacs.tar.gz; \
		mkdir -p gromacs-src/build; \
		cd gromacs-src/build; \
		cmake .. \
			-DCMAKE_INSTALL_PREFIX=${GMX_PREFIX} \
			-DGMX_GPU=CUDA \
			-DGMX_CUDA_TARGET_SM=${CUDA_TARGET_SM} \
			-DGMX_GPU_PME=ON \
			-DGMX_SIMD=AVX2_256 \
			-DGMX_OPENMP=ON \
			-DGMX_MPI=OFF \
			-DGMX_X11=OFF \
			-DGMX_DEFAULT_SUFFIX=OFF \
			-DGMX_BINARY_SUFFIX=${GMX_BINARY_SUFFIX} \
			-DGMX_BUILD_OWN_FFTW=ON \
			-DGMX_NVCC_WORKS=ON \
			-DCMAKE_BUILD_TYPE=Release; \
		make -j${MAKE_JOBS}; \
		make install; \
		cd /opt/src; \
		rm -rf gromacs-src

# Download amber14sb_parmbsc1 force field (GROMACS-compatible ff14SB port)
# Source: https://github.com/intbio/gromacs_ff (trusted academic repo)
# Provides amber14sb with parmbsc1 DNA corrections (superset, works for protein-only too)
RUN git clone --depth 1 https://github.com/intbio/gromacs_ff.git /opt/src/gromacs_ff

# ============================================================================
# Stage 2: Runtime - Minimal image with only runtime dependencies
# ============================================================================
FROM nvidia/cuda:12.6.3-devel-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV APPS=/opt/apps
ENV GMX_VERSION=2024.4
ENV GMX_PREFIX=${APPS}/gmx/${GMX_VERSION}

# Install only runtime dependencies
ARG RUNTIME_PACKAGES="ca-certificates python3 python3-pip libgomp1 openbabel bc"
RUN apt-get update && \
    apt-get install -y --no-install-recommends $RUNTIME_PACKAGES && \
    rm -rf /var/lib/apt/lists/*

# Scientific Python stack for trajectory analysis
# Fix: Ubuntu 22.04 pip does not support --break-system-packages; upgrade pip first
# numpy/scipy: array math, FFT, curve fitting, statistical analysis
# pandas: tabular data for energy/RMSD time series
# matplotlib: publication-quality plots of MD observables
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir \
    numpy scipy pandas matplotlib \
    "pillow>=12.1.1"

# Copy GROMACS installation from builder stage
COPY --from=builder ${GMX_PREFIX} ${GMX_PREFIX}

# Install amber14sb_parmbsc1 force field from builder
# Copy as amber14sb_parmbsc1.ff AND as amber14sb.ff (real copy, not symlink)
# Avoids Docker overlayfs symlink issues that break GROMACS opendir()
COPY --from=builder /opt/src/gromacs_ff/amber14sb_parmbsc1.ff ${GMX_PREFIX}/share/gromacs/top/amber14sb_parmbsc1.ff
COPY --from=builder /opt/src/gromacs_ff/amber14sb_parmbsc1.ff ${GMX_PREFIX}/share/gromacs/top/amber14sb.ff
# Rename the display name inside amber14sb.ff so pdb2gmx shows "AMBER14sb"
RUN sed -i 's/Amber14sb_parmbsc1/Amber14sb/g' ${GMX_PREFIX}/share/gromacs/top/amber14sb.ff/forcefield.doc 2>/dev/null || true

# Set up runtime environment
ENV PATH="${GMX_PREFIX}/bin:${PATH}"
ENV LD_LIBRARY_PATH="${GMX_PREFIX}/lib:${LD_LIBRARY_PATH}"

# Install the GROMACS utilities library (importable as `gromacs_utils`).
# Encodes the POSRES/MDP-dep rules, MPI fallback + SETTLE recovery, analysis
# group selections, and final_results.json schema so the agent does not have
# to re-derive them from prose on every run.
RUN mkdir -p /opt/gromacs_utils
COPY gromacs_utils.py /opt/gromacs_utils/gromacs_utils.py
ENV PYTHONPATH="/opt/gromacs_utils:${PYTHONPATH}"

# Create workspace
RUN mkdir -p /app/workdir /input /output
WORKDIR /app/workdir

CMD ["/bin/bash"]
