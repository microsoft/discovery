#!/bin/bash
# Start the agent workbench with Azure CLI authentication enabled

export AGENT_WORKBENCH_ENABLE_AZURE_CLI=1
echo "🔐 Azure CLI authentication enabled"
echo "Starting agent workbench..."
./start_web_app.sh
