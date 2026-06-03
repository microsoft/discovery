FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib

# Thread control defaults (per agent-create convention)
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled
ENV GOMP_CPU_AFFINITY=""

# Shared base layer -- identical to other Discovery agents
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# Common scientific Python packages (shared layer with chemprop, toxpred)
RUN pip3 install --no-cache-dir \
    matplotlib numpy pandas requests scipy seaborn scikit-learn

# PyTorch CPU-only (no CUDA needed for inference; saves ~2 GB vs CUDA wheels)
RUN pip3 install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu

# Chemprop v2 and RDKit (the core ML stack)
RUN pip3 install --no-cache-dir \
    chemprop==2.2.2 \
    lightning \
    rdkit \
    astartes

# Create directories
RUN mkdir -p /workdir /input /output /tmp/gwp_scratch /tmp/matplotlib && \
    chmod 755 /workdir /input /output

# Copy application code
COPY app/gwp_predictor_utils.py /app/gwp_predictor_utils.py
COPY app/predict_gwp.py /app/predict_gwp.py
COPY app/test_gwp_predictor_utils.py /app/test_gwp_predictor_utils.py

# Copy trained models + training fingerprints
COPY models/ /app/models/

# Make utils importable
ENV PYTHONPATH="/app:${PYTHONPATH}"

WORKDIR /workdir

CMD ["/bin/bash"]
