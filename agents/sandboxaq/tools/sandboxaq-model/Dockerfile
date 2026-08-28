FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app

# System update + TLS certificates (MUST be first RUN for layer sharing)
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all
RUN pip3 install --no-cache-dir requests

# Create working directories
RUN mkdir -p /input /output /workdir

# /app: safe from volume mounts, reachable via PYTHONPATH
COPY sandboxaq_utils.py /app/

WORKDIR /workdir
ENV PYTHONPATH="/app"

CMD ["/bin/bash"]
