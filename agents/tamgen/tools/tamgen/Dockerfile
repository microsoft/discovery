# TamGen Container for Microsoft Discovery Platform
# Target-aware Molecule Generation for Drug Design
# Requires CUDA GPU for inference
#
# Base: Official PyTorch 2.3.0 + CUDA 12.1 + cuDNN 8
# Model: Wu et al., Nature Communications 15:9360 (2024)

FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_PROGRESS_BAR=off

# ── System dependencies ────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget curl git gcc g++ make unzip \
        ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ── PyTorch Geometric (step 1: core) ──────────────────────────────────────
RUN pip install --no-cache-dir -q torch_geometric scipy \
    && echo "=== torch_geometric installed ==="

# ── PyTorch Geometric (step 2: extensions with pinned versions) ───────────
# Use --no-index to force pre-built wheels only (no source compilation)
RUN pip install --no-cache-dir -q --no-index \
        pyg_lib==0.4.0 \
        torch_scatter==2.1.2 \
        torch_sparse==0.6.18 \
        torch_cluster==1.6.3 \
        torch_spline_conv==1.2.2 \
        -f https://data.pyg.org/whl/torch-2.3.0+cu121.html \
    && echo "=== PyG extensions installed ==="

# ── Scientific Python stack ────────────────────────────────────────────────
RUN pip install --no-cache-dir -q \
        rdkit==2024.03.1 \
        numpy==1.26.4 pandas matplotlib seaborn \
        biopython requests tqdm \
        tensorboardX einops \
    && echo "=== Scientific stack installed ==="

# ── Clone & install TamGen (fairseq fork) ──────────────────────────────────
WORKDIR /app
RUN git clone --depth 1 https://github.com/microsoft/TamGen.git \
    && echo "=== TamGen cloned ==="

WORKDIR /app/TamGen
RUN pip install --no-cache-dir -q -e ".[chem]" \
    && echo "=== TamGen/fairseq installed ==="

# ── Download model weights from Zenodo (record 13751391) ──────────────────
# FIX: Use -o flag to overwrite existing files without prompting
RUN wget -q "https://zenodo.org/records/13751391/files/checkpoints.zip" \
        -O /tmp/checkpoints.zip \
    && unzip -o -q /tmp/checkpoints.zip -d /app/TamGen/ \
    && rm /tmp/checkpoints.zip \
    && echo "=== Checkpoints downloaded ==="

RUN wget -q "https://zenodo.org/records/13751391/files/gpt_model.zip" \
        -O /tmp/gpt_model.zip \
    && unzip -o -q /tmp/gpt_model.zip -d /app/TamGen/ \
    && rm /tmp/gpt_model.zip \
    && echo "=== GPT model downloaded ==="

# ── Shrink: remove build tools ─────────────────────────────────────────────
RUN apt-get purge -y gcc g++ make && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* || true

# ── Working directories ───────────────────────────────────────────────────
RUN mkdir -p /app/workdir /input /output

# ── Copy utilities ─────────────────────────────────────────────────────────
COPY tamgen_utils.py /app/tamgen_utils.py
COPY test_tamgen_utils.py /app/test_tamgen_utils.py

ENV PYTHONPATH="/app:/app/TamGen" \
    TAMGEN_ROOT="/app/TamGen"

WORKDIR /app/workdir
CMD ["/bin/bash"]
