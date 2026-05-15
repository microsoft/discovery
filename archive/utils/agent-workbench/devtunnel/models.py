"""Data models for Dev Tunnel parameters and results.

Uses dataclasses instead of Pydantic to minimize dependencies.
Adapted from utils/supercomputer-cli/discovery/src/discovery/poll/models/devtunnel.py
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$")


@dataclass
class PortSpec:
    """Specification for a single port to expose through the tunnel."""
    port: int
    protocols: Tuple[str, ...] = ("https",)
    
    def __post_init__(self):
        if not 1 <= self.port <= 65535:
            raise ValueError(f"Port must be 1-65535, got {self.port}")
        if not self.protocols:
            raise ValueError("protocols must contain at least one value")
    
    def protocols_string(self) -> str:
        """Return comma-separated protocol list for CLI calls."""
        return ",".join(self.protocols)


@dataclass
class TunnelToken:
    """Access token for a dev tunnel."""
    tunnel_id: str
    scope: str
    lifetime: str
    expiration: str
    value: str  # JWT token
    
    def redacted(self) -> str:
        """Return redacted token for safe logging."""
        if len(self.value) <= 10:
            return self.value
        return f"{self.value[:6]}...{self.value[-4:]}"


@dataclass
class TunnelResult:
    """Result of creating a dev tunnel."""
    tunnel_id: str
    host_connections: int = 0
    client_connections: int = 0
    ports: Dict[int, str] = field(default_factory=dict)  # port -> URL
    token: Optional[TunnelToken] = None
    
    def get_port_url(self, port: int) -> Optional[str]:
        """Get the public URL for a specific port."""
        return self.ports.get(port)


@dataclass 
class TunnelParameters:
    """Input parameters for creating a dev tunnel."""
    name: str
    ports: List[PortSpec]
    ensure_login: bool = True
    
    def __post_init__(self):
        name = self.name.strip().lower()
        if not _NAME_PATTERN.match(name):
            raise ValueError(
                f"Invalid tunnel name: {name}. "
                "Must be 2-60 chars, lowercase alphanumeric with internal hyphens."
            )
        self.name = name
        if not self.ports:
            raise ValueError("ports must contain at least one port specification")


@dataclass
class InteractiveSessionConfig:
    """Configuration for an interactive debugging session."""
    mode: str  # "vscode" or "novnc"
    timeout_minutes: int = 30
    auto_open_browser: bool = False
    
    def __post_init__(self):
        if self.mode not in ("vscode", "novnc"):
            raise ValueError(f"mode must be 'vscode' or 'novnc', got '{self.mode}'")
        if self.timeout_minutes < 1:
            raise ValueError("timeout_minutes must be at least 1")
