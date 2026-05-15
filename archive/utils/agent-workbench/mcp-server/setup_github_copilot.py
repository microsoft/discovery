#!/usr/bin/env python3
"""
Setup script to configure the Discovery Agent Workbench MCP server for GitHub Copilot.

Automatically detects the environment (local VS Code, Codespaces, etc.) and configures
the appropriate transport mechanism (stdio for local, HTTP/SSE for web-based environments).

Usage:
    python setup_github_copilot.py              # Install with system Python
    python setup_github_copilot.py --venv       # Install with virtual environment
    python setup_github_copilot.py --uninstall  # Remove MCP server configurations
"""

import argparse
import json
import os
import sys
import subprocess
import socket
import shutil
from pathlib import Path

# Virtual environment directory name
VENV_DIR_NAME = ".mcp-venv"


def get_venv_path():
    """Get the path to the virtual environment directory"""
    mcp_server_dir = Path(__file__).parent.resolve()
    return mcp_server_dir / VENV_DIR_NAME


def get_venv_python():
    """Get the Python executable path inside the venv"""
    venv_path = get_venv_path()
    if sys.platform == 'win32':
        return venv_path / "Scripts" / "python.exe"
    else:
        return venv_path / "bin" / "python"


def create_venv():
    """Create a virtual environment for MCP server dependencies"""
    print("[*] Setting up virtual environment...")

    venv_path = get_venv_path()

    # Check if venv already exists
    if venv_path.exists():
        venv_python = get_venv_python()
        if venv_python.exists():
            print(f"   [OK] Virtual environment already exists: {venv_path}")
            return True
        else:
            print(f"   [!] Incomplete venv found, recreating...")
            shutil.rmtree(venv_path)

    try:
        # Create virtual environment
        print(f"   [*] Creating venv at: {venv_path}")
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:
            print(f"   [X] Failed to create venv: {result.stderr}")
            return False

        # Verify venv was created
        venv_python = get_venv_python()
        if not venv_python.exists():
            print(f"   [X] Venv created but Python not found: {venv_python}")
            return False

        print(f"   [OK] Virtual environment created successfully")
        return True

    except subprocess.TimeoutExpired:
        print("   [X] Venv creation timed out")
        return False
    except Exception as e:
        print(f"   [X] Failed to create venv: {e}")
        return False


def remove_venv():
    """Remove the virtual environment"""
    venv_path = get_venv_path()

    if not venv_path.exists():
        print(f"   [*] No virtual environment found at: {venv_path}")
        return True

    try:
        print(f"   [*] Removing virtual environment: {venv_path}")
        shutil.rmtree(venv_path)
        print(f"   [OK] Virtual environment removed")
        return True
    except Exception as e:
        print(f"   [X] Failed to remove venv: {e}")
        return False


def install_dependencies(use_venv=False):
    """Install required Python dependencies from mcp_requirements.txt

    Args:
        use_venv: If True, create and use a virtual environment for dependencies
    """
    print("[*] Checking and installing dependencies...")

    mcp_server_dir = Path(__file__).parent.resolve()
    requirements_file = mcp_server_dir / "mcp_requirements.txt"

    if not requirements_file.exists():
        print(f"   [!] Requirements file not found: {requirements_file}")
        return False

    # Determine which Python to use
    if use_venv:
        # Create venv if needed
        if not create_venv():
            print("   [X] Failed to create virtual environment")
            return False
        python_exe = str(get_venv_python())
        print(f"   [*] Using venv Python: {python_exe}")
    else:
        python_exe = sys.executable
        print(f"   [*] Using system Python: {python_exe}")

    try:
        # Upgrade pip first in venv
        if use_venv:
            subprocess.run(
                [python_exe, "-m", "pip", "install", "--upgrade", "pip", "-q"],
                capture_output=True,
                text=True,
                timeout=60
            )

        # On Windows, install azure-identity with pre-built cryptography wheels first
        # This avoids the OpenSSL build requirement on Windows ARM64
        if sys.platform == 'win32':
            print("   [*] Installing azure-identity with pre-built wheels (Windows)...")
            prebuilt_result = subprocess.run(
                [python_exe, "-m", "pip", "install", "--only-binary=cryptography",
                 "azure-identity", "azure-storage-blob", "-q"],
                capture_output=True,
                text=True,
                timeout=120
            )
            if prebuilt_result.returncode != 0:
                print(f"   [!] Warning: Pre-built install returned: {prebuilt_result.stderr[:200]}")

        # Install remaining dependencies
        result = subprocess.run(
            [python_exe, "-m", "pip", "install", "-r", str(requirements_file), "-q"],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            print("   [OK] Dependencies installed successfully")
            return True
        else:
            print(f"   [!] pip install returned non-zero: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("   [!] Dependency installation timed out")
        return False
    except Exception as e:
        print(f"   [X] Failed to install dependencies: {e}")
        return False


def verify_servers(use_venv=False):
    """Verify that MCP servers can be loaded"""
    print()
    print("[*] Verifying MCP servers can be loaded...")

    mcp_server_dir = Path(__file__).parent.resolve()
    if use_venv:
        python_exe = str(get_venv_python())
    else:
        python_exe = sys.executable

    servers = [
        ("Agent Workbench", "server.py"),
        ("Discovery Management", "discovery_management_server.py")
    ]

    all_ok = True
    for name, script in servers:
        script_path = mcp_server_dir / script
        if not script_path.exists():
            print(f"   [X] {name}: Script not found ({script})")
            all_ok = False
            continue

        try:
            # Verify the server script has valid Python syntax using py_compile
            result = subprocess.run(
                [python_exe, "-m", "py_compile", str(script_path)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(mcp_server_dir)
            )

            if result.returncode == 0:
                print(f"   [OK] {name}: Syntax OK")
            else:
                print(f"   [X] {name}: Syntax error")
                if result.stderr:
                    # Show last line of error
                    error_line = result.stderr.strip().split('\n')[-1]
                    print(f"       Error: {error_line[:80]}")
                all_ok = False

        except subprocess.TimeoutExpired:
            print(f"   [!] {name}: Verification timed out")
            all_ok = False
        except Exception as e:
            print(f"   [X] {name}: {e}")
            all_ok = False

    return all_ok


def detect_environment():
    """Detect the execution environment and determine appropriate configuration"""
    env_info = {
        'is_codespaces': False,
        'is_web_based': False,
        'is_local_vscode': False,
        'is_remote_ssh': False,
        'environment_name': 'unknown'
    }
    
    # Check for Codespaces
    if os.environ.get('CODESPACES') == 'true' or os.environ.get('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN'):
        env_info['is_codespaces'] = True
        env_info['is_web_based'] = True
        env_info['environment_name'] = 'GitHub Codespaces'
    
    # Check for VS Code Server (web-based VS Code)
    elif os.environ.get('VSCODE_IPC_HOOK_CLI') or os.path.exists(Path.home() / '.vscode-server'):
        # Could be remote SSH or web-based
        if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_CLIENT'):
            env_info['is_remote_ssh'] = True
            env_info['environment_name'] = 'VS Code Remote SSH'
        else:
            env_info['is_web_based'] = True
            env_info['environment_name'] = 'VS Code Server (Web)'
    
    # Default to local VS Code
    else:
        env_info['is_local_vscode'] = True
        env_info['environment_name'] = 'Local VS Code'
    
    return env_info

def find_available_port(start_port=8000, max_attempts=10):
    """Find an available port starting from start_port"""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return port
        except OSError:
            continue
    return None

def get_claude_code_config_paths():
    """Get Claude Code MCP configuration paths"""
    paths = []

    # User-level Claude Code config
    claude_config = Path.home() / ".claude.json"
    paths.append(claude_config)

    # Project-level .mcp.json (in current working directory or project root)
    # Try to find project root by looking for common markers
    current_dir = Path.cwd()
    project_markers = ['.git', 'package.json', 'pyproject.toml', 'Cargo.toml']

    project_root = current_dir
    for parent in [current_dir] + list(current_dir.parents):
        if any((parent / marker).exists() for marker in project_markers):
            project_root = parent
            break

    project_mcp = project_root / ".mcp.json"
    paths.append(project_mcp)

    return paths


def get_vscode_settings_paths():
    """Get VS Code user settings.json and mcp.json paths for relevant installations"""
    paths = []

    if sys.platform == 'darwin':
        # settings.json for GitHub Copilot
        paths.append(Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json")
        paths.append(Path.home() / "Library" / "Application Support" / "Code - Insiders" / "User" / "settings.json")
        # mcp.json for VS Code MCP
        paths.append(Path.home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json")
        paths.append(Path.home() / "Library" / "Application Support" / "Code - Insiders" / "User" / "mcp.json")
    elif sys.platform == 'linux':
        # settings.json for GitHub Copilot
        paths.append(Path.home() / ".config" / "Code" / "User" / "settings.json")
        paths.append(Path.home() / ".config" / "Code - Insiders" / "User" / "settings.json")
        # mcp.json for VS Code MCP
        paths.append(Path.home() / ".config" / "Code" / "User" / "mcp.json")
        paths.append(Path.home() / ".config" / "Code - Insiders" / "User" / "mcp.json")
        # CRITICAL: vscode-remote paths (used in Codespaces and Remote SSH)
        vscode_remote_dir = Path.home() / ".vscode-remote" / "data" / "Machine"
        if vscode_remote_dir.exists():
            paths.append(vscode_remote_dir / "settings.json")
            paths.append(vscode_remote_dir / "mcp.json")
        # User data virtual paths (used in Codespaces web UI)
        vscode_user_dir = Path.home() / ".vscode-remote" / "data" / "User"
        if vscode_user_dir.exists():
            paths.append(vscode_user_dir / "mcp.json")
        # Legacy: Check for vscode-server settings (older remote setups)
        vscode_server_dir = Path.home() / ".vscode-server" / "data" / "Machine"
        if vscode_server_dir.exists():
            paths.append(vscode_server_dir / "settings.json")
            paths.append(vscode_server_dir / "mcp.json")
        # User-specific settings in Codespaces
        user_data_dir = Path("/workspaces/.codespaces/.persistedshare")
        if user_data_dir.exists():
            paths.append(user_data_dir / "mcp.json")
    else:  # Windows
        appdata = os.environ.get('APPDATA', '')
        if not appdata:
            print("[X] APPDATA environment variable not found")
            return []
        # settings.json for GitHub Copilot
        paths.append(Path(appdata) / "Code" / "User" / "settings.json")
        paths.append(Path(appdata) / "Code - Insiders" / "User" / "settings.json")
        # mcp.json for VS Code MCP
        paths.append(Path(appdata) / "Code" / "User" / "mcp.json")
        paths.append(Path(appdata) / "Code - Insiders" / "User" / "mcp.json")

    return paths

def start_http_server(port=8000):
    """Start the MCP HTTP server in the background"""
    mcp_server_dir = Path(__file__).parent.resolve()
    http_server_path = mcp_server_dir / "server_http.py"
    python_exe = sys.executable
    
    # Check if server is already running
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            result = s.connect_ex(('localhost', port))
            if result == 0:
                print(f"[OK] HTTP server already running on port {port}")
                return port
    except:
        pass

    # Start the server
    try:
        log_file = Path("/tmp/mcp_server.log")
        pid_file = Path("/tmp/mcp_server.pid")

        with open(log_file, 'w') as log:
            process = subprocess.Popen(
                [python_exe, str(http_server_path)],
                stdout=log,
                stderr=log,
                env={**os.environ, 'PORT': str(port)},
                start_new_session=True
            )

        # Save PID
        with open(pid_file, 'w') as f:
            f.write(str(process.pid))

        # Wait a bit and verify
        import time
        time.sleep(2)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            result = s.connect_ex(('localhost', port))
            if result == 0:
                print(f"[OK] Started HTTP server on port {port} (PID: {process.pid})")
                print(f"     Logs: {log_file}")
                return port
            else:
                print(f"[!] Server started but not responding on port {port}")
                return None

    except Exception as e:
        print(f"[X] Failed to start HTTP server: {e}")
        return None

def get_mcp_server_config(env_info, server_type='workbench', use_venv=False):
    """Get the MCP server configuration based on environment and server type

    Args:
        env_info: Environment information dictionary
        server_type: 'workbench' for Agent Workbench or 'management' for Discovery Project Management
        use_venv: If True, use the virtual environment Python
    """
    mcp_server_dir = Path(__file__).parent.resolve()
    if use_venv:
        python_exe = str(get_venv_python())
    else:
        python_exe = sys.executable
    
    # Select the appropriate server script
    if server_type == 'management':
        server_script = mcp_server_dir / "discovery_management_server.py"
    else:
        server_script = mcp_server_dir / "server.py"
    
    # Determine which server and transport to use
    # NOTE: For Codespaces, stdio works better than SSE for MCP servers
    # The web-based VS Code interface handles stdio transport correctly
    az_cli_flag = os.environ.get('AGENT_WORKBENCH_ENABLE_AZURE_CLI', '1')
    if env_info['is_web_based'] and not env_info['is_codespaces']:
        # Use HTTP/SSE only for non-Codespaces web environments
        port = find_available_port(8000)
        if port is None:
            print("[!] No available ports found, defaulting to 8000")
            port = 8000

        # Start the HTTP server
        actual_port = start_http_server(port)
        if actual_port is None:
            print("[!] Failed to start HTTP server, falling back to stdio config")
            config = {
                "type": "stdio",
                "command": str(python_exe),
                "args": [str(server_script)],
                "env": {
                    "PYTHONIOENCODING": "utf-8",
                    "AGENT_WORKBENCH_ENABLE_AZURE_CLI": az_cli_flag
                }
            }
        else:
            config = {
                "type": "sse",
                "url": f"http://localhost:{actual_port}/sse"
            }
    else:
        # Use stdio for local VS Code and Codespaces
        config = {
            "type": "stdio",
            "command": str(python_exe),
            "args": [str(server_script)],
            "env": {
                "PYTHONIOENCODING": "utf-8",
                "AGENT_WORKBENCH_ENABLE_AZURE_CLI": az_cli_flag
            }
        }
    
    # Add common metadata (only for stdio transport, not SSE)
    # Note: enabledTools is not needed for MCP servers, they auto-discover tools
    # Keeping this for backward compatibility with older configurations
    if config.get('type') != 'sse':
        config["enabledTools"] = [
            "list_agents",
            "get_agent_config",
            "switch_agent",
            "get_discovery_config",
            "list_docker_containers",
            "set_agent_catalog",
            "upload_agent_catalog",
            "add_discovery_profile",
            "delete_discovery_profile",
            "set_discovery_config",
            "reload_workbench",
            "list_profiles",
            "switch_profile",
            "get_supercomputer_info",
            "validate_agent_definition",
            "generate_mermaid_diagram",
            "generate_mermaid_svg",
            "list_published_agents",
            "list_published_tools",
            "get_published_agent_details",
            "publish_tool",
            "publish_tool_agent",
            "publish_tool_from_catalog",
            "publish_agent_from_catalog",
            "get_error_stats",
            "submit_job",
            "get_job_status"
        ]
    
    return config

def setup_github_copilot(use_venv=False):
    """Setup MCP servers in VS Code settings for GitHub Copilot and mcp.json"""
    print("[*] Discovery MCP Servers Setup (VS Code / GitHub Copilot)")
    print("=" * 80)
    print()

    # Detect environment
    env_info = detect_environment()
    print(f"[*] Environment detected: {env_info['environment_name']}")
    print(f"    Web-based: {env_info['is_web_based']}")
    print(f"    Codespaces: {env_info['is_codespaces']}")
    print()

    settings_paths = get_vscode_settings_paths()

    if not settings_paths:
        print("[X] Could not determine VS Code settings path")
        return False

    # Configure both servers
    servers_to_configure = [
        {
            'name': 'Agent Workbench',
            'type': 'workbench',
            'description': 'Scientific job execution and computational workflows'
        },
        {
            'name': 'Discovery Project Management',
            'type': 'management',
            'description': 'Configuration, catalog management, and tool publishing'
        }
    ]

    # Get configurations for both servers
    server_configs = {}
    for server in servers_to_configure:
        config = get_mcp_server_config(env_info, server['type'], use_venv=use_venv)
        server_configs[server['name']] = config
        print(f"[+] {server['name']}:")
        print(f"    Description: {server['description']}")
        print(f"    Transport: {config.get('type', 'stdio')}")
        if config.get('type') == 'sse':
            print(f"    URL: {config.get('url')}")
        else:
            print(f"    Script: {config.get('args', ['N/A'])[0]}")
        print()
    processed_paths = []
    errors = []

    for settings_path in settings_paths:
        try:
            file_name = settings_path.name
            print(f"[*] Processing: {settings_path}")

            # Load existing file or create new
            if settings_path.exists():
                try:
                    with open(settings_path, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                    print("    [OK] Loaded existing file")
                except Exception as e:
                    print(f"    [!] Error reading file: {e}")
                    print("        Will create new file")
                    settings = {}
            else:
                settings = {}
                print("    [+] Creating new file")
                settings_path.parent.mkdir(parents=True, exist_ok=True)

            # Handle mcp.json differently from settings.json
            if file_name == "mcp.json":
                # mcp.json format: { "servers": { "server-name": {...} } }
                if 'servers' not in settings:
                    settings['servers'] = {}

                # Configure both servers
                for server_name, server_config in server_configs.items():
                    if server_name in settings['servers']:
                        print(f"    [!] Server '{server_name}' already exists in servers")
                        print("        Updating configuration...")
                    else:
                        print(f"    [+] Adding new server to servers: {server_name}")

                    settings['servers'][server_name] = server_config

            else:  # settings.json
                # GitHub Copilot configuration in settings.json
                if 'github.copilot.chat.mcpServers' not in settings:
                    settings['github.copilot.chat.mcpServers'] = {}

                # Also register under generic chat.mcpServers
                if 'chat.mcpServers' not in settings:
                    settings['chat.mcpServers'] = {}

                # Configure both servers
                for server_name, server_config in server_configs.items():
                    if server_name in settings['github.copilot.chat.mcpServers']:
                        print(f"    [!] Server '{server_name}' already exists in github.copilot.chat.mcpServers")
                        print("        Updating configuration...")
                    else:
                        print(f"    [+] Adding new server to github.copilot.chat.mcpServers: {server_name}")

                    settings['github.copilot.chat.mcpServers'][server_name] = server_config

                    if server_name in settings['chat.mcpServers']:
                        print(f"    [!] Server '{server_name}' already exists in chat.mcpServers")
                        print("        Updating configuration...")
                    else:
                        print(f"    [+] Adding new server to chat.mcpServers: {server_name}")

                    # For chat.mcpServers, we need different formats based on transport
                    if server_config.get('type') == 'sse':
                        settings['chat.mcpServers'][server_name] = {
                            "type": "sse",
                            "url": server_config['url']
                        }
                    else:
                        cwd = str(Path(__file__).parent.resolve())
                        settings['chat.mcpServers'][server_name] = {
                            "type": "command",
                            "command": server_config['command'],
                            "args": server_config['args'],
                            "cwd": cwd,
                            "env": server_config['env']
                        }

            # Save the file
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2)
            print(f"    [OK] File saved: {settings_path}")
            processed_paths.append(settings_path)

        except Exception as e:
            print(f"    [X] Failed to save settings at {settings_path}: {e}")
            errors.append((settings_path, str(e)))

        print()

    if not processed_paths:
        print("[X] Failed to update any VS Code settings files")
        return False

    print("[OK] Updated settings files:")
    for path in processed_paths:
        print(f"     - {path}")
    if errors:
        print()
        print("[!] Some settings could not be updated:")
        for path, err in errors:
            print(f"     - {path}: {err}")
    print()
    print("=" * 80)
    print("[OK] VS Code / GitHub Copilot MCP Configuration Complete!")
    print()
    print("Configured Servers:")
    for server_name, server_config in server_configs.items():
        print(f"\n   [+] {server_name}")
        print(f"       Transport: {server_config.get('type', 'stdio')}")
        if server_config.get('type') == 'sse':
            print(f"       URL: {server_config.get('url')}")
        else:
            if server_config.get('args'):
                print(f"       Script: {server_config['args'][0]}")
    print()
    print(f"   Environment: {env_info['environment_name']}")
    print()

    # For Codespaces, provide JSON to copy-paste
    if env_info['is_codespaces']:
        print("=" * 80)
        print("FOR CODESPACES: Copy this configuration")
        print("=" * 80)
        print()
        print("If servers don't appear after reload, manually add them to:")
        print("vscode-userdata:/User/mcp.json")
        print()
        print("Add these entries to the 'servers' object:")
        print()
        print(json.dumps(server_configs, indent=2))
        print()
        print("=" * 80)
        print()

    print("Next Steps for VS Code / GitHub Copilot:")
    print("   1. Reload VS Code window (Ctrl+Shift+P -> 'Developer: Reload Window')")
    if env_info['is_codespaces']:
        print()
        print("   [!] If servers don't appear after reload:")
        print("   2. Open: vscode-userdata:/User/mcp.json (Ctrl+P, paste the path)")
        print("   3. Add the server configurations shown above")
        print("   4. Save and reload window again")
        print()
    print("   2. Open GitHub Copilot Chat")
    print("   3. Type '@' in chat to see available MCP tools from both servers")
    print("   4. Or just ask: 'What agents are available in the workbench?'")
    if env_info['is_codespaces']:
        print()
        print("Codespaces Notes:")
        print("   - Both servers use stdio transport (reliable in Codespaces)")
        print("   - Config files updated in ~/.vscode-remote/data/Machine/")
        print("   - May need manual update to vscode-userdata:/User/mcp.json")
    print()

    return True

def setup_claude_code(use_venv=False):
    """Setup MCP servers for Claude Code

    Args:
        use_venv: If True, use the virtual environment Python
    """
    print()
    print("=" * 80)
    print("[*] Setting up Claude Code MCP Configuration")
    print("=" * 80)
    print()

    config_paths = get_claude_code_config_paths()

    # Get server configurations (Claude Code uses stdio transport)
    mcp_server_dir = Path(__file__).parent.resolve()
    if use_venv:
        python_exe = str(get_venv_python())
    else:
        python_exe = sys.executable
    az_cli_flag = os.environ.get('AGENT_WORKBENCH_ENABLE_AZURE_CLI', '1')

    # Claude Code MCP server format
    server_configs = {
        "agent-workbench": {
            "command": str(python_exe),
            "args": [str(mcp_server_dir / "server.py")],
            "env": {
                "PYTHONIOENCODING": "utf-8",
                "AGENT_WORKBENCH_ENABLE_AZURE_CLI": az_cli_flag
            }
        },
        "discovery-management": {
            "command": str(python_exe),
            "args": [str(mcp_server_dir / "discovery_management_server.py")],
            "env": {
                "PYTHONIOENCODING": "utf-8",
                "AGENT_WORKBENCH_ENABLE_AZURE_CLI": az_cli_flag
            }
        }
    }

    processed_paths = []
    errors = []

    for config_path in config_paths:
        try:
            print(f"[*] Processing: {config_path}")

            # Load existing config or create new
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                    print("    [OK] Loaded existing config")
                except json.JSONDecodeError:
                    print("    [!] Invalid JSON, creating new config")
                    config = {}
            else:
                config = {}
                print("    [+] Creating new config file")
                config_path.parent.mkdir(parents=True, exist_ok=True)

            # Claude Code uses "mcpServers" key
            if "mcpServers" not in config:
                config["mcpServers"] = {}

            # Add server configurations
            for server_name, server_config in server_configs.items():
                if server_name in config["mcpServers"]:
                    print(f"    [!] Updating existing server: {server_name}")
                else:
                    print(f"    [+] Adding server: {server_name}")
                config["mcpServers"][server_name] = server_config

            # Save the config
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            print(f"    [OK] Saved: {config_path}")
            processed_paths.append(config_path)

        except Exception as e:
            print(f"    [X] Failed: {e}")
            errors.append((config_path, str(e)))

        print()

    if processed_paths:
        print("[OK] Claude Code configuration complete!")
        print()
        print("Updated config files:")
        for path in processed_paths:
            print(f"   - {path}")
        print()
        print("Next Steps for Claude Code:")
        print("   1. Restart Claude Code (or run 'claude' again)")
        print("   2. The MCP tools should now be available")
        print("   3. Try: 'Using the agent workbench MCP server, list available agents'")
        return True
    else:
        print("[X] Failed to configure Claude Code")
        return False


def uninstall_mcp_servers():
    """Remove MCP server configurations from Claude Code and VS Code"""
    print()
    print("=" * 80)
    print("[*] Uninstalling Discovery MCP Servers")
    print("=" * 80)
    print()

    servers_to_remove = ["agent-workbench", "discovery-management", "Agent Workbench", "Discovery Project Management"]
    removed_count = 0
    errors = []

    # Remove from Claude Code configs
    print("[*] Removing from Claude Code configurations...")
    claude_paths = get_claude_code_config_paths()

    for config_path in claude_paths:
        if not config_path.exists():
            continue

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            if "mcpServers" not in config:
                continue

            removed_any = False
            for server_name in servers_to_remove:
                if server_name in config["mcpServers"]:
                    del config["mcpServers"][server_name]
                    print(f"   [OK] Removed '{server_name}' from {config_path}")
                    removed_any = True
                    removed_count += 1

            if removed_any:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)

        except Exception as e:
            errors.append((config_path, str(e)))
            print(f"   [X] Error processing {config_path}: {e}")

    # Remove from VS Code configs
    print()
    print("[*] Removing from VS Code configurations...")
    vscode_paths = get_vscode_settings_paths()

    for settings_path in vscode_paths:
        if not settings_path.exists():
            continue

        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            removed_any = False
            file_name = settings_path.name

            if file_name == "mcp.json":
                # mcp.json format
                if "servers" in settings:
                    for server_name in servers_to_remove:
                        if server_name in settings["servers"]:
                            del settings["servers"][server_name]
                            print(f"   [OK] Removed '{server_name}' from {settings_path}")
                            removed_any = True
                            removed_count += 1
            else:
                # settings.json format
                for key in ["github.copilot.chat.mcpServers", "chat.mcpServers"]:
                    if key in settings:
                        for server_name in servers_to_remove:
                            if server_name in settings[key]:
                                del settings[key][server_name]
                                print(f"   [OK] Removed '{server_name}' from {key} in {settings_path}")
                                removed_any = True
                                removed_count += 1

            if removed_any:
                with open(settings_path, 'w', encoding='utf-8') as f:
                    json.dump(settings, f, indent=2)

        except Exception as e:
            errors.append((settings_path, str(e)))
            print(f"   [X] Error processing {settings_path}: {e}")

    # Remove virtual environment if it exists
    print()
    print("[*] Checking for virtual environment...")
    remove_venv()

    # Summary
    print()
    print("=" * 80)
    if removed_count > 0:
        print(f"[OK] Uninstall complete! Removed {removed_count} server configuration(s)")
    else:
        print("[*] No MCP server configurations found to remove")

    if errors:
        print()
        print("[!] Some errors occurred:")
        for path, err in errors:
            print(f"   - {path}: {err}")

    print("=" * 80)
    print()
    print("Next Steps:")
    print("   1. Restart Claude Code and/or VS Code to apply changes")
    print("   2. MCP tools will no longer be available")
    print()

    return removed_count > 0 or len(errors) == 0


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Setup or uninstall Discovery MCP servers for Claude Code and VS Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python setup_github_copilot.py              # Install with system Python
    python setup_github_copilot.py --venv       # Install with virtual environment
    python setup_github_copilot.py --uninstall  # Remove MCP server configurations
        """
    )
    parser.add_argument(
        "--venv",
        action="store_true",
        help="Create and use a virtual environment for MCP server dependencies"
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove MCP server configurations from Claude Code and VS Code"
    )
    return parser.parse_args()


def main():
    """Main entry point"""
    print()

    args = parse_args()

    try:
        # Handle uninstall mode
        if args.uninstall:
            success = uninstall_mcp_servers()
            sys.exit(0 if success else 1)

        # Install mode
        use_venv = args.venv

        if use_venv:
            print("[*] Using virtual environment mode")
        else:
            print("[*] Using system Python mode")
        print()

        # Install dependencies first
        print("=" * 80)
        if not install_dependencies(use_venv=use_venv):
            print("[X] Failed to install dependencies")
            sys.exit(1)
        print()

        # Setup VS Code / GitHub Copilot
        success_vscode = setup_github_copilot(use_venv=use_venv)

        # Setup Claude Code
        success_claude = setup_claude_code(use_venv=use_venv)

        # Verify servers can be loaded
        servers_ok = verify_servers(use_venv=use_venv)

        if success_vscode or success_claude:
            print()
            print("=" * 80)
            print("[OK] Setup completed!")
            if success_vscode:
                print("   [OK] VS Code / GitHub Copilot: Configured")
            if success_claude:
                print("   [OK] Claude Code: Configured")
            if servers_ok:
                print("   [OK] Server verification: Passed")
            else:
                print("   [!] Server verification: Some issues detected")
            if use_venv:
                print(f"   [*] Virtual environment: {get_venv_path()}")
            print("=" * 80)
            print()
            print("IMPORTANT: Restart Claude Code or VS Code to load the MCP servers")
            sys.exit(0)
        else:
            print("[X] Setup failed")
            sys.exit(1)

    except Exception as e:
        print(f"[X] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
