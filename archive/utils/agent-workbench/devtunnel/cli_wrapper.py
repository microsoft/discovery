"""Dev Tunnel CLI wrapper for Agent Workbench.

Azure Dev Tunnels does not provide a Python SDK - the official interface
is the 'devtunnel' CLI binary. This module wraps CLI commands.

Why CLI wrapper instead of SDK:
- No official Python SDK exists for Azure Dev Tunnels
- The supercomputer-cli also uses CLI wrapper approach
- CLI is well-documented and stable

Prerequisites:
- devtunnel CLI installed (winget install Microsoft.devtunnel)
- User logged in (devtunnel user login)
"""
from __future__ import annotations
import json
import shutil
import subprocess
from typing import Optional, Callable, Union, Dict, Any, List

from .models import TunnelParameters, TunnelResult, TunnelToken


class DevTunnelError(RuntimeError):
    """Error from Dev Tunnel CLI operations."""
    pass


class DevTunnelCLI:
    """Wrapper around the devtunnel CLI binary."""
    
    def __init__(self, logger: Optional[Callable[[str], None]] = None):
        """Initialize CLI wrapper.
        
        Args:
            logger: Optional logging function for debug output
        """
        self._log = logger or (lambda msg: None)
    
    def _run(self, args: List[str], *, check: bool = True, 
             expect_json: bool = False) -> Union[str, Dict[str, Any]]:
        """Run devtunnel command and return output."""
        cmd = ["devtunnel"] + args
        self._log(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
        
        if check and result.returncode != 0:
            raise DevTunnelError(
                f"Command failed ({result.returncode}): {' '.join(cmd)}\n"
                f"STDERR: {result.stderr.strip()}"
            )
        
        output = result.stdout.strip()
        if expect_json:
            # Handle CLI welcome message that may precede JSON
            # Find the first '{' character and try to parse from there
            json_start = output.find('{')
            if json_start == -1:
                raise DevTunnelError(f"No JSON object found in CLI output: {output[:200]}")
            json_str = output[json_start:]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                raise DevTunnelError(f"Invalid JSON from CLI: {json_str[:200]}") from e
        return output
    
    # --- Status checks ---
    
    def is_installed(self) -> bool:
        """Check if devtunnel CLI is installed."""
        return shutil.which("devtunnel") is not None
    
    def is_logged_in(self) -> bool:
        """Check if user is logged in to Dev Tunnels."""
        if not self.is_installed():
            return False
        try:
            self._run(["user", "show"], check=True)
            return True
        except DevTunnelError:
            return False
    
    def get_current_user(self) -> Optional[str]:
        """Get current logged-in user info."""
        if not self.is_installed():
            return None
        try:
            return self._run(["user", "show"], check=True)
        except DevTunnelError:
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status of Dev Tunnel CLI."""
        installed = self.is_installed()
        return {
            "installed": installed,
            "logged_in": self.is_logged_in() if installed else False,
            "user": self.get_current_user() if installed else None
        }
    
    def get_setup_instructions(self) -> str:
        """Get instructions for setting up Dev Tunnels."""
        if not self.is_installed():
            return """Dev Tunnels CLI is not installed. To install:

  Windows:  winget install Microsoft.devtunnel
  macOS:    brew install --cask devtunnel  
  Linux:    curl -sL https://aka.ms/DevTunnelCliInstall | bash

After installation, login with:
  devtunnel user login
"""
        if not self.is_logged_in():
            return """Dev Tunnels CLI is installed but not logged in.

Run: devtunnel user login

This will open a browser for Azure authentication.
"""
        return "Dev Tunnels CLI is ready to use."
    
    # --- Tunnel operations ---
    
    def create_tunnel(self, name: str) -> TunnelResult:
        """Create a new dev tunnel."""
        data = self._run(["create", name, "--json"], expect_json=True)
        
        tunnel_data = data.get("tunnel", data)
        return TunnelResult(
            tunnel_id=tunnel_data.get("tunnelId", ""),
            host_connections=tunnel_data.get("hostConnections", 0),
            client_connections=tunnel_data.get("clientConnections", 0)
        )
    
    def add_port(self, tunnel_id: str, port: int, 
                 protocols: str = "https") -> None:
        """Add a port to an existing tunnel."""
        self._run([
            "port", "create", tunnel_id,
            "-p", str(port),
            "--protocol", protocols
        ])
        self._log(f"Added port {port} to tunnel {tunnel_id}")
    
    def get_tunnel_info(self, tunnel_id: str) -> Dict[str, Any]:
        """Get detailed tunnel information including port URLs."""
        return self._run(["show", tunnel_id, "--json"], expect_json=True)
    
    def create_token(self, tunnel_id: str) -> TunnelToken:
        """Create access token for tunnel."""
        data = self._run([
            "token", tunnel_id,
            "--scope", "manage",
            "--scope", "host",
            "--json"
        ], expect_json=True)
        
        return TunnelToken(
            tunnel_id=data.get("tunnelId", data.get("tunneldId", "")),
            scope=data.get("scope", ""),
            lifetime=data.get("lifeTime", data.get("lifetime", "")),
            expiration=data.get("expiration", ""),
            value=data.get("token", data.get("value", ""))
        )
    
    def delete_tunnel(self, tunnel_id: str) -> None:
        """Delete a tunnel."""
        try:
            self._run(["delete", tunnel_id, "-f"])
            self._log(f"Deleted tunnel: {tunnel_id}")
        except DevTunnelError as e:
            self._log(f"Warning: Failed to delete tunnel {tunnel_id}: {e}")
    
    def list_tunnels(self) -> List[Dict[str, Any]]:
        """List all tunnels for current user."""
        data = self._run(["list", "--json"], expect_json=True)
        return data if isinstance(data, list) else []
    
    # --- High-level operations ---
    
    def prepare_tunnel(self, params: TunnelParameters) -> TunnelResult:
        """Create tunnel with ports and token - ready to use.
        
        This is the main entry point for creating a fully configured tunnel.
        """
        # Ensure logged in
        if params.ensure_login and not self.is_logged_in():
            raise DevTunnelError(
                "Not logged in to Dev Tunnels. Run: devtunnel user login"
            )
        
        # Create tunnel
        tunnel = self.create_tunnel(params.name)
        self._log(f"Created tunnel: {tunnel.tunnel_id}")
        
        # Add ports
        for port_spec in params.ports:
            self.add_port(
                tunnel.tunnel_id, 
                port_spec.port, 
                port_spec.protocols_string()
            )
        
        # Get port URLs
        info = self.get_tunnel_info(tunnel.tunnel_id)
        tunnel_info = info.get("tunnel", info)
        for port_info in tunnel_info.get("ports", []):
            port_num = port_info.get("portNumber")
            port_uri = port_info.get("portUri", "")
            if port_num:
                tunnel.ports[port_num] = port_uri
                self._log(f"Port {port_num} URL: {port_uri}")
        
        # Create token
        tunnel.token = self.create_token(tunnel.tunnel_id)
        self._log(f"Created token: {tunnel.token.redacted()}")
        
        return tunnel
