# =============================================================================
# Boltz-2 -- Biomolecular Structure Prediction & Binding Affinity
# Single-stage build using system Python 3.10 (from CUDA Ubuntu 22.04)
# Weights downloaded at first prediction run (cached via HF_HOME=/cache)
# =============================================================================

FROM nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    HF_HOME=/cache \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    KMP_AFFINITY=disabled \
    GOMP_CPU_AFFINITY=""

# System deps using system Python 3.10 (no PPA needed)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-dev python3-pip python3-venv \
        curl ca-certificates \
        build-essential git cmake pkg-config \
        libffi-dev libssl-dev libxml2-dev libxslt-dev \
        libhdf5-dev && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip setuptools wheel

# Install PyTorch with CUDA 12.1 support
RUN pip3 install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cu121

# Install boltz (pulls its own pinned scipy==1.13.1, rdkit, etc.)
RUN pip3 install --no-cache-dir boltz

# Install cuequivariance kernels required for GPU inference (triangular mult)
RUN pip3 install --no-cache-dir cuequivariance-torch cuequivariance-ops-torch-cu12

# Install additional scientific packages (compatible with boltz's deps)
RUN pip3 install --no-cache-dir \
    seaborn \
    biopython \
    pandas \
    matplotlib

# Remove heavyweight build tools but KEEP a minimal C compiler.
# Triton's runtime JIT path (used by cuequivariance fused LayerNorm kernels
# during boltz inference on realistically sized inputs) requires `cc` at
# runtime to compile CUDA driver-utility shims; without it boltz crashes
# with "Failed to find C compiler. Please specify via CC environment variable."
# the moment a fused-LayerNorm kernel is JIT-compiled. Keeping gcc + libc6-dev
# adds ~50 MB but is mandatory for any non-trivial prediction.
RUN apt-get purge -y --auto-remove build-essential git cmake && \
    apt-get update && \
    apt-get install -y --no-install-recommends gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

ENV CC=gcc

WORKDIR /app
COPY boltztwo_utils.py /app/
COPY test_boltztwo_utils.py /app/

# Create standard Discovery directories and non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser && \
    mkdir -p /input /output /workdir /cache /tmp/boltz_scratch /tmp/matplotlib && \
    chmod 777 /input /output /workdir /cache /tmp/boltz_scratch /tmp/matplotlib && \
    chown -R 1000:1000 /app /input /output /workdir /cache

# Smoke test
RUN python3 -c "import boltz; import torch; import numpy, pandas, scipy, yaml, matplotlib; print('All imports OK')"

USER appuser

CMD ["/bin/bash"]
