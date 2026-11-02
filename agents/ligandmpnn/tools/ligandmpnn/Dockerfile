# Source-only LigandMPNN scaffold. No image has been built.
FROM nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04

# Remove this gate only after provisioning and reviewing runtime-plan.yaml.
RUN printf '%s\n' 'Scaffold only: scientific dependencies and model artifacts are not provisioned. Complete runtime-plan.yaml before building a release.' >&2; exit 1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    HF_HOME=/cache \
    PYTHONPATH=/app \
    OMP_NUM_THREADS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install a pinned, compatible LigandMPNN runtime here.
# Upstream: https://github.com/dauparas/LigandMPNN
# Planned stack: PyTorch with CUDA, LigandMPNN source, ProDy, Model-specific checkpoints
# Do not fetch restricted checkpoints or embed credentials in this build.

COPY ligandmpnn_utils.py /app/
COPY test_ligandmpnn_utils.py /app/
COPY runtime-plan.yaml /app/

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser && \
    mkdir -p /input /output /workdir /cache && \
    chown -R 1000:1000 /app /output /workdir /cache

USER appuser
WORKDIR /workdir
CMD ["/bin/bash"]
