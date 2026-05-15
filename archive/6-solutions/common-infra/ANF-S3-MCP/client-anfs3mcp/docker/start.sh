#!/bin/bash
source activate mcp-env
cd /app/scripts
export MCP_SERVER_URL="<URL of MCP server>/mcp"
python entrypoint.py "$@"
