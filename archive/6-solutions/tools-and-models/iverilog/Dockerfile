# Use the official Ubuntu base image, pinned
FROM ubuntu:22.04

# Set environment variables for input and output directories
ENV TOOL_INPUT=/app/input
ENV TOOL_OUTPUT=/app/output
# ENV TOOL_WORKDIR=/app/workdir
ENV IVERILOG="/usr/local/iverilog"

# Install build & runtime deps in one layer, then clean.
# Added automake, libtool, pkg-config, ca-certificates, curl (useful for future extensions).
RUN set -eux; \
    DEBIAN_FRONTEND=noninteractive apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    autoconf \
    automake \
    libtool \
    pkg-config \
    bison \
    flex \
    gperf \
    git \
    wget \
    cmake \
    python3 \
    python3-pip \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone the IVERILOG repository
WORKDIR /tmp/
RUN git clone https://github.com/steveicarus/iverilog.git /tmp/iverilog
WORKDIR /tmp/iverilog

# Build IVERILOG
RUN ls -la && \
    sh autoconf.sh && \
    ./configure --prefix=/usr/local/iverilog && \
    make && \
    make install

# Add IVERILOG binaries to PATH
ENV PATH="/usr/local/iverilog/bin:$PATH"

COPY ./app /app

# RUN useradd -m appuser

# Add non-root user (fixed UID/GID improves reproducibility; adjust values as needed)
RUN set -eux; \
    groupadd -r -g 1000 appuser; \
    useradd  -r -g appuser -u 1000 -d /app -s /usr/sbin/nologin appuser;

# Create tool I/O dirs
RUN mkdir -p "${TOOL_INPUT}" "${TOOL_OUTPUT}" \
    && chown -R appuser:appuser /app "${TOOL_INPUT}" "${TOOL_OUTPUT}"

# # Create a non-root user and switch to it
USER appuser
WORKDIR /app

# ENTRYPOINT [ "/bin/bash" ]
#CMD [ "/bin/bash" ]

# Verify all solvent files exist
#RUN ls -l /usr/local/iverilog
