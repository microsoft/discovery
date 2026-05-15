# PDBInsights - Protein structure analysis with PDBFixer/OpenMM support
# Conda required for openmm/pdbfixer (no reliable pip wheels)
FROM condaforge/mambaforge:latest
WORKDIR /app

# Security: Update OS packages to patch known vulnerabilities
RUN apt-get update && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*

# Install conda packages (openmm + pdbfixer require conda-forge)
RUN mamba install -y -c conda-forge \
    python=3.12 \
    biopython \
    pdbfixer \
    openmm \
    requests \
    pandas \
    && mamba clean -afy

# Security: Upgrade pip packages with known vulnerabilities
RUN pip install --no-cache-dir --upgrade \
    "urllib3>=2.6.3" \
    "wheel>=0.46.2" \
    "setuptools>=78.1.1" \
    "jaraco.context>=6.1.0" \
    "Brotli>=1.2.0" \
    "requests>=2.32.4" \
    "h2>=4.3.0" \
    "pip>=26.0"

# Ensure python symlink exists
RUN ln -sf /opt/conda/bin/python3 /usr/bin/python || true

# Create working directories
RUN mkdir -p /input /output /workdir

# Copy utility module
COPY PDBInsights_utils.py /app/

WORKDIR /workdir
ENV PYTHONPATH="/app"

CMD ["/bin/bash"]
