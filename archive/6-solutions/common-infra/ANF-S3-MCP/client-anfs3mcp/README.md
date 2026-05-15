# Azure NetApp Files MCP client

These Discovery components provide an example of how to implement a MCP client to interface with an MCP server that connects to the Azure NetApp Files Object REST interface.

## Project Overview ##

The ANF MCP solution consists of the following components:

1. **ANFMCPAgent**: Processes natural language requests and uses the ANFMCPTool to execute Object REST commands to the MCP server.
2. **ANFMCPTool**: Executes the Object REST commands and communicates with the MCP server.
3. **ANFMCPSumAgent**: Summarizes and converts output from the MCP server into user friendly output.
4. **ANFMCPWf**: Manages the workflow for the file request to ANF interface flow.

## Configuration Parameters

The following parameters need to be replaced with your specific information before deploying this solution:

### agent-definition/ANFMCPAgent.yaml
- `<your ANF root volume>` - Replace with the name of your Azure NetApp Files root volume (appears twice), for example: /mount
- `<your bucket name>` - Replace with the name of your S3 bucket that maps to the ANF volume, for example: mountbucket

### tool-definition/ANFMCPTool.yaml
- `siphyeast2acr.azurecr.io/anfmcp:latest` - Replace with your Azure Container Registry URL and image name
- `<MCP server IP address - typically http:IP address:port>/mcp` - Replace with your actual MCP server URL including IP address and port (appears in all 10 action environment variables)

### docker/scripts/.env
- `<Access ID for the bucket>` - Replace with your AWS Access Key ID for S3 bucket access
- `<Access Key for the bucket>` - Replace with your AWS Secret Access Key for S3 bucket access
- `<Endpoint for your ANF, typically 'https://IPaddress'>` - Replace with your Azure NetApp Files S3-compatible endpoint URL


