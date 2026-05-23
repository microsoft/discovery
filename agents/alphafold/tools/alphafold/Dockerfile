FROM condaforge/mambaforge:latest

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install scientific stack + bioinformatics tools via conda
# ColabFold requires Python 3.10 and specific JAX versions
RUN mamba install -y -n base \
    -c conda-forge -c bioconda \
    python=3.10 \
    openmm=8.0 \
    pdbfixer \
    kalign2 \
    hhsuite \
    mmseqs2 \
    hmmer \
    "numpy<2" \
    scipy \
    pandas \
    matplotlib \
    biopython \
    seaborn \
    && mamba clean -afy

# Install ColabFold with AlphaFold2 backend
# Let pip resolve JAX + CUDA 12 compatibility
RUN pip install --no-cache-dir \
    "colabfold[alphafold]>=1.5.5" \
    "jax[cuda12_pip]" \
    -f https://storage.googleapis.com/jax-releases/jax_cuda_releases.html

# Download AlphaFold2 model parameters (~3.5GB)
# Stored in /opt/cache/colabfold so they persist in the image
ENV XDG_CACHE_HOME=/opt/cache
RUN python -m colabfold.download || echo "Model download deferred to first run"

# Create working directories
RUN mkdir -p /input /output /workdir /tmp/tool_scratch /app

# Thread control defaults — let scripts override at runtime
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled

# Copy utilities
COPY alphafold_utils.py /app/
COPY test_alphafold_utils.py /app/

WORKDIR /workdir

# Discovery requires no ENTRYPOINT and CMD ["/bin/bash"]
ENTRYPOINT []
CMD ["/bin/bash"]
