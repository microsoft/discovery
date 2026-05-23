# =============================================================================
# ToxPred -- Toxicity prediction agent
# Standalone build: inlines all chemprop dependencies
# =============================================================================
FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled
ENV GOMP_CPU_AFFINITY=""
ENV PYTHONPATH="/app:${PYTHONPATH}"

RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

RUN pip3 install --no-cache-dir \
    matplotlib numpy pandas requests scipy seaborn scikit-learn

RUN pip3 install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cu124

RUN pip3 install --no-cache-dir \
    chemprop==2.2.2 \
    lightning \
    rdkit \
    astartes

RUN mkdir -p /workdir /input /output /app /tmp/chemprop_scratch /tmp/matplotlib && \
    chmod 755 /workdir /input /output

COPY toxpred_utils.py /app/toxpred_utils.py
COPY test_toxpred_utils.py /app/test_toxpred_utils.py
COPY README.md /app/README.md
COPY example-input-files /app/example-input-files

WORKDIR /workdir
CMD ["/bin/bash"]