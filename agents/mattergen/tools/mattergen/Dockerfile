# MatterGen Container for Microsoft Discovery Platform
# Generative AI for inorganic crystal structure design
# Requires CUDA GPU for diffusion model inference
#
# Base: Official PyTorch 2.6.0 + CUDA 12.4 + cuDNN 9 (Python 3.12)
# Model: Zeni et al., Nature 2025 (DOI:10.1038/s41586-025-08628-5)
# License: MIT (https://github.com/microsoft/mattergen)

FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_PROGRESS_BAR=off \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

# -- System dependencies ----------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# -- PyTorch Geometric extensions (match torch 2.6.0+cu124) -----------------
RUN pip install --no-cache-dir -q torch_geometric scipy \
    && pip install --no-cache-dir -q --no-index \
        torch_scatter \
        torch_sparse \
        torch_cluster \
        -f https://data.pyg.org/whl/torch-2.6.0+cu124.html \
    && echo "=== PyG extensions installed ==="

# -- MatterGen non-torch dependencies (install BEFORE mattergen) -------------
RUN pip install --no-cache-dir -q \
        "numpy<2.0" \
        pandas \
        matplotlib==3.8.4 \
        seaborn \
        "ase<=3.25.0" \
        cachetools \
        contextlib2 \
        "emmet-core>=0.84.2" \
        fire \
        huggingface-hub \
        hydra-core==1.3.1 \
        hydra-joblib-launcher==1.1.5 \
        lmdb \
        "matscipy>=0.7.0" \
        "mattersim>=1.1" \
        "monty==2024.7.30" \
        omegaconf==2.3.0 \
        "pymatgen>=2024.6.4" \
        pytorch-lightning==2.0.6 \
        SMACT \
        "sympy>=1.11.1" \
        "setuptools<81" \
    && echo "=== MatterGen deps installed ==="

# -- Clone & install MatterGen (--no-deps to skip torch pin conflict) --------
WORKDIR /app
RUN git clone --depth 1 https://github.com/microsoft/mattergen.git /app/mattergen-src \
    && echo "=== MatterGen cloned ==="

WORKDIR /app/mattergen-src
RUN pip install --no-cache-dir -q --no-deps -e . \
    && echo "=== MatterGen installed ==="

# -- Preserve upstream LICENSE and NOTICE files ------------------------------
RUN mkdir -p /app/mattergen-src/licenses && \
    cp /app/mattergen-src/LICENSE /app/mattergen-src/licenses/LICENSE && \
    cp /app/mattergen-src/NOTICE /app/mattergen-src/licenses/NOTICE

# -- Download all pretrained model checkpoints from HuggingFace Hub ----------
COPY download_checkpoints.py /tmp/download_checkpoints.py
RUN python /tmp/download_checkpoints.py && rm /tmp/download_checkpoints.py \
    && echo "=== Checkpoints downloaded ==="

# -- Working directories -----------------------------------------------------
RUN mkdir -p /workdir /input /output /tmp/mattergen_scratch

# -- Copy utilities ----------------------------------------------------------
COPY mattergen_utils.py /app/mattergen_utils.py
COPY test_mattergen_utils.py /app/test_mattergen_utils.py

ENV PYTHONPATH="/app:/app/mattergen-src"

WORKDIR /app/workdir
CMD ["/bin/bash"]
