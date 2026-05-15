# Discovery Agent Workbench MCP Server Setup Guide

## Overview

The Discovery Agent Workbench MCP Server provides Model Context Protocol (MCP) tools for interacting with Azure Discovery Supercomputer resources. This setup script configures MCP servers for:

- **VS Code / GitHub Copilot** - MCP integration for GitHub Copilot Chat
- **Claude Code** - MCP integration for Anthropic's Claude Code CLI

The servers provide capabilities for:
- Submitting and monitoring computational jobs
- Managing Azure Discovery configurations
- Publishing tools and agents to Azure
- Downloading job results and logs

## Prerequisites

Before running the setup script, ensure you have:

1. **Python 3.8+** installed and available in your PATH
2. **Azure CLI** installed and authenticated (`az login`)
3. **Git** (to clone the repository)

### Verify Prerequisites

```bash
# Check Python version
python --version  # Should be 3.8 or higher

# Check Azure CLI
az --version
az account show  # Should show your logged-in account
```

## Quick Start

### 1. Navigate to the MCP Server Directory

```bash
# From the repository root
cd utils/agent-workbench/mcp-server
```

### 2. Run the Setup Script

```bash
# Standard installation (uses system Python)
python setup_github_copilot.py

# Installation with virtual environment (recommended for isolation)
python setup_github_copilot.py --venv

# Uninstall MCP servers
python setup_github_copilot.py --uninstall
```

The script will automatically:
1. Install required Python dependencies from `mcp_requirements.txt`
2. Detect your environment (local VS Code, Codespaces, Remote SSH)
3. Configure VS Code / GitHub Copilot MCP settings
4. Configure Claude Code MCP settings
5. Verify that servers can be loaded
6. Provide next steps

### 3. Restart Your IDE/CLI

**For VS Code / GitHub Copilot:**
- Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on macOS)
- Type "Developer: Reload Window" and press Enter

**For Claude Code:**
- Close the current session (`/quit` or `Ctrl+C`)
- Start a new session (`claude`)

## What Gets Configured

### Two MCP Servers

The setup configures two complementary MCP servers:

| Server | Purpose | Key Tools |
|--------|---------|-----------|
| **Agent Workbench** | Job execution and computational workflows | `submit_job`, `get_job_results`, `list_nodepools`, `create_investigation` |
| **Discovery Management** | Configuration and tool publishing | `list_profiles`, `publish_tool`, `get_supercomputer_info`, `validate_agent_definition` |

### Configuration Files Updated

**For VS Code / GitHub Copilot:**
- `%APPDATA%\Code\User\settings.json` (Windows)
- `%APPDATA%\Code\User\mcp.json` (Windows)
- `~/.config/Code/User/settings.json` (Linux)
- `~/.config/Code/User/mcp.json` (Linux)
- `~/Library/Application Support/Code/User/settings.json` (macOS)
- `~/Library/Application Support/Code/User/mcp.json` (macOS)

**For Claude Code:**
- `~/.claude.json` (user-level configuration)
- `.mcp.json` (project-level configuration in repository root)

## Environment Support

### Local VS Code (Windows/macOS/Linux)
- **Transport**: stdio (direct process communication)
- **No server needed**: MCP runs as a subprocess

### GitHub Codespaces
- **Transport**: stdio (works reliably in Codespaces)
- **Config files**: Updated in `~/.vscode-remote/data/Machine/`

### VS Code Remote SSH
- **Transport**: stdio (over SSH tunnel)
- **Works like**: Local VS Code through SSH connection

### Web-based VS Code (non-Codespaces)
- **Transport**: HTTP/SSE (web-compatible)
- **Auto-starts**: HTTP server in background on port 8000+

## Command Line Options

| Option | Description |
|--------|-------------|
| (none) | Standard installation using system Python |
| `--venv` | Create and use a virtual environment for dependencies |
| `--uninstall` | Remove MCP server configurations and clean up |

### Virtual Environment Mode (`--venv`)

Using `--venv` creates an isolated Python environment for MCP server dependencies:

```bash
python setup_github_copilot.py --venv
```

Benefits:
- Isolates MCP dependencies from your system Python
- Prevents version conflicts with other projects
- Easy cleanup (just delete the `.mcp-venv` directory)

The virtual environment is created at `utils/agent-workbench/mcp-server/.mcp-venv/`.

### Uninstall Mode (`--uninstall`)

To remove the MCP server configurations:

```bash
python setup_github_copilot.py --uninstall
```

This will:
1. Remove MCP server entries from Claude Code configs (`~/.claude.json`, `.mcp.json`)
2. Remove MCP server entries from VS Code configs (`settings.json`, `mcp.json`)
3. Remove the virtual environment if it exists (`.mcp-venv/`)

After uninstalling, restart Claude Code and/or VS Code to apply changes.

## Troubleshooting

### Dependencies Failed to Install

The setup script automatically handles Windows ARM64 by using pre-built wheels for cryptography.
If dependency installation still fails, try manually:

```bash
# Install azure-identity with pre-built wheels
pip install --only-binary=cryptography azure-identity azure-storage-blob

# Then install remaining dependencies
pip install -r mcp_requirements.txt
```

### Server Verification Failed

Check the server logs:

```bash
# View the MCP server log
cat utils/agent-workbench/logs/mcp_server.log

# Test server import manually
cd utils/agent-workbench/mcp-server
python -c "import sys; sys.path.insert(0, '..'); import server; print('OK')"
```

### MCP Tools Not Appearing

1. **Restart your IDE/CLI** - Required after configuration changes
2. **Check configuration files** - Ensure `mcpServers` key exists
3. **Verify Python path** - The configured Python executable must be accessible

For VS Code, check the MCP output panel:
- `View` > `Output` > Select "MCP" from dropdown

### Azure Authentication Issues

Ensure you're logged into Azure CLI:

```bash
az login
az account set --subscription "YOUR_SUBSCRIPTION_NAME"
```

## Manual Configuration

If automatic setup fails, you can manually configure the MCP servers:

### For Claude Code (~/.claude.json or .mcp.json)

```json
{
  "mcpServers": {
    "agent-workbench": {
      "command": "python",
      "args": ["/path/to/utils/agent-workbench/mcp-server/server.py"],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    },
    "discovery-management": {
      "command": "python",
      "args": ["/path/to/utils/agent-workbench/mcp-server/discovery_management_server.py"],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### For VS Code (mcp.json)

```json
{
  "servers": {
    "Agent Workbench": {
      "type": "stdio",
      "command": "python",
      "args": ["/path/to/utils/agent-workbench/mcp-server/server.py"],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

## Available Tools

### Agent Workbench Tools

| Tool | Description |
|------|-------------|
| `create_investigation` | Create a new investigation for organizing work |
| `list_published_agents_and_tools` | Discover available computational tools |
| `get_published_agent_usage` | Get usage instructions for a specific agent |
| `list_nodepools` | List available compute nodepools |
| `submit_job` | Submit a job to the Discovery Supercomputer |
| `get_job_logs` | Retrieve execution logs for a job |
| `get_job_results` | Download results from a completed job |
| `cancel_job` | Cancel a running job |
| `write_organized_file` | Write files to organized investigation directories |
| `upload_input_files` | Upload input files to Azure Storage |
| `lessons_learned` | Track insights and best practices |

### Discovery Management Tools

| Tool | Description |
|------|-------------|
| `list_profiles` | List available configuration profiles |
| `switch_profile` | Switch to a different profile |
| `get_discovery_config` | Get current Discovery configuration |
| `get_supercomputer_info` | Get supercomputer hardware info |
| `publish_tool` | Deploy a tool to Azure Discovery |
| `publish_tool_agent` | Deploy an agent with its tool |
| `validate_agent_definition` | Validate YAML agent definitions |
| `generate_mermaid_diagram` | Generate workflow diagrams |

## Support

For issues or questions:
1. Check the logs in `utils/agent-workbench/logs/`
2. Verify environment detection in setup output
3. Re-run setup script: `python setup_github_copilot.py`
4. Open an issue in the repository with error details
