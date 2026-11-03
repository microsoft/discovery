# ============================================================
# SFI-compliant Dockerfile for the bo-doe tool
# Multi-stage: Mambaforge builder -> Azure Linux 3.0 runtime
# Complies with AR1.2.7 (pinned tags, non-root, cache cleanup)
# ============================================================

# ---- Stage 1: Builder -- create the conda environment ----
FROM condaforge/mambaforge:24.9.2-0 AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# CPU-only PyTorch keeps the image small; BO on <10k design points is not
# GPU bound. The sklearn GP backend is the dependency-light fallback.
RUN mamba create -y -n boenv -c pytorch -c conda-forge \
      python=3.11 \
      numpy \
      scipy \
      pandas \
      scikit-learn \
      matplotlib \
      seaborn \
      pyarrow \
      openpyxl \
      pytorch-cpu=2.5.1 \
      cpuonly \
 && mamba clean -a -y

RUN mamba run -n boenv python -m pip install --no-cache-dir \
      botorch==0.12.0 \
      gpytorch==1.13 \
      pip==25.3 \
      setuptools==78.1.1 \
      urllib3==2.6.0 \
 && mamba run -n boenv python -m pip cache purge

# ---- Stage 2: Runtime -- Azure Linux 3.0 hardened base ----
FROM mcr.microsoft.com/azurelinux/base/core:3.0

RUN tdnf install -y --setopt=install_weak_deps=False \
      ca-certificates \
      tar \
      shadow-utils \
 && tdnf clean all

# Make Python HTTP clients honour the OS trust store rather than certifi.
ENV REQUESTS_CA_BUNDLE=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
    SSL_CERT_FILE=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
    CURL_CA_BUNDLE=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem

# Non-root user (SFI / CIS benchmark requirement)
RUN groupadd -r bouser && useradd -r -g bouser -s /sbin/nologin bouser

COPY --from=builder /opt/conda/envs/boenv /opt/conda/envs/boenv

WORKDIR /app

COPY app/*.py /app/
COPY app/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV CONDA_DEFAULT_ENV=boenv
ENV CONDA_PREFIX=/opt/conda/envs/boenv
ENV PATH=/opt/conda/envs/boenv/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV MPLBACKEND=Agg
# The non-root user has no writable home, so point every cache at /tmp.
# Without this matplotlib and fontconfig emit permission errors on import.
ENV HOME=/tmp
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV XDG_CACHE_HOME=/tmp/.cache
ENV FONTCONFIG_PATH=/etc/fonts
# Keep BLAS from oversubscribing the small CPU pools these jobs run on.
ENV OMP_NUM_THREADS=4
ENV MKL_NUM_THREADS=4

RUN mkdir -p /input /output /workdir /tmp/matplotlib /tmp/.cache \
 && chown -R bouser:bouser /input /output /workdir /tmp/matplotlib /tmp/.cache

USER bouser

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-c", "import bodoe_utils; print(bodoe_utils.__version__)"]
