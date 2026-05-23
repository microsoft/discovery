FROM continuumio/miniconda3:latest

# Set working directory
WORKDIR /app

# Install system dependencies including interactive mode requirements
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    ca-certificates \
    tar \
    gzip \
    bash \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && update-ca-certificates

# Create conda environment with RDKit and scientific packages
RUN conda create -n hazardgroups python=3.10 -y && \
    conda install -n hazardgroups -c conda-forge \
    rdkit \
    pandas \
    numpy \
    scipy \
    -y && \
    conda clean -afy

# Activate environment by default
ENV PATH="/opt/conda/envs/hazardgroups/bin:$PATH"
ENV CONDA_DEFAULT_ENV=hazardgroups

# Copy application files
COPY app/ /app/

# Make entrypoint executable
RUN chmod +x /app/entrypoint.py

# Create input and output directories
RUN mkdir -p /input /output /scripts

# Set default environment variables
ENV TOOL_INPUT_DIR=/input
ENV TOOL_OUTPUT_DIR=/output
ENV PYTHONPATH=/app:$PYTHONPATH

CMD ["/bin/bash"]
