FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1

RUN tdnf -y update && \
    tdnf -y install ca-certificates shadow-utils && \
    update-ca-trust && \
    tdnf clean all

RUN pip3 install --no-cache-dir \
    flowio \
    matplotlib \
    numpy \
    pandas \
    scikit-learn \
    scipy

RUN mkdir -p /app /workdir /input /output /tmp/matplotlib && \
    chmod 755 /app /workdir /input /output

COPY flow_qc_utils.py /app/flow_qc_utils.py

RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    chown -R appuser:appuser /app /workdir /input /output /tmp/matplotlib

USER appuser
WORKDIR /workdir
ENV PYTHONPATH=/app

CMD ["/bin/bash"]
