"""
Simplified Docker Image Publisher for Azure Container Registry (ACR)
Optimized for web interface integration with the agent testing tool.

This script builds and publishes Docker images to an Azure Container Registry
with simplified functionality focused on the web interface use case.
"""

import os
import sys
import subprocess
import json
import re
import base64
import urllib.request
import urllib.error
from pathlib import Path
from io import StringIO

# Global variable to collect verbose output
_verbose_output = []

def log_verbose(message):
    """Add a message to the verbose output log."""
    global _verbose_output
    _verbose_output.append(message)
    print(message)  # Still print to console
    sys.stdout.flush()  # Ensure immediate output

def get_verbose_output():
    """Get all collected verbose output."""
    global _verbose_output
    return _verbose_output.copy()

def clear_verbose_output():
    """Clear the verbose output log."""
    global _verbose_output
    _verbose_output = []


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Terminate a subprocess and its children as best as possible.

    Notes:
    - On Windows we use taskkill /T to kill the full tree.
    - On POSIX we try to terminate the process group (requires preexec_fn=os.setsid).
    """
    try:
        if not process:
            return
        if process.poll() is not None:
            return

        if os.name == 'nt':
            # /T kills the process tree, /F forces termination.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
        else:
            import signal

            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except Exception:
                process.terminate()
    except Exception as e:
        log_verbose(f"Warning: failed to terminate process tree (pid={getattr(process, 'pid', None)}): {e}")

def run_command(command, cwd=None, capture_output=True, timeout=300, stream_output=False):
    """Run a shell command and return the result."""
    log_verbose(f"Running: {command}")
    try:
        if capture_output and not stream_output:
            result = subprocess.run(
                command, 
                shell=True, 
                cwd=cwd, 
                capture_output=True, 
                text=True, 
                encoding='utf-8',  # Explicitly use UTF-8 for Windows compatibility
                errors='replace',  # Replace problematic bytes
                timeout=timeout
            )
            if result.returncode != 0:
                log_verbose(f"Error running command: {command}")
                log_verbose(f"STDOUT: {result.stdout}")
                log_verbose(f"STDERR: {result.stderr}")
                return None
            return result.stdout.strip()
        elif stream_output:
            # For commands where we want to capture output in real-time
            process = subprocess.Popen(
                command, 
                shell=True, 
                cwd=cwd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',  # Explicitly use UTF-8 for Windows compatibility
                errors='replace',  # Replace problematic bytes
                bufsize=1, 
                universal_newlines=True
            )
            
            output_lines = []
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    line = output.strip()
                    log_verbose(line)
                    output_lines.append(line)
            
            return_code = process.poll()
            if return_code != 0:
                log_verbose(f"Command failed with return code: {return_code}")
                return False
            return True
        else:
            result = subprocess.run(command, shell=True, cwd=cwd, timeout=timeout)
            return result.returncode == 0
    except subprocess.TimeoutExpired:
        log_verbose(f"Command timed out after {timeout} seconds: {command}")
        return None
    except Exception as e:
        log_verbose(f"Exception running command: {command}, Error: {e}")
        return None

def extract_acr_name(acr_resource_id):
    """Extract ACR name from resource ID."""
    # Resource ID format: /subscriptions/.../resourceGroups/.../providers/Microsoft.ContainerRegistry/registries/acrname
    match = re.search(r'/registries/([^/]+)$', acr_resource_id)
    if match:
        return match.group(1)
    raise ValueError(f"Invalid ACR resource ID format: {acr_resource_id}")

def get_acr_registry_host(acr_name):
    """Get the full ACR registry hostname, handling cases where acr_name already includes .azurecr.io"""
    if acr_name.endswith('.azurecr.io'):
        return acr_name
    else:
        return f"{acr_name}.azurecr.io"


def check_docker():
    """Check if Docker is installed and running."""
    # Check if Docker daemon is running (this also confirms installation)
    result = run_command("docker info")
    if result is None:
        return False, "Docker is not installed or daemon is not running. Please install Docker and start the daemon"
    
    return True, "Docker is available and running"


def login_to_acr(acr_name, tenant_id=None, subscription_id=None, acr_token_name=None, acr_token_password=None):
    """Login to Azure Container Registry using either token authentication or Azure SDK authentication.
    
    Args:
        acr_name: Name of the ACR
        tenant_id: Optional tenant ID for tenant-aware authentication
        subscription_id: Optional subscription ID to derive tenant if tenant_id not provided
        acr_token_name: Optional ACR token name for token-based authentication
        acr_token_password: Optional ACR token password for token-based authentication
    """
    script_dir = None  # Initialize to None for cleanup tracking
    try:
        # Get ACR registry hostname
        acr_login_server = get_acr_registry_host(acr_name)
        
        # PRIORITY 1: Check if ACR token credentials are provided
        if acr_token_name and acr_token_password:
            log_verbose("🔑 Using ACR token-based authentication")
            log_verbose(f"   Token name: {acr_token_name}")
            log_verbose(f"   Token password length: {len(acr_token_password)} chars")
            log_verbose(f"   Token password first 8 chars: {acr_token_password[:8]}...")
            log_verbose(f"   ACR server: {acr_login_server}")
            log_verbose(f"   Running: docker login {acr_login_server} --username {acr_token_name} --password-stdin")
            
            try:
                # Use ACR token for direct authentication
                process = subprocess.Popen(
                    ["docker", "login", acr_login_server, "--username", acr_token_name, "--password-stdin"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                stdout, stderr = process.communicate(input=acr_token_password, timeout=30)
                
                if process.returncode != 0:
                    log_verbose(f"❌ Docker login with token failed (returncode={process.returncode})")
                    log_verbose(f"   stdout: {stdout}")
                    log_verbose(f"   stderr: {stderr}")
                    return False, f"Failed to login to ACR with token: {acr_login_server} - {stderr}"
                
                log_verbose("✅ Docker login with ACR token succeeded")
                log_verbose(f"   stdout: {stdout}")
                return True, f"Successfully logged in to ACR using token: {acr_login_server}"
                
            except subprocess.TimeoutExpired:
                log_verbose("❌ Docker login with token timed out")
                return False, f"Docker login to ACR timed out: {acr_login_server}"
            except Exception as token_err:
                log_verbose(f"❌ Docker login with token exception: {str(token_err)}")
                return False, f"Failed to login to ACR with token: {str(token_err)}"
        
        # PRIORITY 2: Fall back to Azure AD authentication
        log_verbose("🔑 Using Azure AD authentication (no ACR token provided)")
        
        # Import the centralized auth helper
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, script_dir)
        from azure_auth_helpers import get_token_for_tenant, get_token_default_credential
        
        # Get ARM management token - use tenant-aware authentication if tenant_id provided
        # ACR token exchange requires an ARM token, not a container registry token
        server_traces = []
        arm_scope = "https://management.azure.com/.default"
        
        if tenant_id:
            # Use explicit tenant
            acr_token = get_token_for_tenant(arm_scope, tenant_id, server_traces, purpose='ACR login')
        else:
            return False, "Explicit tenant_id is required to login to ACR; provide tenant_id or configure it in Settings."
        
        if not acr_token:
            error_msg = "Failed to get ARM token"
            if server_traces:
                error_msg += f": {server_traces[-1]}"
            return False, error_msg
        
        # Get ACR registry hostname (already done above for token auth path)
        # acr_login_server = get_acr_registry_host(acr_name)
        
        # For ACR authentication with Azure AD, we need to exchange the token for an ACR refresh token
        # This is done by calling the ACR token exchange endpoint
        log_verbose(f"Exchanging Azure AD token for ACR refresh token...")
        
        try:
            import requests
            import json
            
            # Step 1: Exchange AAD token for ACR refresh token
            exchange_url = f"https://{acr_login_server}/oauth2/exchange"
            exchange_payload = {
                "grant_type": "access_token",
                "service": acr_login_server,
                "access_token": acr_token
            }
            
            exchange_response = requests.post(
                exchange_url,
                data=exchange_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )
            
            if exchange_response.status_code != 200:
                log_verbose(f"Token exchange failed: {exchange_response.status_code} - {exchange_response.text}")
                return False, f"Failed to exchange token with ACR: {exchange_response.status_code}"
            
            refresh_token = exchange_response.json().get("refresh_token")
            if not refresh_token:
                return False, "Failed to get refresh token from ACR"
            
            log_verbose(f"Successfully exchanged token for ACR refresh token")
            log_verbose(f"Logging into Docker with ACR refresh token: {acr_login_server}")
            
            # Step 2: Use the refresh token to login to Docker
            # For refresh tokens, username should be "00000000-0000-0000-0000-000000000000"
            process = subprocess.Popen(
                ["docker", "login", acr_login_server, "--username", "00000000-0000-0000-0000-000000000000", "--password-stdin"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=refresh_token, timeout=30)
            
            if process.returncode != 0:
                log_verbose(f"Docker login failed: {stderr}")
                return False, f"Failed to login to ACR: {acr_login_server} - {stderr}"
            
            log_verbose("Docker login succeeded")
            return True, f"Successfully logged in to ACR: {acr_login_server}"
            
        except requests.exceptions.RequestException as req_err:
            log_verbose(f"Request error during token exchange: {req_err}")
            return False, f"Failed to exchange token with ACR: {req_err}"
        except Exception as exchange_err:
            log_verbose(f"Error during token exchange: {exchange_err}")
            return False, f"Failed to exchange token: {exchange_err}"
        
    except ImportError:
        return False, "azure_auth_helpers module not available"
    except subprocess.TimeoutExpired:
        log_verbose("Docker login timed out")
        return False, f"Docker login to ACR timed out: {acr_login_server}"
    except Exception as e:
        log_verbose(f"Docker login exception: {str(e)}")
        return False, f"Failed to login to ACR: {str(e)}"
    finally:
        # Clean up sys.path (only if we added it for Azure AD auth)
        if script_dir is not None and sys.path and len(sys.path) > 0 and sys.path[0] == script_dir:
            sys.path.pop(0)


def build_docker_image(dockerfile_path, image_name, tag):
    """Build Docker image from Dockerfile."""
    dockerfile_dir = Path(dockerfile_path).parent
    full_image_name = f"{image_name}:{tag}"
    
    log_verbose(f"Building Docker image: {full_image_name}")
    log_verbose(f"Build context: {dockerfile_dir}")
    
    # Build the image with streaming output
    command = f"docker build -f \"{dockerfile_path}\" -t {full_image_name} \"{dockerfile_dir}\""
    success = run_command(command, capture_output=False, stream_output=True, timeout=600)  # 10 minute timeout for builds
    
    if not success:
        return False, f"Failed to build Docker image: {full_image_name}"
    
    return True, f"Successfully built Docker image: {full_image_name}"

def tag_and_push_image(local_image_name, local_tag, acr_name, remote_image_name, remote_tag):
    """Tag the local image for ACR and push it."""
    local_full_name = f"{local_image_name}:{local_tag}"
    acr_registry_host = get_acr_registry_host(acr_name)
    remote_full_name = f"{acr_registry_host}/{remote_image_name}:{remote_tag}"
    
    log_verbose(f"Tagging image: {local_full_name} -> {remote_full_name}")
    
    # Tag the image for ACR (this is usually quick, so no streaming needed)
    success = run_command(f"docker tag {local_full_name} {remote_full_name}", capture_output=False)
    if not success:
        return False, f"Failed to tag image: {remote_full_name}"
    
    log_verbose(f"Pushing image to ACR: {remote_full_name}")
    
    # Push the image to ACR with streaming output
    success = run_command(f"docker push {remote_full_name}", capture_output=False, stream_output=True, timeout=900)  # 15 minute timeout for push
    if not success:
        return False, f"Failed to push image: {remote_full_name}"
    
    return True, f"Successfully pushed image: {remote_full_name}"

def generate_image_name_from_path(dockerfile_directory):
    """Generate a reasonable image name from the directory path."""
    path_parts = Path(dockerfile_directory).parts
    
    # Look for patterns like "SolutionName/1-Tool" or "SolutionName/2-Tool"
    solution_name = None
    component_type = None
    
    for i, part in enumerate(path_parts):
        if part.endswith("-Tool") or part.endswith("-Model"):
            if i > 0:
                solution_name = path_parts[i-1].lower()
                component_type = part.split("-")[1].lower()  # "tool" or "model"
            break
    
    if solution_name and component_type:
        return f"{solution_name}-{component_type}"
    
    # Fallback: use the last meaningful directory name
    for part in reversed(path_parts):
        if part not in ["a-core", "i-Docker files", "Docker files", "files"]:
            return part.lower().replace(" ", "-")
    
    return "agent-tool"

def run_command_streaming(command, cwd=None, timeout=300, stream_callback=None, cancel_event=None):
    """Run a shell command and stream output in real-time.

    Args:
        cancel_event: Optional threading.Event; when set, terminates the underlying process.
    """
    if stream_callback:
        stream_callback(f"Running: {command}")
    
    process = None
    try:
        import sys
        import threading

        popen_kwargs = {}
        if os.name == 'nt' and hasattr(subprocess, 'CREATE_NEW_PROCESS_GROUP'):
            popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        elif os.name != 'nt':
            popen_kwargs['preexec_fn'] = os.setsid

        process = subprocess.Popen(
            command, 
            shell=True, 
            cwd=cwd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',  # Explicitly use UTF-8 to handle Docker output on Windows
            errors='replace',  # Replace problematic bytes instead of failing
            bufsize=1,  # Line buffered
            universal_newlines=True,
            **popen_kwargs
        )

        cancel_watcher = None
        if cancel_event is not None and hasattr(cancel_event, 'wait'):
            def _watch_cancel():
                try:
                    cancel_event.wait()
                    if stream_callback:
                        stream_callback("🛑 Cancel requested. Terminating Docker process...")
                    _terminate_process_tree(process)
                except Exception:
                    # Best-effort cancellation: never raise from watcher.
                    pass

            cancel_watcher = threading.Thread(target=_watch_cancel, daemon=True)
            cancel_watcher.start()
        
        # Stream output line by line
        if process.stdout:
            for line in iter(process.stdout.readline, ''):
                line = line.rstrip()
                if line and stream_callback:
                    stream_callback(line)
        
        # Wait for process to complete
        if cancel_event is not None and getattr(cancel_event, 'is_set', None) and cancel_event.is_set():
            # The watcher thread should already be terminating the process.
            return False

        process.wait(timeout=timeout)
        
        if process.returncode != 0:
            error_msg = f"Command failed with exit code {process.returncode}: {command}"
            if stream_callback:
                stream_callback(f"❌ {error_msg}")
            return False
        
        return True
        
    except subprocess.TimeoutExpired:
        if process:
            _terminate_process_tree(process)
        error_msg = f"Command timed out after {timeout} seconds: {command}"
        if stream_callback:
            stream_callback(f"❌ {error_msg}")
        return False
    except Exception as e:
        if cancel_event is not None and getattr(cancel_event, 'is_set', None) and cancel_event.is_set():
            if process:
                _terminate_process_tree(process)
        error_msg = f"Exception running command: {command}, Error: {e}"
        if stream_callback:
            stream_callback(f"❌ {error_msg}")
        return False

def generate_tool_definition_json_with_env_vars(dockerfile_directory, environment_variables=None, output_directory=None):
    """
    Generate a tool definition JSON file with environment variables included in properties section.
    
    Args:
        dockerfile_directory: Directory containing the Dockerfile and tool definition
        environment_variables: Dict of environment variables to include
        output_directory: Directory to output the JSON file (optional)
    
    Returns:
        (success, json_file_path, message)
    """
    try:
        # Find tool definition YAML file in the same directory as Dockerfile
        dockerfile_directory = Path(dockerfile_directory)
        
        # Look for tool definition YAML files
        tool_def_patterns = ["*-tool-definition.yaml", "*-tool-definition.yml", 
                           "*-tools-definition.yaml", "*-tools-definition.yml",
                           "*-Tool.yaml", "*-Tool.yml"]
        
        tool_def_file = None
        for pattern in tool_def_patterns:
            matches = list(dockerfile_directory.glob(pattern))
            if matches:
                tool_def_file = matches[0]
                break
        
        if not tool_def_file:
            # Look in parent directory (for a-core structure)
            parent_dir = dockerfile_directory.parent
            for pattern in tool_def_patterns:
                matches = list(parent_dir.glob(pattern))
                if matches:
                    tool_def_file = matches[0]
                    break
        
        if not tool_def_file:
            return False, None, f"No tool definition YAML file found in {dockerfile_directory} or parent directory"
        
        log_verbose(f"Found tool definition file: {tool_def_file}")
        
        # Load YAML data
        import yaml
        with open(tool_def_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        # Add environment variables to properties section if provided
        if environment_variables:
            if 'properties' not in data:
                data['properties'] = {}
            data['properties']['environmentVariables'] = environment_variables
            log_verbose(f"Added environment variables to properties: {list(environment_variables.keys())}")
        
        # Generate output file path
        if output_directory:
            output_dir = Path(output_directory)
        else:
            output_dir = tool_def_file.parent
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate JSON filename based on YAML filename
        json_filename = tool_def_file.stem + '.json'
        json_file_path = output_dir / json_filename
        
        # Write JSON file
        with open(json_file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=True)
        
        log_verbose(f"Generated tool definition JSON: {json_file_path}")
        return True, str(json_file_path), f"Successfully generated {json_file_path}"
        
    except Exception as e:
        return False, None, f"Error generating tool definition JSON: {str(e)}"

def deploy_to_acr_streaming(dockerfile_directory, acr_name, image_name=None, tag="latest",
                           remote_image_name=None, remote_tag=None, stream_callback=None, skip_acr_login=False,
                           use_buildx=True, platforms: str = "linux/amd64", skip_prereq_checks=False,
                           tenant_id=None, subscription_id=None, skip_build=False, cancel_event=None,
                           acr_token_name=None, acr_token_password=None):
    """
    Streaming deployment function for web interface.
    Returns (success, message, image_url)
    
    Args:
        skip_acr_login: If True, skip the ACR login step (assumes already authenticated)
        skip_build: If True, skip building and only tag+push existing local image
        tenant_id: Optional tenant ID for tenant-aware authentication
        subscription_id: Optional subscription ID to derive tenant if tenant_id not provided
        acr_token_name: Optional ACR token name for token-based authentication
        acr_token_password: Optional ACR token password for token-based authentication
    """
    import re
    
    # Track progress state for intelligent filtering
    progress_state = {
        'last_layer': None, 
        'pushed_count': 0, 
        'skipped_count': 0,
        'waiting_layers': set(),
        'last_waiting_report': 0
    }
    
    def stream(msg):
        if stream_callback:
            stream_callback(msg)
    
    def stream_with_progress(msg):
        """Enhanced streaming that parses and formats Docker progress output."""
        if not stream_callback:
            return
        
        # Parse Docker push progress: "abc123de: Pushing [==>  ] 123.4MB/456.7MB"
        push_match = re.match(r'^([a-f0-9]+):\s+Pushing\s+\[([=>\s]+)\]\s+([\d.]+\w+)/([\d.]+\w+)', msg)
        if push_match:
            layer_id = push_match.group(1)[:12]
            progress_bar = push_match.group(2)
            current = push_match.group(3)
            total = push_match.group(4)
            # Calculate approximate percentage from progress bar
            filled = progress_bar.count('=')
            total_chars = len(progress_bar)
            pct = int((filled / total_chars * 100)) if total_chars > 0 else 0
            stream_callback(f"📦 Layer {layer_id}: Pushing {current}/{total} ({pct}%)")
            progress_state['last_layer'] = layer_id
            progress_state['waiting_layers'].discard(layer_id)
            return
        
        # Parse layer waiting: "abc123de: Waiting"
        waiting_match = re.match(r'^([a-f0-9]+):\s+Waiting', msg)
        if waiting_match:
            layer_id = waiting_match.group(1)[:12]
            progress_state['waiting_layers'].add(layer_id)
            # Only report waiting status periodically to avoid spam
            import time
            now = time.time()
            if now - progress_state['last_waiting_report'] > 2:  # Report every 2 seconds
                waiting_count = len(progress_state['waiting_layers'])
                if waiting_count > 0:
                    stream_callback(f"⏳ Waiting to push {waiting_count} layer(s)...")
                    progress_state['last_waiting_report'] = now
            return
        
        # Parse layer completion: "abc123de: Pushed"
        pushed_match = re.match(r'^([a-f0-9]+):\s+(Pushed|Layer already exists)', msg)
        if pushed_match:
            layer_id = pushed_match.group(1)[:12]
            status = pushed_match.group(2)
            progress_state['waiting_layers'].discard(layer_id)
            if status == "Pushed":
                stream_callback(f"✅ Layer {layer_id}: Pushed")
                progress_state['pushed_count'] += 1
            else:
                stream_callback(f"⏭️  Layer {layer_id}: Already exists (skipped)")
                progress_state['skipped_count'] += 1
            return
        
        # Parse buildx progress: "#5 [2/4] RUN ..."
        buildx_match = re.match(r'^#\d+\s+\[(\d+)/(\d+)\]\s+(.+)', msg)
        if buildx_match:
            current_step = buildx_match.group(1)
            total_steps = buildx_match.group(2)
            step_desc = buildx_match.group(3)[:60]  # Truncate long commands
            pct = int((int(current_step) / int(total_steps)) * 100)
            stream_callback(f"🔨 Step {current_step}/{total_steps} ({pct}%): {step_desc}")
            return
        
        # Parse buildx transfer: "transferring context: 123.4MB"
        transfer_match = re.search(r'transferring\s+\w+:\s+([\d.]+\w+)', msg)
        if transfer_match:
            size = transfer_match.group(1)
            stream_callback(f"📤 Transferring context: {size}")
            return
        
        # Filter out noisy BuildKit lines but keep meaningful ones
        if msg.startswith('#') or 'exporting to image' in msg.lower() or 'writing image' in msg.lower():
            # Keep exporting/writing messages
            if any(word in msg.lower() for word in ['exporting', 'writing', 'pushing', 'done']):
                stream_callback(msg)
            return
        
        # Pass through all other messages
        if msg.strip():
            stream_callback(msg)

    def _check_cancel(stage: str) -> bool:
        if cancel_event is not None and getattr(cancel_event, 'is_set', None) and cancel_event.is_set():
            stream(f"🛑 Cancelled by user ({stage}).")
            return True
        return False
    
    try:
        # Validate inputs: require an explicit Dockerfile path (no guessing).
        dockerfile_path_arg = Path(dockerfile_directory)
        if not dockerfile_path_arg.exists() or not dockerfile_path_arg.is_file():
            error_msg = (f"Invalid Dockerfile path provided: {dockerfile_path_arg}. "
                         "The agents catalog must provide an explicit existing Dockerfile path.")
            stream(f"❌ {error_msg}")
            return False, error_msg, None

        # Ensure filename begins with 'Dockerfile' to avoid misuse
        if not dockerfile_path_arg.name.lower().startswith('dockerfile'):
            error_msg = f"Provided file is not a Dockerfile (expected name starting with 'Dockerfile'): {dockerfile_path_arg.name}"
            stream(f"❌ {error_msg}")
            return False, error_msg, None

        dockerfile_path = str(dockerfile_path_arg)
        dockerfile_dir = dockerfile_path_arg.parent
        stream(f"Using explicit Dockerfile path: {dockerfile_path}")

        if _check_cancel("init"):
            return False, "Cancelled", None
        
        # Generate image name if not provided
        if not image_name:
            image_name = generate_image_name_from_path(dockerfile_directory)
        
        if not remote_image_name:
            remote_image_name = image_name
        if not remote_tag:
            remote_tag = tag
        
        # Get the full ACR registry hostname
        acr_registry_host = get_acr_registry_host(acr_name)
        
        stream(f"📋 Configuration:")
        stream(f"   Dockerfile directory: {dockerfile_directory}")
        stream(f"   Local image name: {image_name}:{tag}")
        stream(f"   ACR name: {acr_name}")
        stream(f"   Remote image name: {remote_image_name}:{remote_tag}")
        if use_buildx:
            stream(f"   Using docker buildx with platforms: {platforms}")
        
        # Check prerequisites (skip if already verified)
        if not skip_prereq_checks:
            stream(f"🔍 Checking Docker...")
            success, message = check_docker()
            if not success:
                stream(f"❌ {message}")
                return False, message, None
            stream(f"✅ Docker ready")
        else:
            stream(f"⏭️  Skipping prerequisite checks (already verified)")

        if _check_cancel("pre-login"):
            return False, "Cancelled", None
        
        # Login to ACR (skip if already authenticated)
        if skip_acr_login:
            stream(f"⏭️  Skipping ACR login (already authenticated)")
        else:
            if acr_token_name and acr_token_password:
                stream(f"🔐 Logging into ACR using token authentication: {acr_name}")
            else:
                stream(f"🔐 Logging into ACR using Azure AD: {acr_name}")
            success, message = login_to_acr(acr_name, tenant_id=tenant_id, subscription_id=subscription_id, 
                                           acr_token_name=acr_token_name, acr_token_password=acr_token_password)
            if not success:
                stream(f"❌ {message}")
                return False, message, None
            stream(f"✅ ACR login successful")

        if _check_cancel("post-login"):
            return False, "Cancelled", None
        
        remote_full_name = f"{acr_registry_host}/{remote_image_name}:{remote_tag}"
        
        if skip_build:
            # Skip build - only tag and push existing local image
            local_full_name = f"{image_name}:{tag}"
            stream(f"⏭️  Skipping build (using pre-built image)")
            stream(f"🔍 Verifying local image exists: {local_full_name}")
            
            # Verify local image exists
            check_cmd = f"docker image inspect {local_full_name}"
            if run_command(check_cmd) is None:
                error_msg = f"Local image not found: {local_full_name}. Please build the image first using 'Build & Start' button."
                stream(f"❌ {error_msg}")
                return False, error_msg, None
            stream(f"✅ Local image found: {local_full_name}")
            
            stream(f"🏷️  Tagging image: {local_full_name} → {remote_full_name}")
            tag_command = f"docker tag {local_full_name} {remote_full_name}"
            if not run_command_streaming(tag_command, stream_callback=stream, cancel_event=cancel_event):
                return False, f"Failed to tag image: {remote_full_name}", None
            
            stream(f"⬆️  Pushing image to ACR: {remote_full_name}")
            push_command = f"docker push {remote_full_name}"
            if not run_command_streaming(push_command, timeout=900, stream_callback=stream_with_progress, cancel_event=cancel_event):
                return False, f"Failed to push image: {remote_full_name}", None
            
            # Summary message
            pushed = progress_state.get('pushed_count', 0)
            skipped = progress_state.get('skipped_count', 0)
            total = pushed + skipped
            if skipped > 0 and pushed == 0:
                stream(f"✅ Push completed: All {total} layers already exist in ACR (no upload needed)")
            elif pushed > 0:
                stream(f"✅ Push completed: {pushed} layer(s) uploaded, {skipped} already existed ({total} total)")
            else:
                stream(f"✅ Push completed: {remote_full_name}")
        elif use_buildx:
            # Ensure buildx available
            stream("🔍 Checking docker buildx...")
            if run_command("docker buildx version") is None:
                stream("❌ docker buildx not available. Install/enable Buildx in Docker Desktop.")
                return False, "docker buildx not available", None
            stream("✅ buildx ready")
            # Build and push directly for specified platform(s)
            stream(f"🔨 Building and pushing (buildx) to: {remote_full_name}")
            buildx_cmd = (
                f"docker buildx build --progress=plain --platform {platforms} "
                f"-f \"{dockerfile_path}\" -t {remote_full_name} --push \"{dockerfile_dir}\""
            )
            if not run_command_streaming(buildx_cmd, timeout=1800, stream_callback=stream_with_progress, cancel_event=cancel_event):
                return False, f"Failed to build/push image via buildx: {remote_full_name}", None
            stream(f"✅ Buildx push completed: {remote_full_name}")
        else:
            # Classic path: build locally, tag, push (uses host arch)
            full_image_name = f"{image_name}:{tag}"
            stream(f"🔨 Building Docker image: {full_image_name}")
            stream(f"📁 Build context: {dockerfile_dir}")
            build_command = f"docker build --progress=plain -f \"{dockerfile_path}\" -t {full_image_name} \"{dockerfile_dir}\""
            if not run_command_streaming(build_command, timeout=600, stream_callback=stream_with_progress, cancel_event=cancel_event):
                return False, f"Failed to build Docker image: {full_image_name}", None
            stream(f"✅ Build completed: {full_image_name}")
            local_full_name = f"{image_name}:{tag}"
            stream(f"🏷️  Tagging image: {local_full_name} → {remote_full_name}")
            tag_command = f"docker tag {local_full_name} {remote_full_name}"
            if not run_command_streaming(tag_command, stream_callback=stream, cancel_event=cancel_event):
                return False, f"Failed to tag image: {remote_full_name}", None
            stream(f"⬆️  Pushing image to ACR: {remote_full_name}")
            push_command = f"docker push {remote_full_name}"
            if not run_command_streaming(push_command, timeout=900, stream_callback=stream_with_progress, cancel_event=cancel_event):
                return False, f"Failed to push image: {remote_full_name}", None

        # Build the final ACR image URL
        final_image_url = f"{acr_registry_host}/{remote_image_name}:{remote_tag}"

        return True, f"Successfully deployed image to ACR: {final_image_url}", final_image_url

    except Exception as e:
        error_msg = f"Deployment error: {str(e)}"
        stream(f"❌ {error_msg}")
        return False, error_msg, None

def deploy_to_acr(dockerfile_directory, acr_name, image_name=None, tag="latest",
                  remote_image_name=None, remote_tag=None, use_buildx=True, platforms: str = "linux/amd64",
                  environment_variables=None, tenant_id=None, subscription_id=None,
                  acr_token_name=None, acr_token_password=None):
    """
    Main deployment function for web interface.
    Returns (success, message, image_url, verbose_output)
    
    Args:
        environment_variables: Dict of environment variables to include in the tool definition JSON
        tenant_id: Optional tenant ID for tenant-aware authentication
        subscription_id: Optional subscription ID to derive tenant if tenant_id not provided
    """
    # Clear previous verbose output
    clear_verbose_output()
    
    try:
        # Validate inputs
        dockerfile_directory = Path(dockerfile_directory)
        if not dockerfile_directory.exists():
            return False, f"Directory does not exist: {dockerfile_directory}", None, get_verbose_output()
        
        # Generate image name if not provided
        if not image_name:
            image_name = generate_image_name_from_path(dockerfile_directory)
        
        if not remote_image_name:
            remote_image_name = image_name
        if not remote_tag:
            remote_tag = tag
        
        # Get the full ACR registry hostname
        acr_registry_host = get_acr_registry_host(acr_name)
        
        log_verbose(f"Configuration:")
        log_verbose(f"  Dockerfile directory: {dockerfile_directory}")
        log_verbose(f"  Local image name: {image_name}:{tag}")
        log_verbose(f"  ACR name: {acr_name}")
        log_verbose(f"  ACR registry host: {acr_registry_host}")
        log_verbose(f"  Remote image name: {remote_image_name}:{remote_tag}")
        if use_buildx:
            log_verbose(f"  Using docker buildx with platforms: {platforms}")
        
        # Check Docker is available
        success, message = check_docker()
        if not success:
            return False, message, None, get_verbose_output()
        
        # Login to ACR using token or Azure AD
        if acr_token_name and acr_token_password:
            log_verbose(f"Logging in to ACR using token authentication: {acr_name}")
        else:
            log_verbose(f"Logging in to ACR using Azure AD: {acr_name}")
        success, message = login_to_acr(acr_name, tenant_id=tenant_id, subscription_id=subscription_id,
                                       acr_token_name=acr_token_name, acr_token_password=acr_token_password)
        if not success:
            return False, message, None, get_verbose_output()
        
        # Validate inputs: require an explicit Dockerfile path (no guessing).
        dockerfile_path_arg = Path(dockerfile_directory)
        if not dockerfile_path_arg.exists() or not dockerfile_path_arg.is_file():
            return False, (f"Invalid Dockerfile path provided: {dockerfile_path_arg}. "
                           "The agents catalog must provide an explicit existing Dockerfile path."), None, get_verbose_output()

        if not dockerfile_path_arg.name.lower().startswith('dockerfile'):
            return False, (f"Provided file is not a Dockerfile (expected name starting with 'Dockerfile'): {dockerfile_path_arg.name}"), None, get_verbose_output()

        dockerfile_path = str(dockerfile_path_arg)
        dockerfile_dir = dockerfile_path_arg.parent
        log_verbose(f"Using explicit Dockerfile path: {dockerfile_path}")
        remote_full_name = f"{acr_registry_host}/{remote_image_name}:{remote_tag}"
        if use_buildx:
            # Ensure buildx available
            if run_command("docker buildx version") is None:
                return False, "docker buildx not available", None, get_verbose_output()
            # Buildx push directly to ACR
            buildx_cmd = (
                f"docker buildx build --platform {platforms} "
                f"-f \"{dockerfile_path}\" -t {remote_full_name} --push \"{dockerfile_dir}\""
            )
            ok = run_command(buildx_cmd, capture_output=False)
            if not ok:
                return False, f"Failed to build/push image via buildx: {remote_full_name}", None, get_verbose_output()
        else:
            # Classic: local build, tag, push
            success, message = build_docker_image(dockerfile_path, image_name, tag)
            if not success:
                return False, message, None, get_verbose_output()
            success, message = tag_and_push_image(image_name, tag, acr_name, remote_image_name, remote_tag)
            if not success:
                return False, message, None, get_verbose_output()

        # Build the final ACR image URL
        final_image_url = f"{acr_registry_host}/{remote_image_name}:{remote_tag}"
        
        # Generate tool definition JSON with environment variables
        if environment_variables:
            log_verbose("Generating tool definition JSON with environment variables...")
            success, json_path, message = generate_tool_definition_json_with_env_vars(
                dockerfile_directory, environment_variables
            )
            if success:
                log_verbose(f"Tool definition JSON generated: {json_path}")
            else:
                log_verbose(f"Warning: {message}")

        return True, f"Successfully deployed image to ACR: {final_image_url}", final_image_url, get_verbose_output()

    except Exception as e:
        return False, f"Deployment error: {str(e)}", None, get_verbose_output()
