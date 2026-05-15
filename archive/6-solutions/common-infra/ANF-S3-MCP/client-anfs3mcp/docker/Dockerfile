FROM condaforge/mambaforge:23.3.1-1

LABEL description="Docker image for MCP S3 client tool in Microsoft Discovery"
LABEL version="1.0.0"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Install system dependencies
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    libkrb5-3 \
    libtasn1-6 \
    openssl \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create conda environment
RUN conda config --add channels conda-forge && \
    conda config --set channel_priority strict && \
    mamba create -n mcp-env -c conda-forge \
    python=3.10 \
    boto3 \
    -y

# Use conda environment for subsequent commands
SHELL ["conda", "run", "-n", "mcp-env", "/bin/bash", "-c"]

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./scripts/ /app/scripts/
COPY start.sh /app/start.sh

# Set up entrypoint script
RUN cd /app/scripts && \
    chmod +x entrypoint.py && \
    chmod +x /app/start.sh

# Create non-root user
RUN groupadd -r <usergroup> && \
    useradd -r -g <usergroup> -d /app -s /sbin/nologin <AIuser> && \
    chown -R <AIuser>:<usergroup> /app
USER ai4semi

# ENTRYPOINT ["/app/start.sh"]
# CMD ["--help"]
