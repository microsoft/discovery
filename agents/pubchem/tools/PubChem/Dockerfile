# Basic RDKit container for running scripts
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS base
WORKDIR /app

# System update + TLS certificates
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

RUN pip3 install --no-cache-dir PubChemPy Requests

RUN ln -s /usr/bin/python3 /usr/bin/python

CMD ["/bin/bash"]
