# Basic Python container for accessing PubMed/NCBI APIs
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS base
WORKDIR /app

# Install CA certificates for HTTPS connectivity (required for VS Code tunnels)
RUN tdnf install -y ca-certificates && update-ca-trust

# Install PubMed/NCBI API access libraries
RUN pip3 install biopython
RUN pip3 install pymed
RUN pip3 install requests
RUN pip3 install pandas
RUN pip3 install matplotlib

RUN ln -s /usr/bin/python3 /usr/bin/python

# Set matplotlib config directory to avoid permission issues
ENV MPLCONFIGDIR=/tmp/matplotlib

# Create working directories
RUN mkdir -p /input /output /workdir

# /app: Safe from volume mounts, accessible via PYTHONPATH
COPY pubmed_utils.py /app/

# Set working directory
WORKDIR /workdir

# Add /app to Python path to ensure module can be found
ENV PYTHONPATH="/app"

CMD ["/bin/bash"]