"""Dynamic VS Code layer builder for container images.

Builds a Docker layer that adds VS Code CLI and tunnel helper script
to any existing container image. This allows interactive debugging
without requiring tool publishers to modify their images.

Adapted from utils/supercomputer-cli/discovery/src/discovery/poll/vscode_layer.py
"""
from __future__ import annotations
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path
from textwrap import dedent
from typing import Optional, Callable

from .models import TunnelResult


# VS Code CLI download URL (Alpine Linux x64 build - works in most containers)
VSCODE_CLI_URL = "https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64"

# Where scripts are placed in container
VSCODE_CLI_PATH = "/usr/local/bin/code"
TUNNEL_SCRIPT_PATH = "/usr/local/bin/start-vscode-tunnel.sh"


class VSCodeLayerBuilder:
    """Builds Docker layers with VS Code CLI for interactive debugging."""
    
    def __init__(self, logger: Optional[Callable[[str], None]] = None):
        self._log = logger or (lambda msg: None)
    
    def download_vscode_cli(self, dest_dir: Path) -> Path:
        """Download and extract VS Code CLI binary.
        
        Returns path to the 'code' binary.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        archive = dest_dir / "vscode-cli.tar.gz"
        
        self._log(f"Downloading VS Code CLI from {VSCODE_CLI_URL}")
        urllib.request.urlretrieve(VSCODE_CLI_URL, archive)
        
        bin_path: Optional[Path] = None
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                base_name = os.path.basename(member.name)
                if base_name in {"code", "code-server"} and member.isfile():
                    tf.extract(member, dest_dir)
                    extracted = dest_dir / member.name
                    final_path = dest_dir / "code"
                    shutil.move(str(extracted), final_path)
                    bin_path = final_path
                    break
        
        if not bin_path or not bin_path.exists():
            raise RuntimeError("VS Code CLI binary not found in archive")
        
        bin_path.chmod(0o755)
        self._log(f"VS Code CLI extracted to {bin_path}")
        
        # Cleanup archive
        archive.unlink(missing_ok=True)
        
        return bin_path
    
    def create_tunnel_script(self, dest_dir: Path) -> Path:
        """Create the tunnel startup helper script."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        script = dest_dir / "start-vscode-tunnel.sh"
        script.write_text(dedent('''
            #!/usr/bin/env bash
            set -euo pipefail
            
            if [[ $# -lt 2 ]]; then
                echo "Usage: $0 <tunnel_id> <token>" >&2
                exit 1
            fi
            
            tunnel_id="$1"
            token="$2"
            log_file="${VS_CODE_TUNNEL_LOG:-/tmp/vscode-tunnel.log}"
            
            echo "Starting VS Code tunnel: ${tunnel_id}"
            echo "Log file: ${log_file}"
            
            # Background the VS Code tunnel
            nohup /usr/local/bin/code tunnel --tunnel-id "${tunnel_id}" --host-token "${token}" \
                >>"${log_file}" 2>&1 &
            
            echo "VS Code tunnel started in background (PID: $!)"
        ''').strip() + "\n", encoding="utf-8")
        script.chmod(0o755)
        return script
    
    def prepare_layer_context(self, base_image: str, dest_dir: Path) -> Path:
        """Prepare a Docker build context that layers VS Code onto base image.
        
        Args:
            base_image: Full image reference (registry/image:tag)
            dest_dir: Directory to create build context in
            
        Returns:
            Path to generated Dockerfile
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        bin_dir = dest_dir / "bin"
        bin_dir.mkdir(exist_ok=True)
        
        # Download VS Code CLI
        self.download_vscode_cli(bin_dir)
        
        # Create tunnel script
        self.create_tunnel_script(bin_dir)
        
        # Generate Dockerfile
        dockerfile = dest_dir / "Dockerfile"
        dockerfile.write_text(dedent(f'''
            # Auto-generated: VS Code layer for interactive debugging
            FROM {base_image}
            
            # Add VS Code CLI binary
            COPY --chmod=755 bin/code /usr/local/bin/code
            
            # Add tunnel startup script
            COPY --chmod=755 bin/start-vscode-tunnel.sh /usr/local/bin/start-vscode-tunnel.sh
        ''').strip() + "\n", encoding="utf-8")
        
        self._log(f"Created VS Code layer context in {dest_dir}")
        return dockerfile
    
    def build_tunnel_command(self, user_command: str, 
                             tunnel: TunnelResult) -> str:
        """Build command that starts tunnel then runs user command.
        
        Args:
            user_command: Original command to run
            tunnel: Tunnel with token
            
        Returns:
            Modified command string
        """
        if not tunnel.token or not tunnel.token.value:
            raise ValueError("Tunnel token required")
        
        import shlex
        tunnel_id = shlex.quote(tunnel.tunnel_id)
        token = shlex.quote(tunnel.token.value)
        
        return (
            f"sh -c '{TUNNEL_SCRIPT_PATH} {tunnel_id} {token}; {user_command}'"
        )


def generate_tunnel_wrapper_code(tunnel_or_name, 
                                  timeout_minutes: int = 30) -> str:
    """Generate Python code to inject at start of script for tunnel setup.
    
    This is used when we can't modify the container image but can modify
    the script being executed. Downloads VS Code CLI at runtime and starts
    a proper VS Code tunnel that appears in Remote Explorer.
    
    Args:
        tunnel_or_name: Either a TunnelResult object or a string tunnel name.
                       With VS Code CLI approach, only the name is needed.
        timeout_minutes: How long to wait for user connection before aborting.
        
    Returns:
        Python code string to prepend to the script.
    """
    # Support both TunnelResult objects and plain string names
    if isinstance(tunnel_or_name, str):
        tunnel_name = tunnel_or_name
    elif hasattr(tunnel_or_name, 'tunnel_id'):
        # TunnelResult object - extract just the name part
        tunnel_name = tunnel_or_name.tunnel_id.split('.')[0] if '.' in tunnel_or_name.tunnel_id else tunnel_or_name.tunnel_id
    else:
        raise TypeError(f"Expected TunnelResult or str, got {type(tunnel_or_name)}")
    
    return dedent(f'''
        # ============ VS CODE TUNNEL WRAPPER (Auto-injected) ============
        # Full-featured interactive debugging with VS Code CLI tunnel
        # Version: 2026-01-03-v4 (switched to code tunnel for proper VS Code Remote)
        import subprocess as _subprocess
        import os as _os
        import sys as _sys
        import time as _time
        import urllib.request as _urllib_request
        import shutil as _shutil
        import tarfile as _tarfile
        import atexit as _atexit
        import threading as _threading
        import re as _re

        _TUNNEL_NAME = "{tunnel_name}"
        _TIMEOUT_MINUTES = {timeout_minutes}
        _LOG_FILE = "/tmp/vscode-tunnel.log"

        # VS Code CLI download URL (Alpine Linux x64 - statically linked, works everywhere)
        _VSCODE_CLI_URL = "https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64"
        _VSCODE_CLI_PATH = "/tmp/vscode-cli/code"
        _DEBUGPY_PORT = 5678

        def _log(msg):
            print(f"[tunnel] {{msg}}", flush=True)

        def _download_vscode_cli():
            """Download VS Code CLI if not available."""
            # Check if code CLI is already in PATH
            if _shutil.which("code"):
                code_path = _shutil.which("code")
                # Verify it's the CLI, not just the desktop app
                try:
                    result = _subprocess.run([code_path, "tunnel", "--help"], 
                                           capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        _log("Using system VS Code CLI")
                        return code_path
                except:
                    pass
            
            # Check if we already downloaded it
            if _os.path.exists(_VSCODE_CLI_PATH):
                _log("Using cached VS Code CLI")
                return _VSCODE_CLI_PATH
            
            _log("Downloading VS Code CLI...")
            _os.makedirs("/tmp/vscode-cli", exist_ok=True)
            archive_path = "/tmp/vscode-cli/vscode-cli.tar.gz"
            
            try:
                _urllib_request.urlretrieve(_VSCODE_CLI_URL, archive_path)
                
                # Extract the tarball
                with _tarfile.open(archive_path, "r:gz") as tf:
                    for member in tf.getmembers():
                        base_name = _os.path.basename(member.name)
                        if base_name == "code" and member.isfile():
                            tf.extract(member, "/tmp/vscode-cli")
                            extracted = _os.path.join("/tmp/vscode-cli", member.name)
                            if extracted != _VSCODE_CLI_PATH:
                                _shutil.move(extracted, _VSCODE_CLI_PATH)
                            break
                
                if _os.path.exists(_VSCODE_CLI_PATH):
                    _os.chmod(_VSCODE_CLI_PATH, 0o755)
                    _log(f"VS Code CLI downloaded to {{_VSCODE_CLI_PATH}}")
                    
                    # Cleanup archive
                    try:
                        _os.remove(archive_path)
                    except:
                        pass
                    
                    return _VSCODE_CLI_PATH
                else:
                    _log("Could not find 'code' binary in archive")
                    return None
                    
            except Exception as e:
                _log(f"Failed to download VS Code CLI: {{e}}")
                return None

        def _start_vscode_tunnel(cli_path):
            """Start VS Code tunnel and return the auth URL if needed."""
            _log(f"Starting VS Code tunnel: {{_TUNNEL_NAME}}")
            
            with open(_LOG_FILE, "w") as log:
                log.write(f"Starting VS Code tunnel at {{_time.strftime('%Y-%m-%d %H:%M:%S')}}\\n")
                log.write(f"Tunnel name: {{_TUNNEL_NAME}}\\n")
            
            # Start the tunnel process
            # Use --accept-server-license-terms to skip license prompt
            proc = _subprocess.Popen(
                [cli_path, "tunnel", "--accept-server-license-terms", "--name", _TUNNEL_NAME],
                stdout=_subprocess.PIPE,
                stderr=_subprocess.STDOUT,
                text=True,
                bufsize=1  # Line buffered
            )
            
            auth_url = None
            auth_code = None
            tunnel_ready = False
            start_time = _time.time()
            
            # Read output looking for either auth URL or tunnel ready message
            # Timeout after 60 seconds of waiting for initial output
            while (_time.time() - start_time) < 60:
                try:
                    # Check if process died
                    if proc.poll() is not None:
                        remaining = proc.stdout.read()
                        with open(_LOG_FILE, "a") as log:
                            log.write(remaining)
                        _log(f"VS Code tunnel process exited with code {{proc.returncode}}")
                        break
                    
                    # Non-blocking read with select would be better, but this works
                    import select
                    if hasattr(select, 'select'):
                        readable, _, _ = select.select([proc.stdout], [], [], 1.0)
                        if not readable:
                            continue
                    
                    line = proc.stdout.readline()
                    if not line:
                        _time.sleep(0.1)
                        continue
                    
                    # Log the line
                    with open(_LOG_FILE, "a") as log:
                        log.write(line)
                    
                    # Check for device code auth URL
                    # Looks like: "To grant access to the server, please log into https://github.com/login/device and use code XXXX-XXXX"
                    # Or Microsoft: "To sign in, use a web browser to open https://microsoft.com/devicelogin and enter the code XXXXXXXX"
                    if "microsoft.com/devicelogin" in line or "github.com/login/device" in line:
                        auth_url = _re.search(r'https://[^\\s]+', line)
                        auth_url = auth_url.group(0) if auth_url else None
                        code_match = _re.search(r'code\\s+([A-Z0-9]{{4}}-[A-Z0-9]{{4}}|[A-Z0-9]{{8,}})', line, _re.IGNORECASE)
                        auth_code = code_match.group(1) if code_match else None
                        if auth_url:
                            _log(f"Auth required: {{auth_url}}")
                            if auth_code:
                                _log(f"Auth code: {{auth_code}}")
                    
                    # Check for tunnel ready
                    # Looks like: "Open this link in your browser https://vscode.dev/tunnel/<name>"
                    if "vscode.dev/tunnel" in line or "Connected to" in line or "Forwarding" in line:
                        tunnel_ready = True
                        _log("VS Code tunnel is ready!")
                        break
                    
                    # Alternative: "Tunnel name:" followed by URL
                    if "https://vscode.dev" in line:
                        tunnel_ready = True
                        break
                        
                except Exception as e:
                    _log(f"Error reading tunnel output: {{e}}")
                    break
            
            return proc, auth_url, auth_code, tunnel_ready

        def _install_debugpy():
            """Install debugpy for Python debugging support."""
            try:
                import debugpy
                _log("debugpy already available")
                return True
            except ImportError:
                _log("Installing debugpy for Python debugging...")
                result = _subprocess.run(
                    [_sys.executable, "-m", "pip", "install", "--quiet", "debugpy"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    _log("debugpy installed successfully")
                    return True
                else:
                    _log(f"Failed to install debugpy: {{result.stderr}}")
                    return False

        def _start_debugpy_server():
            """Start debugpy server for VS Code debugging."""
            try:
                import debugpy
                debugpy.listen(("0.0.0.0", _DEBUGPY_PORT))
                _log(f"debugpy server listening on port {{_DEBUGPY_PORT}}")
                return True
            except Exception as e:
                _log(f"Failed to start debugpy: {{e}}")
                return False

        # ======================== MAIN SETUP ========================
        print("=" * 70, flush=True)
        print("INTERACTIVE DEBUGGING SESSION", flush=True)
        print("=" * 70, flush=True)
        print(flush=True)

        _tunnel_proc = None
        _cli_path = _download_vscode_cli()

        if _cli_path:
            _tunnel_proc, _auth_url, _auth_code, _tunnel_ready = _start_vscode_tunnel(_cli_path)
            
            if _tunnel_proc and _tunnel_proc.poll() is None:
                print(flush=True)
                
                if _auth_url:
                    # Need authentication
                    print("\\033[93m" + "=" * 70 + "\\033[0m", flush=True)
                    print("\\033[93m  AUTHENTICATION REQUIRED\\033[0m", flush=True)
                    print("\\033[93m" + "=" * 70 + "\\033[0m", flush=True)
                    print(flush=True)
                    print("  To authorize this tunnel, open your browser to:", flush=True)
                    print(f"    \\033[96m{{_auth_url}}\\033[0m", flush=True)
                    if _auth_code:
                        print(flush=True)
                        print(f"  Enter code: \\033[93m{{_auth_code}}\\033[0m", flush=True)
                    print(flush=True)
                    print("  Waiting for authentication...", flush=True)
                    print("=" * 70, flush=True)
                    print(flush=True)
                    
                    # Wait for tunnel to become ready after auth
                    _wait_start = _time.time()
                    while (_time.time() - _wait_start) < 120:  # 2 minute timeout for auth
                        try:
                            line = _tunnel_proc.stdout.readline()
                            if line:
                                with open(_LOG_FILE, "a") as log:
                                    log.write(line)
                                if "vscode.dev" in line or "Connected" in line or "Forwarding" in line:
                                    _tunnel_ready = True
                                    _log("Authentication successful - tunnel ready!")
                                    break
                            if _tunnel_proc.poll() is not None:
                                _log("Tunnel process exited during auth wait")
                                break
                        except:
                            _time.sleep(0.5)
                    
                    if not _tunnel_ready:
                        _log("Authentication timeout or failed")
                
                if _tunnel_ready or _tunnel_proc.poll() is None:
                    print("\\033[92m" + "=" * 70 + "\\033[0m", flush=True)
                    print("\\033[92m  TUNNEL ACTIVE - VS Code Remote Access Ready\\033[0m", flush=True)
                    print("\\033[92m" + "=" * 70 + "\\033[0m", flush=True)
                    print(flush=True)
                    print("  To connect with VS Code:", flush=True)
                    print("    1. Open VS Code on your local machine", flush=True)
                    print("    2. Press Ctrl+Shift+P → 'Remote - Tunnels: Connect to Tunnel'", flush=True)
                    print(f"    3. Select or enter tunnel: \\033[96m{{_TUNNEL_NAME}}\\033[0m", flush=True)
                    print(flush=True)
                    print("  Or open in browser:", flush=True)
                    print(f"    \\033[96mhttps://vscode.dev/tunnel/{{_TUNNEL_NAME}}\\033[0m", flush=True)
                    print(flush=True)
                    print("  Features available:", flush=True)
                    print("    • Full VS Code editor in the container", flush=True)
                    print("    • Integrated terminal (bash/sh)", flush=True)
                    print("    • File browser and editing", flush=True)
                    print("    • Extensions support", flush=True)
                    print(flush=True)
                    
                    # Start thread to keep reading tunnel output (prevents buffer fill)
                    def _read_tunnel_output():
                        while _tunnel_proc and _tunnel_proc.poll() is None:
                            try:
                                line = _tunnel_proc.stdout.readline()
                                if line:
                                    with open(_LOG_FILE, "a") as log:
                                        log.write(line)
                            except:
                                break
                    _output_thread = _threading.Thread(target=_read_tunnel_output, daemon=True)
                    _output_thread.start()
                    
                    # Setup Python debugging
                    _debugpy_ready = False
                    if _install_debugpy():
                        if _start_debugpy_server():
                            _debugpy_ready = True
                    
                    # Auto-create VS Code debug configuration for easy F5 debugging
                    def _setup_vscode_workspace():
                        """Create a writable workspace with .vscode/launch.json for F5 debugging.
                        
                        Since /mnt/scripts is read-only (mounted from blob storage), we create
                        a workspace in /workspace/ with symlinks to the scripts and a writable
                        .vscode directory.
                        """
                        try:
                            import shutil as _shutil
                            
                            # Create writable workspace directory
                            workspace_dir = "/workspace"
                            vscode_dir = f"{{workspace_dir}}/.vscode"
                            scripts_link = f"{{workspace_dir}}/scripts"
                            
                            _os.makedirs(workspace_dir, exist_ok=True)
                            _os.makedirs(vscode_dir, exist_ok=True)
                            
                            # Create symlink to scripts (so user can see them in workspace)
                            if not _os.path.exists(scripts_link):
                                try:
                                    _os.symlink("/mnt/scripts", scripts_link)
                                    _log("Created symlink: /workspace/scripts -> /mnt/scripts")
                                except OSError as e:
                                    # If symlink fails, try copying instead
                                    _log(f"Symlink failed ({{e}}), copying scripts instead...")
                                    if _os.path.isdir("/mnt/scripts"):
                                        _shutil.copytree("/mnt/scripts", scripts_link, dirs_exist_ok=True)
                            
                            # Create symlinks to /input, /output, and /workdir if they exist
                            for folder_name in ["input", "output", "workdir"]:
                                source_path = f"/{{folder_name}}"
                                link_path = f"{{workspace_dir}}/{{folder_name}}"
                                
                                if _os.path.exists(source_path) and not _os.path.exists(link_path):
                                    try:
                                        _os.symlink(source_path, link_path)
                                        _log(f"Created symlink: /workspace/{{folder_name}} -> /{{folder_name}}")
                                    except OSError as e:
                                        # If symlink fails, try copying instead
                                        _log(f"Symlink failed for {{folder_name}} ({{e}}), copying instead...")
                                        if _os.path.isdir(source_path):
                                            _shutil.copytree(source_path, link_path, dirs_exist_ok=True)
                            
                            # Create launch.json for Python remote attach
                            launch_config = {{
                                "version": "0.2.0",
                                "configurations": [
                                    {{
                                        "name": "Attach to Script",
                                        "type": "debugpy",
                                        "request": "attach",
                                        "connect": {{
                                            "host": "localhost",
                                            "port": _DEBUGPY_PORT
                                        }},
                                        "pathMappings": [
                                            {{
                                                "localRoot": "${{workspaceFolder}}/scripts",
                                                "remoteRoot": "/mnt/scripts"
                                            }},
                                            {{
                                                "localRoot": "/mnt/scripts",
                                                "remoteRoot": "/mnt/scripts"
                                            }}
                                        ],
                                        "justMyCode": False
                                    }}
                                ]
                            }}
                            
                            import json as _json
                            launch_path = _os.path.join(vscode_dir, "launch.json")
                            with open(launch_path, "w") as f:
                                _json.dump(launch_config, f, indent=4)
                            
                            # Create extensions.json to recommend Python debugger extension
                            extensions_config = {{
                                "recommendations": [
                                    "ms-python.python",
                                    "ms-python.debugpy",
                                    "ms-python.vscode-pylance"
                                ],
                                "unwantedRecommendations": []
                            }}
                            extensions_path = _os.path.join(vscode_dir, "extensions.json")
                            with open(extensions_path, "w") as f:
                                _json.dump(extensions_config, f, indent=4)
                            
                            _log("Workspace created at /workspace/ with launch.json and extensions.json")
                            _log("Open /workspace/ folder in VS Code, then press F5 to debug")
                            return True
                        except Exception as e:
                            _log(f"Could not create workspace: {{e}}")
                            return False
                    
                    _vscode_configured = _setup_vscode_workspace()
                    
                    if _debugpy_ready:
                        print("  \\033[92mPython Debugging Ready:\\033[0m", flush=True)
                        print(f"    • debugpy listening on port {{_DEBUGPY_PORT}}", flush=True)
                        if _vscode_configured:
                            print("    • \\033[92mJust press F5 to attach debugger!\\033[0m", flush=True)
                            print("    • Set breakpoints, then F5 to start debugging", flush=True)
                        else:
                            print("    • Use 'Python: Attach' debug configuration", flush=True)
                        print(flush=True)
                    
                    print(f"  Session timeout: {{_TIMEOUT_MINUTES}} minutes", flush=True)
                    print(f"  Tunnel log: {{_LOG_FILE}}", flush=True)
                    print("=" * 70, flush=True)
                    print(flush=True)
                    
                    # ============ WAIT FOR USER TO CONNECT ============
                    print("\\033[93m" + "=" * 70 + "\\033[0m", flush=True)
                    print("\\033[93m  WAITING FOR YOU TO CONNECT...\\033[0m", flush=True)
                    print("\\033[93m" + "=" * 70 + "\\033[0m", flush=True)
                    print(flush=True)
                    print("  The script is PAUSED. Choose how to proceed:", flush=True)
                    print(flush=True)
                    print("  \\033[96mOption 1: DEBUG with breakpoints (recommended)\\033[0m", flush=True)
                    print("    1. Open folder: /workspace", flush=True)
                    print("    2. Open scripts/your_script.py and set breakpoints", flush=True)
                    print("    3. Press F5 to attach debugger and start stepping", flush=True)
                    print(flush=True)
                    print("  \\033[96mOption 2: Just RUN the script\\033[0m", flush=True)
                    print("    In VS Code terminal, run: touch /tmp/continue", flush=True)
                    print(flush=True)
                    print(f"  \\033[91mTimeout: {{_TIMEOUT_MINUTES}} minutes - script will ABORT if no action.\\033[0m", flush=True)
                    print("=" * 70, flush=True)
                    print(flush=True)
                    
                    # Wait for either: debugger attach, signal file, or timeout
                    _wait_start = _time.time()
                    _wait_timeout = _TIMEOUT_MINUTES * 60
                    _continue_file = "/tmp/continue"
                    _user_connected = False
                    
                    while (_time.time() - _wait_start) < _wait_timeout:
                        # Check for signal file
                        if _os.path.exists(_continue_file):
                            print("[tunnel] Continue signal received - resuming script", flush=True)
                            try:
                                _os.remove(_continue_file)
                            except:
                                pass
                            _user_connected = True
                            break
                        
                        # Check if debugger attached (debugpy sets trace function)
                        if _debugpy_ready:
                            try:
                                import debugpy
                                if debugpy.is_client_connected():
                                    print("[tunnel] Debugger attached - resuming script", flush=True)
                                    _user_connected = True
                                    break
                            except:
                                pass
                        
                        _time.sleep(2)
                    
                    if not _user_connected:
                        # Timeout reached without user action - ABORT
                        print(flush=True)
                        print("\\033[91m" + "=" * 70 + "\\033[0m", flush=True)
                        print("\\033[91m  TIMEOUT - NO USER CONNECTION DETECTED\\033[0m", flush=True)
                        print("\\033[91m" + "=" * 70 + "\\033[0m", flush=True)
                        print(flush=True)
                        print(f"  Waited {{_TIMEOUT_MINUTES}} minutes for:", flush=True)
                        print("    • VS Code tunnel connection + '/tmp/continue' file", flush=True)
                        print("    • Debugger attachment", flush=True)
                        print(flush=True)
                        print("  ABORTING script execution.", flush=True)
                        print("  Re-submit the job if you want to try again.", flush=True)
                        print("=" * 70, flush=True)
                        
                        # Cleanup tunnel before exit
                        if _tunnel_proc and _tunnel_proc.poll() is None:
                            _tunnel_proc.terminate()
                        
                        _sys.exit(1)
                    
                    print(flush=True)
                    print("=" * 70, flush=True)
                    print("  CONTINUING SCRIPT EXECUTION", flush=True)
                    print("  Tunnel remains active. You can still connect via VS Code.", flush=True)
                    print("=" * 70, flush=True)
                    print(flush=True)
                    
                    # Register cleanup
                    def _cleanup():
                        if _tunnel_proc and _tunnel_proc.poll() is None:
                            _tunnel_proc.terminate()
                            _log("VS Code tunnel terminated")
                    _atexit.register(_cleanup)
                else:
                    _log("Tunnel failed to start")
            else:
                _log("VS Code tunnel process failed to start")
                if _tunnel_proc:
                    remaining = _tunnel_proc.stdout.read() if _tunnel_proc.stdout else ""
                    print(f"Process output: {{remaining[:500]}}", flush=True)
        else:
            print("\\033[93mWARNING: Could not set up VS Code tunnel\\033[0m", flush=True)
            print("The script will continue without interactive debugging.", flush=True)
            print("=" * 70, flush=True)
            print(flush=True)

        # Cleanup wrapper variables
        try:
            del _log, _download_vscode_cli, _start_vscode_tunnel, _install_debugpy
            del _start_debugpy_server
            del _VSCODE_CLI_URL, _VSCODE_CLI_PATH, _DEBUGPY_PORT, _LOG_FILE
            del _TUNNEL_NAME, _TIMEOUT_MINUTES, _cli_path
            del _auth_url, _auth_code, _tunnel_ready
        except:
            pass
        # Keep _tunnel_proc for atexit cleanup
        # ============ END TUNNEL WRAPPER - USER SCRIPT STARTS BELOW ============

    ''').lstrip()

def generate_shell_tunnel_wrapper() -> str:
    """Generate a self-contained shell script for VS Code tunnel setup.
    
    This is a language-independent alternative to generate_tunnel_wrapper_code().
    Instead of injecting Python, this creates a shell script that:
    1. Downloads VS Code CLI (if not present)
    2. Starts the tunnel
    3. Outputs auth info in a parseable format (same as Python version)
    4. Creates /workspace/run_script.sh with the user command (NOT auto-executed)
    5. Waits for the full timeout period, giving user full control
    
    The user command is NOT automatically executed. This allows users to:
    - Connect via VS Code and explore the environment
    - Debug and modify code before running
    - Run the command manually when ready (./run_script.sh)
    - Cancel the job when done to free resources
    
    Returns:
        Shell script content as a string.
    """
    return dedent(r'''
        #!/bin/sh
        # ============ VS CODE TUNNEL WRAPPER (Language-Independent) ============
        # Version: 2026-01-10-v5 (explicit logging for debugging)
        # This script sets up a VS Code tunnel for interactive debugging.
        # The user script is NOT auto-executed - a run_script.sh helper is created.
        # Auth info is output to stdout for log polling.
        
        # Ensure all output is flushed immediately (important for job logs)
        (echo ">>> WRAPPER BOOTSTRAP STARTED" ; sleep 0) >&2
        
        # FAIL-FAST DEPENDENCY CHECK: Validate bash availability before proceeding
        # Only run this check once (not when bash re-executes the script)
        if [ -z "$_WRAPPER_BOOTSTRAP_DONE" ]; then
            echo "[wrapper-bootstrap] Checking bash availability..." >&2
            if ! command -v bash >/dev/null 2>&1; then
                echo "===============================================" >&2
                echo "ERROR: Interactive mode requires bash" >&2
                echo "===============================================" >&2
                echo "" >&2
                echo "Bash is not installed in this container." >&2
                echo "" >&2
                echo "To fix this, add bash to your container image:" >&2
                echo "  Alpine:        RUN apk add --no-cache bash" >&2
                echo "  Debian/Ubuntu: RUN apt-get update && apt-get install -y bash" >&2
                echo "  RHEL/CentOS:   RUN yum install -y bash" >&2
                echo "" >&2
                echo "Alternatively, run without interactive mode for debugging." >&2
                echo "===============================================" >&2
                exit 1
            fi
            
            # Bash found, proceed with bootstrap
            echo "[wrapper-bootstrap] Bash found, switching to bash..." >&2
            
            # Switch to bash for the rest of the script (uses bash-specific syntax)
            # Export the guard variable so bash doesn't re-run this check
            export _WRAPPER_BOOTSTRAP_DONE=1
            exec bash "$0" "$@"
            exit $?  # Should never reach here, but in case exec fails
        fi
        
        # Everything below runs in bash
        set -eo pipefail
        echo "[wrapper-bash] Bash bootstrap complete, starting tunnel setup..." >&2
        
        # Configuration (passed as environment variables)
        TUNNEL_NAME="${TUNNEL_SESSION_ID:-discovery-session}"
        TIMEOUT_MINUTES="${TUNNEL_TIMEOUT_MINUTES:-30}"
        TUNNEL_MODE="${TUNNEL_MODE:-vscode}"  # vscode or novnc
        
        VSCODE_CLI_URL="https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64"
        VSCODE_CLI_PATH="/tmp/vscode-cli/code"
        LOG_FILE="/tmp/vscode-tunnel.log"
        WORKSPACE_DIR="/workspace"
        
        # Setup SSL certificates for Rust-based VS Code CLI
        # This is needed for containers that don't have SSL_CERT_FILE set
        setup_ssl_certs() {
            if [[ -z "$SSL_CERT_FILE" ]]; then
                # Try common certificate bundle locations
                for cert_file in \
                    /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
                    /etc/ssl/certs/ca-certificates.crt \
                    /etc/ssl/certs/ca-bundle.crt \
                    /etc/ssl/cert.pem \
                    /etc/pki/tls/certs/ca-bundle.crt; do
                    if [[ -f "$cert_file" && -s "$cert_file" ]]; then
                        export SSL_CERT_FILE="$cert_file"
                        log "Set SSL_CERT_FILE=$cert_file"
                        break
                    fi
                done
            fi
            
            if [[ -z "$SSL_CERT_DIR" ]]; then
                for cert_dir in /etc/ssl/certs /etc/pki/tls/certs; do
                    if [[ -d "$cert_dir" ]]; then
                        export SSL_CERT_DIR="$cert_dir"
                        break
                    fi
                done
            fi
            
            # Test if SSL works by trying to connect to a test URL
            # If it fails, download Mozilla CA bundle as fallback
            if ! curl -s --connect-timeout 5 https://github.com -o /dev/null 2>/dev/null; then
                log "SSL verification failed, downloading Mozilla CA bundle..."
                if curl -k -s --connect-timeout 10 https://curl.se/ca/cacert.pem -o /tmp/mozilla-ca-bundle.pem 2>/dev/null; then
                    export SSL_CERT_FILE="/tmp/mozilla-ca-bundle.pem"
                    log "Set SSL_CERT_FILE=/tmp/mozilla-ca-bundle.pem (Mozilla CA bundle)"
                else
                    log "WARNING: Could not download Mozilla CA bundle"
                fi
            fi
        }
        
        log() {
            echo "[tunnel] $1"
        }
        
        log_session_info() {
            echo "[session-info] $1"
        }
        
        log_countdown() {
            echo "[countdown] $1"
        }
        
        setup_workspace_symlinks() {
            log "Starting setup_workspace_symlinks..."
            # Create workspace directory if it doesn't exist
            # Try /workspace first, fall back to /tmp/workspace if permission denied
            if mkdir -p "$WORKSPACE_DIR" 2>/dev/null; then
                log "Workspace directory ready: $WORKSPACE_DIR"
            else
                log "WARNING: Cannot create $WORKSPACE_DIR (permission denied), using /tmp/workspace"
                WORKSPACE_DIR="/tmp/workspace"
                export WORKSPACE_DIR  # Export so fallback persists throughout script
                mkdir -p "$WORKSPACE_DIR" || { log "ERROR: Cannot create fallback workspace"; return 1; }
                log "Using fallback workspace: $WORKSPACE_DIR"
            fi
            
            log "Setting up workspace symlinks..."
            
            # Create symlinks to important directories
            # Only create if target exists and symlink doesn't already exist
            for target_dir in /input /output /app /workdir /mnt/scripts; do
                log "Checking directory: $target_dir"
                if [[ -d "$target_dir" ]]; then
                    link_name="$WORKSPACE_DIR/$(basename $target_dir)"
                    if [[ ! -e "$link_name" ]]; then
                        ln -sf "$target_dir" "$link_name"
                        log "Created symlink: $link_name -> $target_dir"
                    else
                        log "Symlink already exists: $link_name"
                    fi
                else
                    log "Directory does not exist: $target_dir"
                fi
            done
            
            # Also create a convenient 'scripts' symlink if /mnt/scripts exists
            log "Checking /mnt/scripts for scripts symlink..."
            if [[ -d "/mnt/scripts" && ! -e "$WORKSPACE_DIR/scripts" ]]; then
                ln -sf "/mnt/scripts" "$WORKSPACE_DIR/scripts"
                log "Created symlink: $WORKSPACE_DIR/scripts -> /mnt/scripts"
            fi
            
            log "Workspace symlinks setup complete"
        }
        
        setup_vscode_workspace() {
            log "Starting setup_vscode_workspace..."
            # Create .vscode directory with settings and extension recommendations
            local vscode_dir="$WORKSPACE_DIR/.vscode"
            if ! mkdir -p "$vscode_dir" 2>/dev/null; then
                log "WARNING: Cannot create .vscode dir (permission denied), skipping VS Code workspace config"
                return 0
            fi
            
            log "Setting up VS Code workspace configuration..."
            
            # Detect languages (fallback if no pre-generated extensions.json)
            local python_detected=false
            local r_detected=false
            local julia_detected=false
            
            log "Auto-detecting available languages..."
            
            # Check for script files in /mnt/scripts (supercomputer) or /workdir (local Docker)
            local script_dirs=("/mnt/scripts" "/workdir")
            for script_dir in "${script_dirs[@]}"; do
                if [[ -d "$script_dir" ]]; then
                    log "Checking for scripts in $script_dir..."
                    if ls "$script_dir"/*.py &>/dev/null; then
                        python_detected=true
                        log "Python scripts detected in $script_dir"
                    fi
                    if ls "$script_dir"/*.r "$script_dir"/*.R &>/dev/null 2>&1; then
                        r_detected=true
                        log "R scripts detected in $script_dir"
                    fi
                    if ls "$script_dir"/*.jl &>/dev/null; then
                        julia_detected=true
                        log "Julia scripts detected in $script_dir"
                    fi
                fi
            done
            
            # Fallback: check if language executables are installed
            if [[ "$python_detected" == "false" ]] && (timeout 2 command -v python &>/dev/null || timeout 2 command -v python3 &>/dev/null); then
                python_detected=true
                log "Python executable detected"
            fi
            if [[ "$r_detected" == "false" ]] && (timeout 2 command -v R &>/dev/null || timeout 2 command -v Rscript &>/dev/null); then
                r_detected=true
                log "R executable detected"
            fi
            if [[ "$julia_detected" == "false" ]] && timeout 2 command -v julia &>/dev/null; then
                julia_detected=true
                log "Julia executable detected"
            fi
            log "Language detection complete"
            
            # Check if extensions.json was pre-generated and uploaded with the script
            if [[ -f "/mnt/scripts/.vscode/extensions.json" ]]; then
                log "Found pre-generated extensions.json in /mnt/scripts/.vscode/"
                cp -r "/mnt/scripts/.vscode" "$WORKSPACE_DIR/"
                log "Copied .vscode configuration from uploaded scripts"
            else
                log "No pre-generated extensions.json found, generating based on detected languages"
                
                # Create extensions.json with recommendations
                cat > "$vscode_dir/extensions.json" << 'EXTENSIONS_EOF'
{
    "recommendations": [
EXTENSIONS_EOF
                
                # Add language-specific extensions
                local first=true
                
                if [[ "$python_detected" == "true" ]]; then
                    [[ "$first" == "true" ]] && first=false || echo "," >> "$vscode_dir/extensions.json"
                    cat >> "$vscode_dir/extensions.json" << 'EOF'
        "ms-python.python",
        "ms-python.debugpy",
        "ms-python.vscode-pylance",
        "ms-toolsai.jupyter"
EOF
            fi
            
            if [[ "$r_detected" == "true" ]]; then
                [[ "$first" == "true" ]] && first=false || echo "," >> "$vscode_dir/extensions.json"
                cat >> "$vscode_dir/extensions.json" << 'EOF'
        "REditorSupport.r"
EOF
            fi
            
            if [[ "$julia_detected" == "true" ]]; then
                [[ "$first" == "true" ]] && first=false || echo "," >> "$vscode_dir/extensions.json"
                cat >> "$vscode_dir/extensions.json" << 'EOF'
        "julialang.language-julia"
EOF
            fi
            
            # Close the JSON
            cat >> "$vscode_dir/extensions.json" << 'EOF'
    ],
    "unwantedRecommendations": []
}
EOF
                
                log "extensions.json created successfully"
            fi
            
            # Auto-detect Python interpreter path
            local PYTHON_PATH="/usr/bin/python3"
            log "Auto-detecting Python interpreter..."
            
            if command -v python3 &>/dev/null; then
                PYTHON_PATH=$(which python3 2>/dev/null || echo "/usr/bin/python3")
                log "Found python3 at: $PYTHON_PATH"
            elif command -v python &>/dev/null; then
                PYTHON_PATH=$(which python 2>/dev/null || echo "/usr/bin/python")
                log "Found python at: $PYTHON_PATH"
            else
                log "WARNING: Python not found in PATH, using default: $PYTHON_PATH"
            fi
            
            # Verify the detected path is executable
            if [[ ! -x "$PYTHON_PATH" ]]; then
                log "WARNING: Detected Python path $PYTHON_PATH is not executable, using default"
                PYTHON_PATH="/usr/bin/python3"
            fi
            
            log "Using Python interpreter: $PYTHON_PATH"
            
            # Create settings.json with auto-detected Python path
            cat > "$vscode_dir/settings.json" << SETTINGS_EOF
{
    "python.defaultInterpreterPath": "$PYTHON_PATH",
    "python.analysis.extraPaths": ["/app"],
    "python.autoComplete.extraPaths": ["/app"],
    "python.terminal.activateEnvironment": false,
    "editor.formatOnSave": true,
    "files.autoSave": "afterDelay",
    "files.autoSaveDelay": 1000,
    "terminal.integrated.defaultProfile.linux": "bash",
    "workbench.startupEditor": "readme",
    "explorer.confirmDelete": false,
    "debug.onTaskErrors": "debugAnyway"
}
SETTINGS_EOF
            
            log "settings.json created successfully with Python path: $PYTHON_PATH"
            
            # Create launch.json for Python debugging
            log "Creating launch.json for Python debugging..."
            if [[ "$python_detected" == "true" ]]; then
                cat > "$vscode_dir/launch.json" << 'LAUNCH_EOF'
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Current File",
            "type": "debugpy",
            "request": "launch",
            "program": "${file}",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                "PYTHONPATH": "/app:${workspaceFolder}"
            }
        },
        {
            "name": "Python: Run Script",
            "type": "debugpy",
            "request": "launch",
            "program": "${workspaceFolder}/scripts/${input:scriptName}",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}",
            "env": {
                "PYTHONPATH": "/app:${workspaceFolder}"
            }
        }
    ],
    "inputs": [
        {
            "id": "scriptName",
            "type": "promptString",
            "description": "Enter the script filename to debug"
        }
    ]
}
LAUNCH_EOF
                log "launch.json created successfully"
            else
                log "Skipping launch.json (Python not detected)"
            fi
            
            # Create a README in the workspace
            log "Creating workspace README.md..."
            cat > "$WORKSPACE_DIR/README.md" << 'README_EOF'
# Discovery Interactive Session

Welcome to your interactive debugging session!

## Workspace Structure

| Directory | Description |
|-----------|-------------|
| `scripts/` | Your uploaded scripts |
| `input/` | Input files for the job |
| `output/` | Output files from the job |
| `app/` | Tool modules |

## Quick Start

1. **Install recommended extensions** - You should see a popup to install them
2. **Open a script** - Navigate to `scripts/` folder
3. **Debug** - Press F5 or use the Run and Debug panel
4. **Use the terminal** - Open integrated terminal with Ctrl+`

## Session Info

This session will remain active for the configured timeout period.
README_EOF
            log "README.md created successfully"
            
            log "VS Code workspace configuration complete"
        }
        
        try_install_tar() {
            # Attempt to dynamically install tar if missing
            # Only works if we have package manager access (may require root)
            log "Attempting to install tar dynamically..."
            
            # Detect package manager and try installation
            if command -v apt-get &>/dev/null; then
                log "Detected apt (Debian/Ubuntu)..."
                apt-get update -qq 2>/dev/null && apt-get install -y tar gzip 2>/dev/null && return 0
            elif command -v yum &>/dev/null; then
                log "Detected yum (RHEL/CentOS)..."
                yum install -y tar gzip 2>/dev/null && return 0
            elif command -v apk &>/dev/null; then
                log "Detected apk (Alpine)..."
                apk add --no-cache tar gzip 2>/dev/null && return 0
            elif command -v dnf &>/dev/null; then
                log "Detected dnf (Fedora)..."
                dnf install -y tar gzip 2>/dev/null && return 0
            elif command -v zypper &>/dev/null; then
                log "Detected zypper (SUSE)..."
                zypper install -y tar gzip 2>/dev/null && return 0
            fi
            
            log "Could not install tar automatically (may need root or package manager unavailable)"
            return 1
        }
        
        download_vscode_cli() {
            # Check if already in PATH
            if command -v code &>/dev/null; then
                if code tunnel --help &>/dev/null 2>&1; then
                    log "Using system VS Code CLI"
                    VSCODE_CLI_PATH="$(command -v code)"
                    return 0
                fi
            fi
            
            # Check cached download
            if [[ -x "$VSCODE_CLI_PATH" ]]; then
                log "Using cached VS Code CLI"
                return 0
            fi
            
            log "Downloading VS Code CLI..."
            mkdir -p /tmp/vscode-cli
            
            # Download first
            if command -v curl &>/dev/null; then
                curl -fsSL "$VSCODE_CLI_URL" -o /tmp/vscode-cli/cli.tar.gz
            elif command -v wget &>/dev/null; then
                wget -q "$VSCODE_CLI_URL" -O /tmp/vscode-cli/cli.tar.gz
            else
                log "ERROR: Neither curl nor wget available"
                log "📝 IMAGE OPTIMIZATION TIP: Add 'RUN apt-get update && apt-get install -y curl' to your Dockerfile"
                return 1
            fi
            
            if [[ ! -f /tmp/vscode-cli/cli.tar.gz ]]; then
                log "ERROR: Download failed"
                return 1
            fi
            
            # Try extraction methods in order of preference
            EXTRACTION_SUCCESS=0
            
            # Method 1: tar (fastest, most reliable) - try to install if missing
            if ! command -v tar &>/dev/null; then
                log "tar not found, attempting dynamic installation..."
                if try_install_tar; then
                    log "✅ tar installed successfully!"
                fi
            fi
            
            if command -v tar &>/dev/null; then
                log "Extracting with tar..."
                if tar -xzf /tmp/vscode-cli/cli.tar.gz -C /tmp/vscode-cli 2>/dev/null; then
                    EXTRACTION_SUCCESS=1
                fi
            fi
            
            # Method 2: Python (fallback if tar unavailable)
            if [[ $EXTRACTION_SUCCESS -eq 0 ]]; then
                log "tar not available, trying Python extraction..."
                
                PYTHON_CMD=""
                if command -v python3 &>/dev/null; then
                    PYTHON_CMD="python3"
                elif command -v python &>/dev/null; then
                    PYTHON_CMD="python"
                fi
                
                if [[ -n "$PYTHON_CMD" ]]; then
                    log "Extracting with $PYTHON_CMD..."
                    $PYTHON_CMD -c "
import tarfile
import os
import shutil
try:
    with tarfile.open('/tmp/vscode-cli/cli.tar.gz', 'r:gz') as tf:
        for member in tf.getmembers():
            if member.name.endswith('code') and member.isfile():
                tf.extract(member, '/tmp/vscode-cli')
                extracted = os.path.join('/tmp/vscode-cli', member.name)
                if extracted != '/tmp/vscode-cli/code':
                    shutil.move(extracted, '/tmp/vscode-cli/code')
                os.chmod('/tmp/vscode-cli/code', 0o755)
                print('[tunnel] Extracted with Python successfully')
                exit(0)
except Exception as e:
    print(f'[tunnel] Python extraction failed: {e}')
    exit(1)
" 2>/dev/null && EXTRACTION_SUCCESS=1
                fi
            fi
            
            # Method 3: gunzip + cpio (for minimal images with busybox)
            if [[ $EXTRACTION_SUCCESS -eq 0 ]] && command -v gunzip &>/dev/null && command -v cpio &>/dev/null; then
                log "Trying gunzip+cpio extraction..."
                (cd /tmp/vscode-cli && gunzip -c cli.tar.gz | cpio -idm 2>/dev/null) && EXTRACTION_SUCCESS=1
            fi
            
            # Method 4: busybox tar (for alpine-based images)
            if [[ $EXTRACTION_SUCCESS -eq 0 ]] && command -v busybox &>/dev/null; then
                log "Trying busybox tar extraction..."
                busybox tar -xzf /tmp/vscode-cli/cli.tar.gz -C /tmp/vscode-cli 2>/dev/null && EXTRACTION_SUCCESS=1
            fi
            
            # Cleanup and verify
            rm -f /tmp/vscode-cli/cli.tar.gz
            
            if [[ $EXTRACTION_SUCCESS -eq 0 ]]; then
                log "ERROR: All extraction methods failed"
                log "📝 IMAGE OPTIMIZATION TIP: Add to your Dockerfile:"
                log "   RUN apt-get update && apt-get install -y tar gzip"
                log "   OR: RUN apk add --no-cache tar gzip  # for Alpine"
                log "   OR: RUN yum install -y tar gzip      # for RHEL/CentOS"
                return 1
            fi
            
            # Verify the code binary exists and is executable
            if [[ ! -f "$VSCODE_CLI_PATH" ]]; then
                # Fallback: try to find it if Python didn't place it correctly
                log "Code binary not at expected location, searching..."
                find /tmp/vscode-cli -name "code" -type f -exec mv {} "$VSCODE_CLI_PATH" \;
            fi
            
            chmod +x "$VSCODE_CLI_PATH" 2>/dev/null || true
            
            if [[ -x "$VSCODE_CLI_PATH" ]]; then
                log "VS Code CLI downloaded successfully"
                return 0
            else
                log "ERROR: Failed to download VS Code CLI"
                return 1
            fi
        }
        
        start_tunnel() {
            log "Starting VS Code tunnel: $TUNNEL_NAME"
            
            # Setup workspace symlinks before starting tunnel
            setup_workspace_symlinks
            
            # Setup VS Code workspace configuration (.vscode folder with extensions.json, settings.json, etc.)
            setup_vscode_workspace
            
            # Verify workspace actually exists after setup attempts
            if [[ ! -d "$WORKSPACE_DIR" ]]; then
                log "WARNING: Workspace directory $WORKSPACE_DIR does not exist after setup"
                # Try to create it one more time
                if mkdir -p "$WORKSPACE_DIR" 2>/dev/null; then
                    log "Successfully created workspace directory"
                elif mkdir -p "/tmp/workspace" 2>/dev/null; then
                    WORKSPACE_DIR="/tmp/workspace"
                    export WORKSPACE_DIR  # Export fallback
                    log "Using fallback workspace: $WORKSPACE_DIR"
                else
                    log "ERROR: Cannot create any workspace directory, using root"
                    WORKSPACE_DIR="/"
                fi
            fi
            
            log "Final workspace directory: $WORKSPACE_DIR"
            
            # Check if a tunnel with this name is already running
            if pgrep -f "/tmp/vscode-cli/code tunnel.*--name $TUNNEL_NAME" > /dev/null 2>&1; then
                log "Tunnel $TUNNEL_NAME is already running - reusing existing tunnel"
                log_session_info ""
                log_session_info "======================================================================"
                log_session_info "  VS CODE TUNNEL READY (Reusing existing tunnel)"
                log_session_info "======================================================================"
                log_session_info ""
                log_session_info "  Open this workspace in VS Code:"
                log_session_info "  - Workspace path: $WORKSPACE_DIR"
                log_session_info "  - Browser:  https://vscode.dev/tunnel/$TUNNEL_NAME$WORKSPACE_DIR"
                log_session_info "  - Desktop:  code --remote tunnel+$TUNNEL_NAME $WORKSPACE_DIR"
                log_session_info ""
                log_session_info "======================================================================"
                return 0
            fi
            
            # No existing tunnel - clean up any stale processes and start fresh
            log "No existing tunnel found, starting fresh..."
            
            # Create VS Code CLI data directory in /tmp (writable location)
            VSCODE_CLI_DATA_DIR="/tmp/vscode-cli-data"
            mkdir -p "$VSCODE_CLI_DATA_DIR" 2>/dev/null || true
            
            # Kill any zombie tunnel processes (but only if they don't match our tunnel name)
            pkill -9 -f "/tmp/vscode-cli/code tunnel" 2>/dev/null || true
            
            # Also try the CLI's own kill command
            "$VSCODE_CLI_PATH" tunnel --cli-data-dir "$VSCODE_CLI_DATA_DIR" kill 2>/dev/null || true
            
            # Unregister current machine's tunnel (redirect stdin from /dev/null to avoid prompts)
            log "Unregistering previous tunnel..."
            "$VSCODE_CLI_PATH" tunnel --cli-data-dir "$VSCODE_CLI_DATA_DIR" unregister < /dev/null 2>/dev/null || true
            
            log "Cleanup complete, starting tunnel..."
            
            # Wait for processes to die
            sleep 1
            log "Sleep complete"
            
            # Clear log file to remove old errors from previous runs
            > "$LOG_FILE" 2>/dev/null || { log "ERROR: Cannot create log file $LOG_FILE"; return 1; }
            log "Log file created: $LOG_FILE"
            
            # Export SSL_CERT_FILE for the tunnel process
            if [[ -n "${SSL_CERT_FILE:-}" ]]; then
                export SSL_CERT_FILE
                log "SSL_CERT_FILE exported: $SSL_CERT_FILE"
            fi
            
            # Start tunnel in background, redirecting to log file
            log "Starting fresh tunnel with name: $TUNNEL_NAME"
            "$VSCODE_CLI_PATH" tunnel --accept-server-license-terms --cli-data-dir "$VSCODE_CLI_DATA_DIR" --name "$TUNNEL_NAME" >> "$LOG_FILE" 2>&1 &
            TUNNEL_PID=$!
            log "Tunnel command launched, PID=$TUNNEL_PID"
            
            log "Tunnel process started (PID: $TUNNEL_PID), waiting for tunnel to be ready..."
            
            # Wait for auth info or tunnel ready (max 60 seconds)
            # Also tail the log file in background so output is visible
            log "Starting log tail..."
            tail -f "$LOG_FILE" &
            TAIL_PID=$!
            log "Tail started, PID=$TAIL_PID"
            local waited=0
            local auth_found=false
            local tunnel_ready=false
            
            while [[ $waited -lt 60 ]]; do
                sleep 2
                waited=$((waited + 2))
                log "Checking tunnel status... (${waited}s elapsed)"
                
                # Check for GitHub device auth FIRST (before checking for errors)
                if grep -q "github.com/login/device" "$LOG_FILE" 2>/dev/null; then
                    auth_found=true
                    AUTH_URL="https://github.com/login/device"
                    AUTH_CODE=$(grep -oE "code [A-Z0-9]{4}-[A-Z0-9]{4}" "$LOG_FILE" | head -1 | cut -d' ' -f2)
                    break
                fi
                
                # Check for Microsoft device auth
                if grep -q "microsoft.com/devicelogin" "$LOG_FILE" 2>/dev/null; then
                    auth_found=true
                    AUTH_URL="https://microsoft.com/devicelogin"
                    AUTH_CODE=$(grep -oE "code [A-Z0-9]{8,}" "$LOG_FILE" | head -1 | cut -d' ' -f2)
                    break
                fi
                
                # Check if tunnel is already ready (no auth needed)
                # Look for URL in the output - this is the definitive indicator
                if grep -q "vscode.dev/tunnel" "$LOG_FILE" 2>/dev/null; then
                    tunnel_ready=true
                    log "Tunnel connected (URL found in output)"
                    break
                fi
                
                # Check if process died (only if no auth/ready found)
                if ! pgrep -f "tunnel.*--name.*$TUNNEL_NAME" > /dev/null 2>&1; then
                    # Double check with the log file for fatal errors (not transient SSL errors)
                    if [[ -f "$LOG_FILE" ]] && grep -qE "error.*certificate" "$LOG_FILE" 2>/dev/null; then
                        log "ERROR: Tunnel process exited with SSL certificate error"
                        cat "$LOG_FILE"
                        return 1
                    elif [[ -f "$LOG_FILE" ]] && grep -qE "fatal|panic|cannot" "$LOG_FILE" 2>/dev/null; then
                        log "ERROR: Tunnel process exited with error"
                        cat "$LOG_FILE"
                        return 1
                    fi
                fi
                
                # Also check for "Open this link" which appears with the URL
                if grep -qiE "open this link|is ready|Connected to|tunnel is ready" "$LOG_FILE" 2>/dev/null; then
                    tunnel_ready=true
                    log "Tunnel connected (ready indicator found)"
                    break
                fi
            done
            
            # Stop tailing the log file
            kill $TAIL_PID 2>/dev/null || true
            
            # Output auth info in EXACT format expected by log polling
            # The MCP server parses for: "[tunnel] Auth required: <URL>" and "[tunnel] Auth code: <CODE>"
            log_session_info ""
            log_session_info "======================================================================"
            if [[ "$auth_found" == "true" ]]; then
                log_session_info "  AUTHENTICATION REQUIRED"
                log_session_info "======================================================================"
                # CRITICAL: These exact log lines are parsed by the MCP server
                log "Auth required: $AUTH_URL"
                if [[ -n "${AUTH_CODE:-}" ]]; then
                    log "Auth code: $AUTH_CODE"
                fi
                log_session_info ""
                log_session_info "  To authorize this tunnel, open your browser to:"
                log_session_info "    $AUTH_URL"
                if [[ -n "${AUTH_CODE:-}" ]]; then
                    log_session_info ""
                    log_session_info "  And enter the code:"
                    log_session_info "    $AUTH_CODE"
                fi
                log_session_info ""
                log_session_info "======================================================================"
                log_session_info "  VS CODE TUNNEL ACCESS"
                log_session_info "======================================================================"
                log_session_info ""
                log_session_info "  After authenticating, use VS Code Desktop (recommended):"
                log_session_info "    code --remote tunnel+$TUNNEL_NAME $WORKSPACE_DIR"
                log_session_info ""
                log_session_info "  Or use VS Code in Browser:"
                WORKSPACE_PATH="${WORKSPACE_DIR#/}"
                log_session_info "    https://vscode.dev/tunnel/$TUNNEL_NAME/$WORKSPACE_PATH"
                log_session_info ""
                log_session_info "  Session timeout: $TIMEOUT_MINUTES minutes"
                log_session_info "======================================================================"
                echo ""
                
                # Wait for authentication (check if tunnel becomes ready)
                log "Waiting for authentication..."
                local auth_waited=0
                local auth_timeout=$((TIMEOUT_MINUTES * 60))
                
                while [[ $auth_waited -lt $auth_timeout ]]; do
                    sleep 5
                    auth_waited=$((auth_waited + 5))
                    
                    if ! kill -0 $TUNNEL_PID 2>/dev/null; then
                        log "Tunnel process exited"
                        break
                    fi
                    
                    if grep -q "vscode.dev/tunnel\\|Connected to\\|Forwarding" "$LOG_FILE" 2>/dev/null; then
                        log "Authentication successful! Tunnel is ready."
                        log "Tunnel ready"
                        tunnel_ready=true
                        break
                    fi
                    
                    # Progress update every 30 seconds
                    if [[ $((auth_waited % 30)) -eq 0 ]]; then
                        log "Still waiting for authentication... ($auth_waited seconds)"
                    fi
                done
                
            elif [[ "$tunnel_ready" == "true" ]]; then
                log_session_info "  VS CODE TUNNEL READY (No auth required)"
                log_session_info "======================================================================"
                log_session_info ""
                log_session_info "  RECOMMENDED: Use VS Code Desktop (best experience)"
                log_session_info "  ────────────────────────────────────────────────────────────"
                log_session_info "  Paste this command in your terminal:"
                log_session_info "    code --remote tunnel+$TUNNEL_NAME $WORKSPACE_DIR"
                log_session_info ""
                log_session_info "  ALTERNATIVE: Use VS Code in Browser"
                log_session_info "  ───────────────────────────────────"
                WORKSPACE_PATH="${WORKSPACE_DIR#/}"
                log_session_info "    https://vscode.dev/tunnel/$TUNNEL_NAME/$WORKSPACE_PATH"
                log_session_info ""
                log_session_info "  Workspace path: $WORKSPACE_DIR"
                log_session_info "======================================================================"
            else
                log "WARNING: Could not determine tunnel status after 60 seconds"
                log "Log file contents:"
                cat "$LOG_FILE"
            fi
            
            # Trap to cleanup ONLY the tail process on exit
            # We intentionally DO NOT kill the tunnel - it should stay running for reuse
            trap 'kill $TAIL_PID 2>/dev/null; log "Wrapper script exiting (tunnel left running for reuse)"' EXIT
        }
        
        create_run_script() {
            # Create a helper script that users can run manually
            local run_script="$WORKSPACE_DIR/run_script.sh"
            
            # Check if there's an uploaded action script in /mnt/scripts/
            # (uploaded for interactive action commands)
            local action_script=""
            if [[ -d "/mnt/scripts" ]]; then
                # Find the first script_*.sh file (should be the action script)
                action_script=$(find /mnt/scripts -maxdepth 1 -name "script_*.sh" -print -quit 2>/dev/null)
            fi
            
            if [[ -n "$action_script" && -f "$action_script" ]]; then
                # For interactive action commands: link to the uploaded action script
                # so user can easily access it as run_script.sh in the workspace
                log "Found uploaded action script: $action_script"
                ln -sf "$action_script" "$run_script" 2>/dev/null || {
                    # Fallback: copy if symlink fails
                    cp "$action_script" "$run_script"
                }
                log "Linked action script to: $run_script"
                chmod +x "$run_script"
                return 0
            fi
            
            # For non-action commands, create a script from the passed arguments
            if [[ $# -eq 0 ]]; then
                # No command provided - might be starting tunnel without command
                log "No command provided, creating empty run_script.sh"
                echo "#!/usr/bin/env bash" > "$run_script"
                echo "# No command was provided" >> "$run_script"
                echo "echo 'Use the uploaded script or provide a command to run'" >> "$run_script"
                chmod +x "$run_script"
                return 0
            fi
            
            # User command is passed as arguments to this wrapper
            local script_content=$(cat << 'RUNSCRIPT_EOF'
#!/usr/bin/env bash
# Auto-generated script to run the original command
# You can execute this script manually, or run the command directly.
# Feel free to modify, debug, or run step-by-step!

set -euo pipefail

echo "========================================"
echo "  Running original script/command"
echo "========================================"
echo ""

# Original command:
RUNSCRIPT_EOF
            )
            
            # Add the actual command to the script content
            script_content="$script_content"$'\n'"$@"$'\n'
            
            script_content="$script_content"$(cat << 'RUNSCRIPT_EOF'

exit_code=$?
echo ""
echo "========================================"
echo "  Command completed with exit code: $exit_code"
echo "========================================"
exit $exit_code
RUNSCRIPT_EOF
            )
            
            # Write to /workspace/run_script.sh
            echo "$script_content" > "$run_script"
            chmod +x "$run_script"
            log "Created run script: $run_script"
        }
        
        # Main execution
        echo "======================================================================"
        echo "INTERACTIVE DEBUGGING SESSION"
        echo "======================================================================"
        echo ""
        
        # Early validation: Check for required dependencies when in interactive mode
        validate_interactive_dependencies() {
            local missing_deps=()
            local has_extraction_method=0
            
            log "Validating interactive mode dependencies..."
            
            # Check for bash (absolutely required for wrapper script)
            if ! command -v bash &>/dev/null; then
                missing_deps+=("bash")
                log "  ❌ Missing: bash (REQUIRED)"
            else
                log "  ✓ Found: bash"
            fi
            
            # Check for curl OR wget (required for download)
            if command -v curl &>/dev/null; then
                log "  ✓ Found: curl"
            elif command -v wget &>/dev/null; then
                log "  ✓ Found: wget"
            else
                missing_deps+=("curl/wget")
                log "  ❌ Missing: curl or wget (REQUIRED)"
            fi
            
            # Check for extraction methods (at least one needed)
            log "  Checking extraction methods..."
            if command -v tar &>/dev/null; then
                log "    ✓ tar available (preferred method)"
                has_extraction_method=1
            else
                log "    ℹ tar not found (will try fallbacks)"
            fi
            
            if command -v python3 &>/dev/null || command -v python &>/dev/null; then
                log "    ✓ Python available (fallback method)"
                has_extraction_method=1
            else
                log "    ℹ Python not found"
            fi
            
            if command -v gunzip &>/dev/null && command -v cpio &>/dev/null; then
                log "    ✓ gunzip+cpio available (fallback method)"
                has_extraction_method=1
            fi
            
            if command -v busybox &>/dev/null; then
                log "    ✓ busybox available (fallback method)"
                has_extraction_method=1
            fi
            
            if [[ $has_extraction_method -eq 0 ]]; then
                missing_deps+=("extraction-tool")
                log "  ❌ No extraction method available (need tar, python, gunzip+cpio, or busybox)"
            fi
            
            if [[ ${#missing_deps[@]} -gt 0 ]]; then
                return 1  # Signal failure
            fi
            return 0  # All dependencies present
        }
        
        # If in interactive mode, validate dependencies BEFORE attempting tunnel setup
        if [[ "$TUNNEL_MODE" != "none" && -n "$TUNNEL_MODE" ]]; then
            log ""
            log "🔍 INTERACTIVE MODE REQUESTED: $TUNNEL_MODE"
            
            if ! validate_interactive_dependencies; then
                # Fatal error: dependencies missing and user explicitly requested interactive mode
                echo ""
                echo "======================================================================"
                echo "  ❌ INTERACTIVE MODE FAILED - MISSING DEPENDENCIES"
                echo "======================================================================"
                echo ""
                echo "  Your container image is missing required tools for interactive debugging."
                echo ""
                echo "  Missing tools: ${missing_deps[*]}"
                echo ""
                echo "  📝 UPDATE YOUR DOCKERFILE:"
                echo ""
                if [[ " ${missing_deps[*]} " =~ " bash " ]]; then
                    echo "  ⚠️  bash is REQUIRED (no fallback available):"
                    echo "    Debian/Ubuntu: RUN apt-get install -y bash"
                    echo "    Alpine:        RUN apk add --no-cache bash"
                    echo "    RHEL/CentOS:   RUN yum install -y bash"
                    echo ""
                fi
                if [[ " ${missing_deps[*]} " =~ " curl/wget " ]]; then
                    echo "  ⚠️  curl or wget is REQUIRED (no fallback available):"
                    echo "    Debian/Ubuntu: RUN apt-get install -y curl ca-certificates"
                    echo "    Alpine:        RUN apk add --no-cache curl ca-certificates"
                    echo "    RHEL/CentOS:   RUN yum install -y curl ca-certificates"
                    echo ""
                fi
                if [[ " ${missing_deps[*]} " =~ " extraction-tool " ]]; then
                    echo "  ⚠️  At least one extraction tool is REQUIRED:"
                    echo "    Recommended: Install tar (fastest and most reliable)"
                    echo "      Debian/Ubuntu: RUN apt-get install -y tar gzip"
                    echo "      Alpine:        RUN apk add --no-cache tar gzip"
                    echo "      RHEL/CentOS:   RUN yum install -y tar gzip"
                    echo ""
                    echo "    Alternative: Ensure Python is available"
                    echo "      Debian/Ubuntu: RUN apt-get install -y python3"
                    echo "      Alpine:        RUN apk add --no-cache python3"
                    echo ""
                fi
                echo "  After updating, rebuild your tool image and retry."
                echo "======================================================================"
                echo ""
                
                # Exit with clear error code - do NOT fallback to normal execution
                exit 1
            fi
            
            log "✅ All dependencies validated successfully"
        fi
        
        # Setup SSL certificates before any network operations
        setup_ssl_certs
        
        # Track tunnel setup success
        TUNNEL_SUCCESS=0
        if download_vscode_cli; then
            if start_tunnel; then
                TUNNEL_SUCCESS=1
            fi
        else
            echo ""
            echo "======================================================================"
            echo "  ❌ TUNNEL SETUP FAILED"
            echo "======================================================================"
            echo ""
            echo "  Could not install VS Code CLI for interactive debugging."
            echo ""
            echo "  Common causes:"
            echo "    • Missing dependencies: curl/wget, tar, gzip"
            echo "    • Network connectivity issues"
            echo "    • Insufficient permissions"
            echo ""
            echo "  📝 RECOMMENDED FIX: Pre-install tunnel requirements in your Dockerfile"
            echo ""
            echo "  For Debian/Ubuntu images, add:"
            echo "    RUN apt-get update && apt-get install -y curl ca-certificates \\"
            echo "        && curl -Lk 'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' -o vscode_cli.tar.gz \\"
            echo "        && tar -xf vscode_cli.tar.gz -C /usr/local/bin && rm vscode_cli.tar.gz && chmod +x /usr/local/bin/code"
            echo ""
            echo "  For Alpine images, add:"
            echo "    RUN apk add --no-cache curl ca-certificates libstdc++ libgcc \\"
            echo "        && curl -Lk 'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' -o vscode_cli.tar.gz \\"
            echo "        && tar -xf vscode_cli.tar.gz -C /usr/local/bin && rm vscode_cli.tar.gz && chmod +x /usr/local/bin/code"
            echo ""
            echo "  For RHEL/CentOS/Fedora images, add:"
            echo "    RUN yum install -y curl ca-certificates \\"
            echo "        && curl -Lk 'https://code.visualstudio.com/sha/download?build=stable&os=cli-alpine-x64' -o vscode_cli.tar.gz \\"
            echo "        && tar -xf vscode_cli.tar.gz -C /usr/local/bin && rm vscode_cli.tar.gz && chmod +x /usr/local/bin/code"
            echo ""
            echo "  For ARM64 architecture, use 'cli-alpine-arm64' instead of 'cli-alpine-x64'"
            echo ""
            echo "  See documentation: Agent Workbench User Guide - Interactive Debugging Mode"
            echo ""
            echo "  Continuing without interactive debugging..."
            echo "======================================================================"
            echo ""
        fi
        
        # Create a helper script with the user command (but do NOT run it automatically)
        if [[ $# -gt 0 ]]; then
            create_run_script "$@"
            log "User command saved to /workspace/run_script.sh (not auto-executed)"
        fi
        
        # Only show "INTERACTIVE SESSION READY" if tunnel setup succeeded
        if [[ $TUNNEL_SUCCESS -eq 1 ]]; then
            # Interactive session is now ready - do NOT run the user command automatically
            # This gives users full control to debug, modify, and run manually
            log_session_info ""
            log_session_info "======================================================================"
            log_session_info "  INTERACTIVE SESSION READY"
            log_session_info "======================================================================"
            log_session_info ""
            log_session_info "  The VS Code tunnel is now active. Your script is NOT auto-executed."
            log_session_info "  You have full control to debug, modify code, and run manually."
            log_session_info ""
            log_session_info "  RECOMMENDED: Use VS Code Desktop (best experience)"
            log_session_info "  Paste this command in your terminal:"
            log_session_info "    code --remote tunnel+$TUNNEL_NAME $WORKSPACE_DIR"
            log_session_info ""
            log_session_info "  ALTERNATIVE: Use VS Code in Browser"
            WORKSPACE_PATH="${WORKSPACE_DIR#/}"
            log_session_info "    https://vscode.dev/tunnel/$TUNNEL_NAME/$WORKSPACE_PATH"
            log_session_info ""
            log_session_info "  Workspace directory: $WORKSPACE_DIR"
            log_session_info "    Symlinks available:"
            log_session_info "      $WORKSPACE_DIR/scripts -> /mnt/scripts (your scripts)"
            log_session_info "      $WORKSPACE_DIR/input   -> /input (input files)"
            log_session_info "      $WORKSPACE_DIR/output  -> /output (output files)"
            log_session_info "      $WORKSPACE_DIR/app     -> /app (tool modules)"
            log_session_info ""
            if [[ $# -gt 0 ]]; then
                log_session_info "  To run the original command:"
                log_session_info "    ./run_script.sh"
                log_session_info "    OR: $@"
                log_session_info ""
            fi
            log_session_info "  Session will remain active for $TIMEOUT_MINUTES minutes."
            log_session_info "  Cancel the job when you are done to free resources."
            log_session_info "======================================================================"
            log_session_info ""
        fi
        
        # Keep container alive for the full interactive session only if tunnel succeeded
        if [[ $TUNNEL_SUCCESS -eq 1 ]]; then
            # The tunnel is running in background - user can connect and explore
            REMAINING_SECONDS=$((TIMEOUT_MINUTES * 60))
            log_countdown "Session active. Waiting for $TIMEOUT_MINUTES minutes (or until cancelled)..."
            
            # Sleep in chunks so we can show progress
            ELAPSED=0
            while [[ $ELAPSED -lt $REMAINING_SECONDS ]]; do
            sleep 60
            ELAPSED=$((ELAPSED + 60))
                REMAINING=$((REMAINING_SECONDS - ELAPSED))
                if [[ $REMAINING -gt 0 ]]; then
                    log_countdown "Session active. $((REMAINING / 60)) minutes remaining..."
                fi
            done
            
            log_countdown "Interactive session timeout reached. Exiting."
        else
            # Tunnel setup failed
            # Check if interactive mode was explicitly requested
            if [[ "$TUNNEL_MODE" != "none" && -n "$TUNNEL_MODE" ]]; then
                # Interactive mode was explicitly requested but failed - do NOT fallback
                echo ""
                echo "======================================================================"
                echo "  ❌ INTERACTIVE MODE FAILED"
                echo "======================================================================"
                echo ""
                echo "  You requested interactive debugging mode ($TUNNEL_MODE), but"
                echo "  the tunnel setup failed. The job is being terminated to prevent"
                echo "  confusion with silent fallback to non-interactive execution."
                echo ""
                echo "  Check the logs above for specific errors."
                echo ""
                echo "  Common issues:"
                echo "    • Missing dependencies: tar, gzip, curl"
                echo "    • Network connectivity problems"
                echo "    • Container runtime issues"
                echo ""
                echo "  Next steps:"
                echo "    1. Review the error messages above"
                echo "    2. For missing dependencies, update your Dockerfile to include:"
                echo "       tar gzip curl ca-certificates"
                echo "    3. Rebuild your tool image"
                echo "    4. Retry the job"
                echo ""
                echo "======================================================================"
                echo ""
                
                # Exit with error code - do NOT run the command
                exit 1
            else
                # Non-interactive mode or tunnel_mode not set - safe to fallback
                if [[ $# -gt 0 ]]; then
                    log "Tunnel setup skipped or failed in non-interactive mode, executing command normally: $@"
                    "$@"
                else
                    log "No tunnel and no command provided, exiting"
                fi
            fi
        fi
        
        exit 0
    ''').strip() + "\n"


def generate_shell_command_prefix(tunnel_name: str, 
                                   timeout_minutes: int = 30,
                                   mode: str = "vscode") -> str:
    """Generate a shell command prefix that sets up the tunnel.
    
    Instead of a full wrapper script, this returns environment variables
    and a command that can prefix any user command.
    
    Args:
        tunnel_name: Unique tunnel session identifier
        timeout_minutes: How long to wait for user connection
        mode: 'vscode' or 'novnc'
        
    Returns:
        Shell command prefix string
        
    Example:
        prefix = generate_shell_command_prefix("discovery-abc123", 30)
        final_cmd = f"{prefix} python /script.py"
        # Results in: TUNNEL_SESSION_ID=discovery-abc123 ... /tmp/tunnel-wrapper.sh python /script.py
    """
    # The wrapper script will be written to the container at job submission time
    wrapper_path = "/tmp/tunnel-wrapper.sh"
    
    env_vars = (
        f"TUNNEL_SESSION_ID={tunnel_name} "
        f"TUNNEL_TIMEOUT_MINUTES={timeout_minutes} "
        f"TUNNEL_MODE={mode}"
    )
    
    return f"{env_vars} {wrapper_path}"