# Use Python 3.12 as base image (required for PyTorch compatibility with microsoft-skala)
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libopenblas-dev \
    liblapack-dev \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
# Note: microsoft-skala will automatically install all its dependencies including:
# - torch (PyTorch)
# - qcelemental
# - numpy
# - pint
# - pyscf
# - ase
# - azure-core
# - dftd3
# - e3nn
# - huggingface_hub
# - opt_einsum_fx
# and all their transitive dependencies
# Additional packages:
# - rdkit: for SMILES to XYZ conversion
# - azure-ai-ml: for Azure ML authentication and endpoint management
# - azure-identity: for DefaultAzureCredential authentication
RUN pip install --no-cache-dir \
    microsoft-skala \
    rdkit \
    azure-ai-ml \
    azure-identity

# Copy application files
COPY app/skala_client.py .
COPY app/io_utils.py .

# Create outputs directory for logs
RUN mkdir -p /app/outputs

# Set Python to run in unbuffered mode for better logging
ENV PYTHONUNBUFFERED=1

# Default command to run the skala client
CMD ["python", "skala_client.py"]
