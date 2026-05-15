# Azure Cyclecloud MCP client

These Discovery components provide an example of how to implement a MCP client to interface with an MCP server that connects to the Azure Cyclecloud HPC orchestrator.

## Project Overview ##

The ANF MCP solution consists of the following components:

1. **cc-MCPAgent**: Processes natural language requests and uses the cc-MCPTool to dispatch SLURM commands and basic file operations to Cyclecloud.
2. **cc-MCPTool**: Executes the SLURM and file functions, and  communicates with the MCP server.
3. **cc-MCPDisplayAgent**: Converts output from the MCP server into user friendly output.
4. **cc-MCPWf**: Manages the workflow for the file request to cc-mcp interface flow.

### tool-definition/cc-MCPTool.yaml

- `siphyeast2acr.azurecr.io/cc-mcp:latest` - Replace with your Azure Container Registry URL and image name

### docker/entrypoint.py
- `<MCP_URL>` - Replace with the URL for your MCP server. Typically http://<IP Address>:<port>/mcp

### docker/start.sh
- `<MCP_SERVER_URL>` - Replace with the URL for your MCP server. Typically http://<IP Address>:<port>/mcp


