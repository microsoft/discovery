FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV KMP_AFFINITY=disabled

# Shared base layer — keep identical across agents
RUN tdnf -y update && \
    tdnf -y install ca-certificates shadow-utils && \
    update-ca-trust && \
    tdnf clean all

# Common scientific Python packages (shared layer)
RUN pip3 install --no-cache-dir \
    matplotlib==3.10.1 \
    numpy==2.2.4 \
    pandas==2.2.3 \
    requests==2.32.3 \
    scipy==1.15.2 \
    seaborn==0.13.2

# Bioinformatics-specific packages
RUN pip3 install --no-cache-dir \
    GEOparse==2.0.4 \
    networkx==3.4.2 \
    scikit-learn==1.6.1 \
    statsmodels==0.14.6 \
    xgboost==3.0.1

# Create directories
RUN mkdir -p /workdir /input /output /tmp/rnaseq_scratch /tmp/matplotlib && \
    chmod 755 /workdir /input /output

# Copy utilities
COPY rnaseq_utils.py /app/rnaseq_utils.py

# Add non-root user (shadow-utils provides groupadd/useradd on Azure Linux)
RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    chown -R appuser:appuser /app /workdir /output /input /tmp/rnaseq_scratch /tmp/matplotlib
USER appuser

ENV PYTHONPATH=/app:$PYTHONPATH

CMD ["/bin/bash"]
