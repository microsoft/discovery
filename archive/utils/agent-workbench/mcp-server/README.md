# Discovery Agent Workbench MCP Server - Experimental

Alongside the browser experience, the Agent Workbench ships with an MCP server companion that lets you drive the same workflows directly from VS Code or GitHub Copilot chat. The server exposes tool calls for creating investigations, listing published agents/nodepools, submitting and monitoring Discovery supercomputer jobs, organizing scripts/inputs/outputs, validating catalog assets, and even publishing or reloading agent/tool definitions.

Highlights:

- Provides a complete job lifecycle: upload inputs, submit jobs with the correct nodepool, stream logs, retrieve results, and clean up storage.
- Includes configuration/profile management plus helper utilities such as lessons-learned tracking and Mermaid workflow generation.

## Quick Setup

### Automatic Setup (Recommended)

Run the setup script from the mcp-server directory:

```bash
python setup_github_copilot.py
```

The script will:
1. ✅ Detect your environment (local, Codespaces, remote)
2. ✅ Choose the appropriate transport mechanism
3. ✅ Start HTTP server if needed (for web environments)
4. ✅ Configure all VS Code settings files
5. ✅ Provide clear next steps

### Environment-Specific Behavior

#### Local VS Code
- **Transport**: stdio (process-based)
- **No server needed**: Direct process communication
- **Config location**: `~/.config/Code/User/mcp.json` (Linux/Mac) or `%APPDATA%\Code\User\mcp.json` (Windows)

#### GitHub Codespaces / VS Code Web
- **Transport**: HTTP/SSE (web-compatible)
- **Auto-starts**: HTTP server in background on available port (8000+)
- **Config location**: `/workspaces/.codespaces/.persistedshare/mcp.json` + standard locations
- **Health check**: `curl http://localhost:8000/health`
- **Logs**: `/tmp/mcp_server.log`

#### Remote SSH
- **Transport**: stdio (over SSH tunnel)
- **Works like**: Local VS Code through SSH connection

### Manual Setup

<details>
<summary>Click to expand manual setup instructions</summary>

#### For Local VS Code (stdio)

Add to `mcp.json`:

```json
{
  "servers": {
    "Agent Workbench": {
      "type": "stdio",
      "command": "/path/to/python",
      "args": ["/path/to/mcp-server/server.py"],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

#### For Codespaces (HTTP/SSE)

1. Start the HTTP server:
```bash
cd /workspaces/Bremen/utils/agent-workbench/mcp-server
python server_http.py > /tmp/mcp_server.log 2>&1 &
```

2. Add to `mcp.json`:
```json
{
  "servers": {
    "Agent Workbench": {
      "type": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

**Settings locations:**
- Linux/Mac: `~/.config/Code/User/mcp.json`
- Windows: `%APPDATA%\Code\User\mcp.json`
- Codespaces: `/workspaces/.codespaces/.persistedshare/mcp.json`

</details>

## Features

The MCP server provides tools for:
- **Investigation Management**: Create and organize computational workflows
- **Agent Discovery**: List and explore available computational agents
- **Job Submission**: Execute scientific computations on Azure Discovery Supercomputer
- **Job Monitoring**: Check status, view logs, retrieve results
- **File Management**: Organize scripts, inputs, outputs in structured directories
- **Publishing**: Publish tools and agents to Azure Discovery
- **Validation**: Validate agent definitions against schemas
- **Configuration**: Manage Discovery configs and profiles

## Requirements

- Python 3.12+
- Virtual environment at `.venv` with required packages
- Agent Workbench components
- For web environments: MCP SDK and HTTP dependencies (auto-installed)

### Install Dependencies

```bash
cd /workspaces/Bremen/utils/agent-workbench
pip install -r mcp-server/mcp_requirements.txt
```

## Usage

Once configured, the server runs automatically when VS Code/Copilot needs it. You can use the tools through GitHub Copilot chat or any MCP-compatible client.

### Example Usage in GitHub Copilot

```
"What agents are available?"
"List the available computational tools"
"Calculate mol weight of CCO and generate an optimized conformer for it."
"Check the status of my last job"
```

## HTTP Server Management (Web Environments)

### Check Server Status
```bash
curl http://localhost:8000/health
```

### View Logs
```bash
cat /tmp/mcp_server.log
tail -f /tmp/mcp_server.log  # Follow logs
```

### Restart Server
```bash
pkill -f server_http.py
cd /workspaces/Bremen/utils/agent-workbench/mcp-server
python server_http.py > /tmp/mcp_server.log 2>&1 &
```

### Find Server PID
```bash
cat /tmp/mcp_server.pid
ps aux | grep server_http.py
```

## Troubleshooting

### Server Not Appearing in VS Code

**Solution:**
1. Reload VS Code window: `Ctrl+Shift+P` → "Developer: Reload Window"
2. Re-run setup: `python setup_github_copilot.py`
3. Check the terminal output for errors

### "No delegate found" Error (Codespaces)

**Cause:** Trying to use stdio in a web environment

**Solution:**
1. Run `python setup_github_copilot.py` to auto-detect and configure
2. Verify HTTP server is running: `curl http://localhost:8000/health`
3. Check mcp.json has `"type": "sse"` and correct URL

### Connection Issues

**Check logs:**
```bash
# MCP server logs
cat /tmp/mcp_server.log

# Workbench logs
cat ../logs/mcp_server.log
```

**Verify configuration:**
```bash
# Check mcp.json
cat ~/.config/Code/User/mcp.json  # or Codespaces location
jq '.servers."Agent Workbench"' ~/.config/Code/User/mcp.json
```

**Test HTTP endpoint (web environments):**
```bash
curl http://localhost:8000/health
curl http://localhost:8000/sse
```

### Import Errors

**Ensure dependencies are installed:**
```bash
cd /workspaces/Bremen/utils/agent-workbench
.venv/bin/pip install -r mcp-server/mcp_requirements.txt
```

**Verify virtual environment:**
```bash
which python
python --version
```

### Port Conflicts

**Check if port is in use:**
```bash
lsof -i :8000
```

**Use different port:**
```bash
PORT=8001 python server_http.py &
```

Then update mcp.json URL to `http://localhost:8001/sse`

## Advanced Configuration

### Auto-Start in Codespaces

Add to `.devcontainer/devcontainer.json`:
```json
{
  "postStartCommand": "cd /workspaces/Bremen/utils/agent-workbench/mcp-server && python server_http.py > /tmp/mcp_server.log 2>&1 &"
}
```

### Custom Configuration

See [SETUP_GUIDE.md](./SETUP_GUIDE.md) for detailed configuration options and advanced scenarios.

## Support

For detailed troubleshooting and configuration options, see:
- [SETUP_GUIDE.md](./SETUP_GUIDE.md) - Comprehensive setup guide
- [lessons_learned.md](./lessons_learned.md) - Common issues and solutions

For issues:
1. Check environment detection in setup output
2. Verify logs: `/tmp/mcp_server.log` or `../logs/mcp_server.log`
3. Test connectivity based on your environment
4. Re-run setup script: `python setup_github_copilot.py`
