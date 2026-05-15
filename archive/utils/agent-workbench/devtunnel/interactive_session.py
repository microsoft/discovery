"""High-level interactive session management.

Provides a unified interface for both MCP server and web UI to manage
interactive debugging sessions. With VS Code CLI approach, the actual
tunnel is created in the container, not on the server side.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Callable, List
from datetime import datetime, timezone

from .models import TunnelResult, InteractiveSessionConfig
from .vscode_layer import generate_tunnel_wrapper_code


@dataclass
class InteractiveSession:
    """Represents an active interactive debugging session."""
    session_id: str
    job_id: Optional[str]
    mode: str  # "vscode" or "novnc"
    tunnel: TunnelResult
    created_at: datetime
    timeout_minutes: int
    
    def get_access_url(self) -> Optional[str]:
        """Get the URL to access this session.
        
        For VS Code CLI tunnels, returns the tunnel URL with /workspace path
        which contains .vscode config and a symlink to /mnt/scripts.
        """
        if self.mode == "vscode":
            # Open /workspace - it's writable and has .vscode/ with debug config
            # Scripts are in /workspace/scripts/ (symlink to /mnt/scripts)
            return f"https://vscode.dev/tunnel/{self.tunnel.tunnel_id}/workspace"
        elif self.mode == "novnc":
            # noVNC uses port 6080
            return self.tunnel.get_port_url(6080)
        return None
    
    def get_connection_instructions(self) -> List[str]:
        """Get user-friendly connection instructions."""
        if self.mode == "vscode":
            return [
                "1. Wait for the job to start (check job logs)",
                "2. The container will display an authentication URL",
                "3. Visit the URL and enter the code shown to authorize",
                "4. Once authenticated, connect via VS Code:",
                "   - Open VS Code on your local machine",
                "   - Install the 'Remote - Tunnels' extension if not installed",
                "   - Press Ctrl+Shift+P (Cmd+Shift+P on Mac)",
                "   - Type 'Remote-Tunnels: Connect to Tunnel' and select it",
                f"   - Select tunnel: {self.tunnel.tunnel_id}",
                "",
                "Or open directly in browser:",
                f"   {self.get_access_url()}",
                "",
                "Features available:",
                "  - Full VS Code editor in the container",
                "  - Integrated terminal (bash/sh)",
                "  - File browser and editing",
                "  - Extensions support",
                "  - Python debugging with debugpy"
            ]
        elif self.mode == "novnc":
            url = self.get_access_url()
            return [
                f"1. Open this URL in your browser:",
                f"   {url}",
                "2. You'll see a graphical desktop environment",
                "3. Use the desktop to interact with GUI applications"
            ]
        return []
    
    def to_dict(self) -> Dict:
        """Convert session to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "job_id": self.job_id,
            "mode": self.mode,
            "tunnel_id": self.tunnel.tunnel_id,
            "access_url": self.get_access_url(),
            "ports": self.tunnel.ports,
            "created_at": self.created_at.isoformat(),
            "timeout_minutes": self.timeout_minutes,
            "instructions": self.get_connection_instructions()
        }


class InteractiveSessionManager:
    """Manages interactive debugging sessions.
    
    With VS Code CLI approach, this class just manages session IDs and metadata.
    The actual tunnel is created by VS Code CLI running inside the container.
    No devtunnel CLI required on the server side.
    """
    
    def __init__(self, logger: Optional[Callable[[str], None]] = None):
        self._log = logger or (lambda msg: None)
        self._active_sessions: Dict[str, InteractiveSession] = {}
    
    def check_prerequisites(self) -> Dict:
        """Check if interactive mode is ready to use.
        
        With VS Code CLI approach, no special prerequisites are needed on
        the server side. The VS Code CLI in the container handles everything.
        
        Returns dict with 'ready', 'status', and 'instructions' keys.
        """
        return {
            "ready": True,
            "status": {
                "approach": "vscode-cli",
                "description": "VS Code CLI handles tunnel creation in container"
            },
            "error": None,
            "instructions": (
                "Interactive mode uses VS Code CLI which is downloaded and run "
                "inside the container. No setup required on your local machine. "
                "When the job starts, follow the authentication instructions in "
                "the job logs to authorize the tunnel."
            )
        }
    
    def create_session(self, config: InteractiveSessionConfig,
                       job_id: Optional[str] = None) -> InteractiveSession:
        """Create a new interactive session.
        
        With VS Code CLI approach, we don't need to pre-create a tunnel on the
        server side. The VS Code CLI running in the container will create and
        manage its own tunnel. We just generate a unique session ID that will
        be used as the tunnel name.
        
        Args:
            config: Session configuration (mode, timeout, etc.)
            job_id: Optional job ID to associate with session
            
        Returns:
            InteractiveSession ready for use
        """
        # Generate a unique session ID that will be used as tunnel name
        session_id = f"discovery-{uuid.uuid4().hex[:8]}"
        
        # Create a minimal TunnelResult - the actual tunnel will be created
        # by VS Code CLI in the container
        tunnel = TunnelResult(
            tunnel_id=session_id,
            host_connections=0,
            client_connections=0,
            ports={},  # Will be populated when tunnel is created
            token=None  # Not needed for VS Code CLI approach
        )
        
        self._log(f"Created interactive session: {session_id} (mode: {config.mode})")
        self._log(f"Note: Tunnel will be created by VS Code CLI in container")
        
        # Create session object
        session = InteractiveSession(
            session_id=session_id,
            job_id=job_id,
            mode=config.mode,
            tunnel=tunnel,
            created_at=datetime.now(timezone.utc),
            timeout_minutes=config.timeout_minutes
        )
        
        self._active_sessions[session_id] = session
        
        return session
    
    def get_session(self, session_id: str) -> Optional[InteractiveSession]:
        """Get an active session by ID."""
        return self._active_sessions.get(session_id)
    
    def get_session_by_job(self, job_id: str) -> Optional[InteractiveSession]:
        """Get session associated with a job ID."""
        for session in self._active_sessions.values():
            if session.job_id == job_id:
                return session
        return None
    
    def close_session(self, session_id: str) -> bool:
        """Close and cleanup an interactive session.
        
        With VS Code CLI approach, the tunnel is managed by the container
        and cleaned up automatically when the job ends.
        """
        session = self._active_sessions.pop(session_id, None)
        if session:
            self._log(f"Session closed: {session_id}")
            return True
        return False
    
    def close_session_by_job(self, job_id: str) -> bool:
        """Close session associated with a job ID."""
        session = self.get_session_by_job(job_id)
        if session:
            return self.close_session(session.session_id)
        return False
    
    def generate_script_wrapper(self, session: InteractiveSession) -> str:
        """Generate Python code to inject into script for tunnel setup."""
        return generate_tunnel_wrapper_code(
            session.tunnel, 
            session.timeout_minutes
        )
    
    def list_active_sessions(self) -> List[InteractiveSession]:
        """List all active sessions."""
        return list(self._active_sessions.values())
    
    def cleanup_all_sessions(self) -> int:
        """Close all active sessions. Returns count of closed sessions."""
        session_ids = list(self._active_sessions.keys())
        count = 0
        for session_id in session_ids:
            if self.close_session(session_id):
                count += 1
        return count
