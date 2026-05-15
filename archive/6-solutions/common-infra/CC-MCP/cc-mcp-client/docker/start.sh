#!/bin/bash
cd /app
export MCP_SERVER_URL="http://10.16.16.16:8080/mcp"
python entrypoint.py "$@"
