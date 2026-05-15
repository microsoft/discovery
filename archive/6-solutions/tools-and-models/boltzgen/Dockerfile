# =============================================================================
# BoltzGen — Protein Binder Design Pipeline (HannesStark/boltzgen)
# Diffusion-based design → inverse folding → folding → analysis → filtering
# Requires GPU (CUDA 12) for diffusion inference
#
# Multi-stage build:
#   Stage 1 (builder) — devel image: compile native extensions (cuequivariance)
#   Stage 2 (weights) — download model weights as non-root user
#   Stage 3 (final)   — runtime image: only Python packages + weights + runtime libs
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Build — compile everything in the devel image
# ---------------------------------------------------------------------------
FROM nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CUDA_HOME=/usr/local/cuda \
    PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu121

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        software-properties-common curl ca-certificates && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev python3.11-venv \
        build-essential git cmake pkg-config \
        libffi-dev libssl-dev libxml2-dev libxslt-dev \
        libhdf5-dev libboost-all-dev && \
    rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 && \
    python3.11 -m pip install --upgrade pip setuptools setuptools_scm wheel

# Install all Python packages (compiles cuequivariance native extensions)
RUN pip install --no-cache-dir boltzgen scipy seaborn pyyaml

# ---------------------------------------------------------------------------
# Stage 2: Download model weights as non-root (avoids chown layer duplication)
# ---------------------------------------------------------------------------
FROM builder AS weights

ARG DOWNLOAD_WEIGHTS=true

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser && \
    mkdir -p /cache && chown 1000:1000 /cache

USER appuser

RUN if [ "${DOWNLOAD_WEIGHTS}" = "true" ]; then \
        boltzgen download all --cache /cache --force_download; \
    fi

# ---------------------------------------------------------------------------
# Stage 3: Final — slim runtime image
# ---------------------------------------------------------------------------
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

# Optional: set HF_HUB_OFFLINE=1 to prevent any HuggingFace Hub network requests
# at runtime. All model weights are baked into /cache by stage 2, so online access
# is not required. Omit this to allow boltzgen to check for model updates or
# download additional assets on first run.
# Enable at build time:  --build-arg HF_HUB_OFFLINE=1
# Enable at run time:    -e HF_HUB_OFFLINE=1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/cache \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    KMP_AFFINITY=disabled \
    GOMP_CPU_AFFINITY=""

# Minimal runtime dependencies — install Python 3.11 via PPA, then purge PPA tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev \
        gcc libc6-dev \
        libffi8 libssl3 libxml2 libxslt1.1 \
        libhdf5-103-1 libgomp1 \
        libboost-system1.74.0 libboost-filesystem1.74.0 && \
    apt-get purge -y --auto-remove software-properties-common && \
    rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Copy pre-built Python packages from builder (no recompilation needed)
COPY --from=builder /usr/local/lib/python3.11/dist-packages /usr/local/lib/python3.11/dist-packages
COPY --from=builder /usr/lib/python3/dist-packages /usr/lib/python3/dist-packages

# Copy only the CLI scripts we need — not the entire /usr/local/bin
COPY --from=builder /usr/local/bin/boltzgen /usr/local/bin/boltzgen
COPY --from=builder /usr/local/bin/pip /usr/local/bin/pip
COPY --from=builder /usr/local/bin/pip3 /usr/local/bin/pip3
COPY --from=builder /usr/local/bin/pip3.11 /usr/local/bin/pip3.11

WORKDIR /app
COPY boltzgen_utils.py /app/
COPY test_boltzgen_utils.py /app/

# Create standard Discovery directories + non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser && \
    mkdir -p /input /output /workdir /tmp/boltzgen_scratch && \
    chmod 755 /input /output /workdir && \
    chown -R 1000:1000 /app /input /output /workdir /tmp/boltzgen_scratch

# Copy weights (already owned by 1000:1000 — no chown duplication)
COPY --from=weights --chown=1000:1000 /cache /cache

# Smoke test — verify critical imports resolve against runtime libs
RUN python3 -c "from rdkit import Chem; import torch; import boltzgen; import gemmi; from Bio import PDB; import numpy, pandas, scipy, sklearn, yaml; print('All imports OK')"

USER appuser

CMD ["/bin/bash"]
