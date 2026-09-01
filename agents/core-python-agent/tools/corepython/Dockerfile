# ============================================================
# SFI-Compliant Dockerfile for corePythonTool
# Multi-stage: Mambaforge builder → Azure Linux 3.0 runtime
# Complies with AR1.2.7 (pinned tags, non-root, cache cleanup)
# ============================================================

# ---- Stage 1: Builder — create conda environment ----
FROM condaforge/mambaforge:24.9.2-0 AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

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

RUN mamba run -n molenv python -m pip install --no-cache-dir \
      brotli==1.2.0 \
      fonttools==4.60.2 \
      h2==4.3.0 \
      pip==25.3 \
      requests==2.32.4 \
      setuptools==78.1.1 \
      urllib3==2.6.0 \
      werkzeug==3.1.4

# ---- Stage 2: Runtime — Azure Linux 3.0 hardened base ----
FROM mcr.microsoft.com/azurelinux/base/core:3.0

RUN tdnf install -y --setopt=install_weak_deps=False \
      ca-certificates \
      tar \
      shadow-utils \
 && tdnf clean all

# Make Python HTTP clients honor the OS trust store instead of conda's certifi bundle.
# The conda `requests`/`urllib3` default to certifi and conda's OpenSSL uses the env's own CA
# file; point them at the OS trust bundle so any CA added via update-ca-trust (e.g. a
# TLS-inspecting egress CA supplied by the platform) is trusted by all HTTP clients.
ENV REQUESTS_CA_BUNDLE=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
    SSL_CERT_FILE=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
    CURL_CA_BUNDLE=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem

# Non-root user (SFI / CIS benchmark requirement)
RUN groupadd -r moluser && useradd -r -g moluser -s /sbin/nologin moluser

# Copy self-contained conda environment from builder
COPY --from=builder /opt/conda/envs/molenv /opt/conda/envs/molenv

WORKDIR /app

# Copy application code late to maximise layer caching
COPY app/*.py /app/
COPY app/entrypoint.sh /app/entrypoint.sh

# ---- Runtime env vars ----
ENV CONDA_DEFAULT_ENV=molenv
ENV CONDA_PREFIX=/opt/conda/envs/molenv
ENV PATH=/opt/conda/envs/molenv/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create common mount points and set ownership
RUN mkdir -p /input /output /workdir \
 && chown -R moluser:moluser /app /input /output /workdir

USER moluser:moluser

CMD ["tail", "-f", "/dev/null"]