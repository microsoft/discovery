FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY config/ ./config/

# Create non-root user
RUN useradd -m -u 1000 mcpuser && chown -R mcpuser:mcpuser /app
USER mcpuser

# Expose MCP port
EXPOSE 8000

# Run the server in SSE mode
CMD ["python", "-c", "import sys; sys.path.insert(0, 'src'); from s3_mcp import mcp; mcp.run(transport='sse', host='0.0.0.0', port=8000)"]
