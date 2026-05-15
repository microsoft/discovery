# Basic RDKit container for running scripts
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS base
WORKDIR /app

RUN tdnf update -y
RUN pip3 install azure-storage-blob azure-identity
RUN pip3 install --no-cache-dir paramiko

# Initialize working directory
RUN mkdir -p /app/input/root /app/output/
RUN chmod -R 755 /app/input/ /app/output/


# Copy application code
COPY ./app /app/
RUN chmod +x /app/execssh.py

CMD ["/bin/bash"]
