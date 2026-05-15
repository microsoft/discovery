# VS Code Tunnel Example

This example demonstrates using the Azure Linux 3 base image with VS Code CLI pre-installed.

## Quick Start

### 1. Build the base image

From the repository root:

```bash
docker build -f Dockerfile.vscode -t azurelinux-vscode:latest .
```

### 2. Run interactively

```bash
docker run -it azurelinux-vscode:latest /bin/bash
```

Inside the container, verify VS Code CLI:

```bash
code --version
```

### 3. Use with Discovery Platform

Build and deploy:

```bash
# Build via ACR
python -m discovery_poll.cli build . \
  --image azurelinux-vscode \
  --tag v1.0

# Start a tunnel-enabled tool run
python -m discovery_poll.cli start --vscode "your-command"
```

## Extending the Base Image

Create your own Dockerfile building on this base:

```dockerfile
FROM azurelinux-vscode:latest

# Install your application dependencies
RUN tdnf install -y python3 python3-pip git && tdnf clean all

# Copy your application
COPY ./app /app
WORKDIR /app

# Install Python dependencies
RUN pip3 install -r requirements.txt

# Your application entrypoint
CMD ["python3", "main.py"]
```

Then build:

```bash
docker build -t my-app-with-vscode:latest .
```

## Manual Tunnel Setup

If you need to manually start a tunnel (not using Discovery CLI):

```bash
# Get tunnel credentials from your tunnel provider
TUNNEL_ID="your-tunnel-id"
TOKEN="your-token"

# Start tunnel in background
docker run -d \
  --name my-vscode-tunnel \
  azurelinux-vscode:latest \
  /usr/local/bin/start-vscode-tunnel.sh "${TUNNEL_ID}" "${TOKEN}"

# Check tunnel logs
docker exec my-vscode-tunnel cat /tmp/vscode-tunnel.log
```

## Environment Variables

- `VS_CODE_TUNNEL_LOG`: Override log file location (default: `/tmp/vscode-tunnel.log`)

## Troubleshooting

### Tunnel fails to start

Check logs:

```bash
docker exec <container> cat /tmp/vscode-tunnel.log
```

### Connection refused

Ensure the container has network access:

```bash
docker run --rm azurelinux-vscode:latest curl -I https://code.visualstudio.com
```

### Permission denied

Verify script permissions:

```bash
docker run --rm azurelinux-vscode:latest \
  ls -la /usr/local/bin/start-vscode-tunnel.sh
```
