# =============================================================================
# RFDiffusion Agent — Protein Backbone Design via Denoising Diffusion
# =============================================================================
# GPU REQUIRED: Diffusion inference needs CUDA GPU
# Models: Base (~600MB) + Complex (~600MB) baked into image
# =============================================================================

FROM condaforge/mambaforge:latest

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    DGLBACKEND=pytorch \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch + CUDA 12.1 via conda (most reliable for GPU tools)
RUN mamba install -y -c pytorch -c nvidia \
    python=3.10 \
    pytorch=2.3.1 \
    pytorch-cuda=12.1 \
    && mamba clean -afy

# Install DGL via pip (more consistent than conda channel)
RUN pip install --no-cache-dir \
    dgl -f https://data.dgl.ai/wheels/torch-2.3/cu121/repo.html

# Scientific Python stack
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    scipy==1.13.1 \
    matplotlib==3.9.2 \
    pandas==2.2.2 \
    seaborn==0.13.2 \
    biopython==1.84

# Clone RFDiffusion (pinned commit for reproducibility)
RUN git clone https://github.com/RosettaCommons/RFdiffusion.git /opt/RFdiffusion

# Install SE3Transformer (bundled in RFDiffusion repo)
RUN cd /opt/RFdiffusion/env/SE3Transformer && \
    pip install --no-cache-dir .

# Install RFDiffusion
RUN cd /opt/RFdiffusion && \
    pip install --no-cache-dir -e .

# Install remaining dependencies
RUN pip install --no-cache-dir \
    hydra-core \
    omegaconf \
    pyrsistent \
    icecream \
    opt_einsum \
    e3nn

# Download model weights: Base (unconditional/scaffolding) + Complex (binder design)
RUN mkdir -p /opt/RFdiffusion/models && \
    wget -q -O /opt/RFdiffusion/models/Base_ckpt.pt \
      "http://files.ipd.uw.edu/pub/RFdiffusion/6f5902ac237024bdd0c176cb93063dc4/Base_ckpt.pt" && \
    wget -q -O /opt/RFdiffusion/models/Complex_base_ckpt.pt \
      "http://files.ipd.uw.edu/pub/RFdiffusion/e29311f6f1bf1af907f9ef9f44b8328b/Complex_base_ckpt.pt"

# Copy utilities
COPY rfdiffusion_utils.py /app/
COPY test_rfdiffusion_utils.py /app/

# Create directory structure
RUN mkdir -p /workdir /input /output /tmp/rfdiffusion_scratch /tmp/matplotlib

# Set Python path
ENV PYTHONPATH="/opt/RFdiffusion:/app:${PYTHONPATH}"

WORKDIR /workdir
CMD ["/bin/bash"]
