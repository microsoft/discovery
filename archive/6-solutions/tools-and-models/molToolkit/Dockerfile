
# Dockerfile for MolToolkit
# Base image includes conda-forge channel and mamba tooling
FROM condaforge/mambaforge:latest

WORKDIR /app

# Avoid interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

# (Optional) makes RUN lines easier to read + fails on pipe errors
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ---- System deps (single layer, no upgrade) ----
# Combine update+install+cleanup in one layer to avoid persisting apt lists
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      gpgv \
      libsm6 \
      libxrender1 \
      tar \
      wget \
 && rm -rf /var/lib/apt/lists/*

# ---- Conda env (single solve using mamba) ----
# Install everything in one transaction to reduce dependency re-solves
RUN mamba create -y -n molenv -c conda-forge \
      python=3.11 \
      ase \
      biopython \
      mdanalysis \
      matplotlib \
      numpy \
      openbabel \
      pyarrow \
      pandas \
      pymatgen \
      pymol-open-source \
      pyscf \
      rdkit \
      ruamel.yaml \
      scanpy \
      scikit-bio \
      scikit-learn \
      scipy \
      seaborn \
      sympy \
 && mamba clean -a -y

# ---- Patch base conda env (Trivy scans all site-packages dirs) ----
RUN pip install --no-cache-dir \
      h2==4.3.0 \
      pip==26.0 \
      requests==2.32.4 \
      setuptools==78.1.1 \
      urllib3==2.6.3 \
      wheel==0.46.2

# ---- pip (ONLY inside molenv; no duplicate global pip install) ----
RUN mamba run -n molenv python -m pip install --no-cache-dir \
      brotli==1.2.0 \
      fonttools==4.60.2 \
      h2==4.3.0 \
      "jaraco.context>=6.1.0" \
      pillow==12.1.1 \
      pip==26.0 \
      requests==2.32.4 \
      setuptools==78.1.1 \
      urllib3==2.6.3 \
      werkzeug==3.1.5 \
      wheel==0.46.2

# Copy code late to maximize Docker layer caching
COPY app/*.py /app/

# ---- Runtime env vars ----
ENV CONDA_DEFAULT_ENV=molenv
ENV CONDA_PREFIX=/opt/conda/envs/molenv
ENV PATH=/opt/conda/envs/molenv/bin:/opt/conda/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create common mount points / working dirs (single layer)
RUN mkdir -p /workdir

CMD ["/bin/bash"]