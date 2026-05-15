# Basic RDKit container for running scripts
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS base
WORKDIR /app

RUN tdnf update -y
RUN pip3 install azure-storage-blob azure-identity

# Copy application code
COPY ./app /app/
RUN chmod +x /app/fileSaver.py

CMD ["/bin/bash"]