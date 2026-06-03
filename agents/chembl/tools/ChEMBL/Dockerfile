# Basic Python container for accessing ChEMBL API
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS base
WORKDIR /app

# System update + TLS certificates (MUST be first RUN for layer sharing)
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# Install ChEMBL API access and data processing libraries
RUN pip3 install requests
RUN pip3 install pandas
RUN pip3 install numpy
# RDKit for basic cheminformatics operations (SMILES validation, InChI conversion, etc.)
# Note: Visualization features (Draw module) require X11 and are not available
RUN pip3 install rdkit
# chembl_webresource_client installed as safety net — the agent instructions direct
# use of ChEMBLUtils (from chembl_utils), but LLMs sometimes hallucinate the public
# API import. Having the package present prevents a ModuleNotFoundError crash.
RUN pip3 install chembl_webresource_client

RUN ln -s /usr/bin/python3 /usr/bin/python

# Create working directories
RUN mkdir -p /input /output /workdir

# /app: Safe from volume mounts, accessible via PYTHONPATH
COPY chembl_utils.py /app/

# Set working directory
WORKDIR /workdir

# Add /app to Python path to ensure module can be found
ENV PYTHONPATH="/app"

CMD ["/bin/bash"]
