# Basic Python container for accessing ClinicalTrials.gov API
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS base
WORKDIR /app

# System update + TLS certificates (MUST be first RUN for layer sharing)
RUN tdnf -y update && \
    tdnf -y install ca-certificates && \
    update-ca-trust && \
    tdnf clean all

# Install ClinicalTrials.gov API access libraries
RUN pip3 install requests
RUN pip3 install pandas
RUN pip3 install matplotlib

RUN ln -s /usr/bin/python3 /usr/bin/python

# Set matplotlib config directory to avoid permission issues
ENV MPLCONFIGDIR=/tmp/matplotlib

# Create working directories
RUN mkdir -p /input /output /workdir

# /app: Safe from volume mounts, accessible via PYTHONPATH
COPY clinicaltrials_utils.py /app/

# Set working directory
WORKDIR /workdir

# Add /app to Python path to ensure module can be found
ENV PYTHONPATH="/app"

CMD ["/bin/bash"]
