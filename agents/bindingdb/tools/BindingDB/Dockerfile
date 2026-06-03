# BindingDB Agent - Multi-stage Self-contained Build
# 
# This Dockerfile builds the SQLite database during the Docker build process.
# No external database file required - everything is self-contained.
#
# Build command:
#   docker build -f Dockerfile.multistage -t bindingdb-agent:latest .
#
# Build time: 
#   - First build: ~30-45 minutes (downloads TSV and builds database)
#   - Subsequent builds: ~2-3 minutes (cached database layer is reused)
#
# Image size: ~10 GB
#
# Advantages:
#   - Single command build (no manual database creation)
#   - Fully reproducible and self-contained
#   - Excellent Docker layer caching (database only built once)
#
# Disadvantages:
#   - First build is very slow (database creation takes time)
#   - Cache invalidates if tsv_to_sqlite.py changes

# ============================================================================
# Stage 1: Database Builder
# ============================================================================
FROM mcr.microsoft.com/azurelinux/base/python:3.12 AS builder

WORKDIR /build

# Install dependencies needed for database creation
RUN pip3 install --no-cache-dir \
        pandas \
        requests

# Copy the database converter script
COPY tsv_to_sqlite.py /build/

# Build the SQLite database from TSV source
# This layer is cached - it only rebuilds if tsv_to_sqlite.py changes
# or if Docker cache is cleared
RUN echo "Building BindingDB database (this will take 30-45 minutes)..." && \
    python3 tsv_to_sqlite.py --output /build/bindingdb.db && \
    echo "Database build complete!"

# Verify database was created successfully
RUN test -f /build/bindingdb.db || \
    (echo "Database file not found after build!" && exit 1)

# ============================================================================
# Stage 2: Runtime Image
# ============================================================================
FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app

# Install CA certificates for HTTPS connectivity (required for VS Code tunnels)
RUN tdnf install -y ca-certificates && update-ca-trust

# Install runtime dependencies
RUN pip3 install --no-cache-dir \
        pandas \
        requests

# Create symlink for python command
RUN ln -s /usr/bin/python3 /usr/bin/python

# Create working directories
RUN mkdir -p /input /output /workdir

# Copy pre-built database from builder stage (NO EXTERNAL FILE NEEDED!)
COPY --from=builder /build/bindingdb.db /app/bindingdb.db

# Copy agent code
COPY bindingdb_utils.py /app/

# Set working directory for script execution
WORKDIR /workdir

# Environment variables
ENV PYTHONPATH="/app"
ENV BINDINGDB_DATABASE="/app/bindingdb.db"

# Verify database is accessible
RUN test -f /app/bindingdb.db && \
    echo "Database successfully copied to runtime image"

CMD ["/bin/bash"]
