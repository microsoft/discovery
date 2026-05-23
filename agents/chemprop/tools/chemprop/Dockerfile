FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib

# NVIDIA Container Toolkit — required for GPU passthrough on non-nvidia base images
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Thread control defaults
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled
ENV GOMP_CPU_AFFINITY=""

# Shared base layer ΓÇö identical to other Discovery agents
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# Common scientific Python packages (shared layer)
RUN pip3 install --no-cache-dir \
    matplotlib numpy pandas requests scipy seaborn scikit-learn

# PyTorch with CUDA 12.4 — required for GPU acceleration on H100/A100 nodes
RUN pip3 install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cu124

# Chemprop v2 and its dependencies (lightning, rdkit, astartes)
RUN pip3 install --no-cache-dir \
    chemprop==2.2.2 \
    lightning \
    rdkit \
    astartes

# Create directories
RUN mkdir -p /workdir /input /output /tmp/chemprop_scratch /tmp/matplotlib && \
    chmod 755 /workdir /input /output

# Copy utility library
COPY chemprop_utils.py /app/chemprop_utils.py

# Make utils importable
ENV PYTHONPATH="/app:${PYTHONPATH}"

WORKDIR /workdir

CMD ["/bin/bash"]
