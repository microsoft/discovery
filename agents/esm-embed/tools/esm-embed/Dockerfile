# ESM-2 Protein Embeddings Container for Microsoft Discovery Platform
# CUDA-enabled PyTorch base image so the 650M model runs efficiently on GPU.
# Falls back to CPU automatically when no GPU is present.
#
# Base: NVIDIA CUDA 12.1 runtime on Ubuntu 22.04 (matches PyTorch 2.3 cu121 wheels).

FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf-cache \
    TRANSFORMERS_CACHE=/opt/hf-cache \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TOKENIZERS_PARALLELISM=false

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 \
        python3-pip \
        python3-distutils \
        ca-certificates \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3

# Security: upgrade all packages picked up from the base image to their latest
# patched versions in the Ubuntu 22.04 archive. Specifically targets
# CVE-2025-68973 in gnupg* / dirmngr (12 HIGH CVEs flagged by Trivy 0.70.0).
RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    apt-get install -y --no-install-recommends --only-upgrade \
        gnupg gnupg2 gnupg-l10n gnupg-utils \
        gpg gpg-agent gpg-wks-client gpg-wks-server \
        gpgconf gpgsm gpgv dirmngr && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/workdir /input /output /opt/hf-cache

RUN pip3 install --upgrade pip setuptools wheel
RUN pip3 install --index-url https://download.pytorch.org/whl/cu121 \
        torch==2.3.1 \
        torchvision==0.18.1

RUN pip3 install \
        numpy>=1.26.0 \
        scipy>=1.11.0 \
        pandas>=2.0.0 \
        matplotlib>=3.7.0 \
        tqdm>=4.66.0 \
        PyYAML>=6.0 \
        requests>=2.32.0

RUN pip3 install \
        biopython>=1.83 \
        transformers==4.43.3 \
        tokenizers>=0.19.1 \
        huggingface_hub>=0.24.0 \
        safetensors>=0.4.3 \
        accelerate>=0.31.0 \
        sentencepiece>=0.2.0

# Pre-download all four ESM-2 checkpoints at build time so first job is fast.
# Cached under HF_HOME (/opt/hf-cache). ~3.2 GB total weights on disk.
RUN python3 -c "from transformers import AutoTokenizer, AutoModel; \
    [ (AutoTokenizer.from_pretrained(m), AutoModel.from_pretrained(m)) \
      for m in ['facebook/esm2_t6_8M_UR50D', \
                'facebook/esm2_t12_35M_UR50D', \
                'facebook/esm2_t30_150M_UR50D', \
                'facebook/esm2_t33_650M_UR50D'] ]; \
    print('All ESM-2 checkpoints pre-cached.')"

# CVE pins
RUN pip3 install \
        cryptography>=43.0.1 \
        urllib3>=2.2.2 \
        certifi>=2024.7.4 \
        idna>=3.7 \
        pillow>=10.4.0

WORKDIR /app
COPY esm_utils.py /app/esm_utils.py
ENV PYTHONPATH="/app"

RUN PYTHON_SITE=$(python3 -c "import site; print(site.getsitepackages()[0])") \
    && ln -sf /app/esm_utils.py "${PYTHON_SITE}/esm_utils.py" 2>/dev/null || true

WORKDIR /app/workdir
CMD ["/bin/bash"]

LABEL maintainer="Microsoft Discovery Platform"
LABEL description="ESM-2 protein embedding container (PyTorch + CUDA + transformers)"
LABEL version="1.0.0"
LABEL esm.models="8M,35M,150M,650M"
LABEL base.image="nvidia/cuda:12.1.1-runtime-ubuntu22.04"
