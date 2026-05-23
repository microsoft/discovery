# ============================================================================
# CREST Agent Container for Microsoft Discovery Platform
# CREST 3.0 — Conformer-Rotamer Ensemble Sampling Tool
# https://crest-lab.github.io/crest-docs/
# https://doi.org/10.1063/5.0197592
# ============================================================================
FROM condaforge/mambaforge:latest

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Layer 1: System update, certificates, and download tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates wget xz-utils && \
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

# Layer 2.5: Replace conda CREST binary with GitHub pre-built release
# ---------------------------------------------------------------
# The conda-forge CREST 3.0.2 build has a universal segfault in all
# conformer search modes (confscript2i_ at legacy_wrappers.f90:148).
# The GitHub CI binary (gfortran-12 on Ubuntu) does not have this bug.
# The conda xtb binary works fine — only the crest binary is replaced.
# ---------------------------------------------------------------
RUN wget -q https://github.com/crest-lab/crest/releases/download/latest/crest-gnu-12-ubuntu-latest.tar.xz \
        -O /tmp/crest.tar.xz && \
    mkdir -p /tmp/crest_extract && \
    tar -xJf /tmp/crest.tar.xz -C /tmp/crest_extract && \
    find /tmp/crest_extract -name 'crest' -type f | head -1 | \
        xargs -I{} cp {} /opt/conda/bin/crest && \
    chmod +x /opt/conda/bin/crest && \
    rm -rf /tmp/crest.tar.xz /tmp/crest_extract

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

# XTBPATH tells xtb/CREST where to find parameter files
ENV XTBPATH=/opt/conda/share/xtb

# OPENBLAS_NUM_THREADS=1 prevents nested parallelism warnings.
# OMP_STACKSIZE=4G is recommended for larger systems.
# Do NOT set OMP_NUM_THREADS — CREST manages it via --T flag.
ENV OPENBLAS_NUM_THREADS=1
ENV OMP_STACKSIZE=4G

WORKDIR /workdir

CMD ["/bin/bash"]
