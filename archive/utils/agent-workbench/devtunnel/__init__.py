"""Dev Tunnel integration for Agent Workbench.

This module provides interactive remote access to Discovery Supercomputer jobs
using Azure Dev Tunnels. It supports:

- VS Code Remote: Full VS Code editor experience in the container
- noVNC: Graphical desktop access for GUI applications

Usage:
    from devtunnel import InteractiveSessionManager, InteractiveSessionConfig
    
    manager = InteractiveSessionManager()
    
    # Check if ready
    status = manager.check_prerequisites()
    if not status["ready"]:
        print(status["instructions"])
        
    # Create session
    config = InteractiveSessionConfig(mode="vscode", timeout_minutes=30)
    session = manager.create_session(config, job_id="op-123")
    
    # Get connection info
    print(session.get_connection_instructions())
"""

from .models import (
    PortSpec,
    TunnelToken,
    TunnelResult,
    TunnelParameters,
    InteractiveSessionConfig,
)
from .cli_wrapper import DevTunnelCLI, DevTunnelError
from .vscode_layer import (
    VSCodeLayerBuilder, 
    generate_tunnel_wrapper_code,
    generate_shell_tunnel_wrapper,
    generate_shell_command_prefix,
)
from .interactive_session import InteractiveSession, InteractiveSessionManager

__all__ = [
    # Models
    "PortSpec",
    "TunnelToken", 
    "TunnelResult",
    "TunnelParameters",
    "InteractiveSessionConfig",
    # CLI
    "DevTunnelCLI",
    "DevTunnelError",
    # VS Code layer
    "VSCodeLayerBuilder",
    "generate_tunnel_wrapper_code",
    "generate_shell_tunnel_wrapper",
    "generate_shell_command_prefix",
    # Session management
    "InteractiveSession",
    "InteractiveSessionManager",
]

