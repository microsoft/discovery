# COCONUT Agent Container for Microsoft Discovery Platform
# Azure Linux 3.0 (Python 3.12) — hardened, minimal, fast CVE patching

FROM mcr.microsoft.com/azurelinux/base/python:3.12

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# System dependencies — keep this block identical across agents for layer sharing
RUN tdnf -y update && \
    tdnf -y install \
        ca-certificates \
        gzip tar \
    && tdnf clean all

RUN mkdir -p /app /input /output

# Pip packages: requests for API access, pandas for data handling
RUN pip3 install --no-cache-dir requests pandas

# Copy utilities
WORKDIR /app
COPY coconut_utils.py /app/coconut_utils.py
ENV PYTHONPATH="/app"
WORKDIR /app/workdir
CMD ["/bin/bash"]
