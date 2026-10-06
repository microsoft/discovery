# NVIDIA ALCHEMI Toolkit container for Microsoft Discovery.
# Build context: the agent directory (parent of tools/), for example
#   docker build -f tools/nvidia-alchemi/Dockerfile -t nvidia-alchemi:1.1.2 .
# Public base and package indexes only. Dependencies are exact versions from
# requirements-build.txt; checkpoints are downloaded and hash-verified at build
# time so jobs run offline. GPU required at runtime (no CPU fallback kernels).
ARG BASE_IMAGE=nvidia/cuda:13.0.1-devel-ubuntu24.04@sha256:7d2f6a8c2071d911524f95061a0db363e24d27aa51ec831fcccf9e76eb72bc92
FROM ${BASE_IMAGE}
ARG BASE_IMAGE

LABEL org.opencontainers.image.version="1.1.2"
ENV PYTHONUNBUFFERED=1 \
    PIP_PROGRESS_BAR=off \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

# python3.12-dev is needed by runtime TorchInductor/JIT compilation.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev python3-pip \
        git curl ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/venv \
    XDG_CACHE_HOME=/opt/cache \
    TORCH_HOME=/opt/cache/torch \
    HF_HOME=/opt/cache/huggingface

COPY tools/nvidia-alchemi/requirements-build.txt tools/nvidia-alchemi/checkpoints.json tools/nvidia-alchemi/download_checkpoints.py /app/build/
RUN pip install --no-deps -r /app/build/requirements-build.txt && pip check
RUN mkdir -p /opt/cache/torch /opt/cache/huggingface \
    && python /app/build/download_checkpoints.py /app/build/checkpoints.json

RUN mkdir -p /app/workdir /workdir /input /output /tmp/alchemi_scratch \
    && chmod -R 0777 /opt/cache /app/workdir /workdir /output /tmp/alchemi_scratch \
    && chmod -R a+rX /root

COPY tools/nvidia-alchemi/alchemi_utils.py tools/nvidia-alchemi/alchemi_artifacts.py tools/nvidia-alchemi/alchemi_validators.py tools/nvidia-alchemi/release_smoke.py tools/nvidia-alchemi/build_release_manifest.py /app/
COPY tools/nvidia-alchemi/example-input-files /app/example-input-files
COPY THIRD_PARTY_NOTICES.md /app/THIRD_PARTY_NOTICES.md
COPY agent.yaml /app/agent-source.yaml
COPY tools/nvidia-alchemi/tool.yaml /app/tool-definition.yaml
COPY tools/nvidia-alchemi/tests /app/tests
ENV PYTHONPATH="/app" \
    ALCHEMI_AGENT_RELEASE="1.1.2" \
    ALCHEMI_BASE_IMAGE="${BASE_IMAGE}"
RUN python /app/build_release_manifest.py \
    && python -B -m unittest discover -s /app/tests -v
WORKDIR /app/workdir
CMD ["/bin/bash"]
