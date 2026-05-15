# ============================================================================
# CREST Agent Container for Microsoft Discovery Platform
# CREST 3.0 — Conformer-Rotamer Ensemble Sampling Tool
# https://crest-lab.github.io/crest-docs/
# https://doi.org/10.1063/5.0197592
# ============================================================================
FROM condaforge/mambaforge:latest

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Layer 1: System update and certificates (SHARED pattern)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Layer 2: Install CREST, xtb, and scientific stack via mamba
# CREST 3.0+ integrates tblite for standalone GFN calculations;
# xtb is still needed for QCG and some legacy features.
RUN mamba install -y -c conda-forge \
    crest \
    xtb \
    rdkit \
    openbabel \
    numpy \
    scipy \
    matplotlib-base \
    pandas \
    ase \
    pytest \
    && mamba clean -afy

# Layer 3: Copy utils library
COPY crest_utils.py /app/

# Layer 4: Setup directories and environment
RUN mkdir -p /workdir /input /output /tmp/crest_scratch

# Layer 5: Non-root user for security
RUN useradd -m -s /bin/bash crest \
    && chown -R crest:crest /workdir /input /output /tmp/crest_scratch /app
USER crest

# Make crest_utils importable without sys.path hacks.
ENV PYTHONPATH=/app

# OPENBLAS_NUM_THREADS=1 prevents nested parallelism warnings.
# OMP_STACKSIZE=4G is recommended for larger systems.
# Do NOT set OMP_NUM_THREADS — CREST manages it via --T flag.
ENV OPENBLAS_NUM_THREADS=1
ENV OMP_STACKSIZE=4G

WORKDIR /workdir

CMD ["/bin/bash"]
