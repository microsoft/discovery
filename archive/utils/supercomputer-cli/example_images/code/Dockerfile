# Dockerfile for Azure Linux 3 with VS Code CLI pre-installed
FROM mcr.microsoft.com/azurelinux/base/core:3.0

LABEL maintainer="Discovery Platform"
LABEL description="Azure Linux 3 base image with VS Code CLI for remote tunnel support"

# Install dependencies required for VS Code CLI
RUN tdnf install -y \
    ca-certificates \
    tar \
    gzip \
    curl \
    && tdnf clean all

# Download and install VS Code CLI
# Using the Alpine x64 build which is compatible with Azure Linux
ARG VSCODE_CLI_URL="https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64"
RUN curl -fsSL "${VSCODE_CLI_URL}" -o /tmp/vscode-cli.tar.gz \
    && tar -xzf /tmp/vscode-cli.tar.gz -C /tmp \
    && mv /tmp/code /usr/local/bin/code \
    && chmod +x /usr/local/bin/code \
    && rm -f /tmp/vscode-cli.tar.gz

# Verify installation
RUN /usr/local/bin/code --version

# Default command
CMD ["/bin/bash"]
