"""
Session Manager for Agent Workbench

This module handles multi-session management with isolated directories and state persistence.
Each session has its own input/output/workdir directories and conversation history.
"""

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, List, Optional, Any


@dataclass
class WorkbenchSession:
    """Represents a workbench session with isolated state."""
    session_id: str
    name: str
    created_at: float
    last_activity: float
    agent_name: Optional[str] = None
    agent_type: Optional[str] = None  # 'tool', 'entry', 'kb'
    message_count: int = 0
    ui_state: Dict[str, Any] = field(default_factory=dict)  # Legacy: kept for backward compatibility
    ui_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # New: per-agent UI state
    agents_used: List[str] = field(default_factory=list)  # Track all agents used in this session

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'session_id': self.session_id,
            'name': self.name,
            'created_at': self.created_at,
            'last_activity': self.last_activity,
            'agent_name': self.agent_name,
            'agent_type': self.agent_type,
            'message_count': self.message_count,
            'ui_state': self.ui_state,  # Legacy
            'ui_states': self.ui_states,  # Per-agent UI states
            'agents_used': self.agents_used  # List of agents used in session
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkbenchSession':
        """Create from dictionary."""
        # Migrate old ui_state to ui_states if needed
        ui_states = data.get('ui_states', {})
        legacy_ui_state = data.get('ui_state', {})

        # If we have legacy ui_state but no ui_states, and we have an agent_name,
        # migrate the legacy state to the current agent
        if legacy_ui_state and not ui_states and data.get('agent_name'):
            ui_states = {data['agent_name']: legacy_ui_state}

        return cls(
            session_id=data['session_id'],
            name=data['name'],
            created_at=data['created_at'],
            last_activity=data['last_activity'],
            agent_name=data.get('agent_name'),
            agent_type=data.get('agent_type'),
            message_count=data.get('message_count', 0),
            ui_state=legacy_ui_state,
            ui_states=ui_states,
            agents_used=data.get('agents_used', [])
        )


class SessionManager:
    """
    Manages workbench sessions with persistence.
    Coordinates isolated directories per session and tracks session metadata.
    """

    def __init__(self, base_dir: str):
        """
        Initialize the session manager.

        Args:
            base_dir: Base directory for the agent workbench
        """
        self.base_dir = base_dir
        self.workbench_dir = os.path.join(base_dir, '.workbench')
        self.sessions_file = os.path.join(self.workbench_dir, 'sessions.json')
        self.sessions_dir = os.path.join(self.workbench_dir, 'sessions')

        self.sessions: Dict[str, WorkbenchSession] = {}
        self.current_session_id: Optional[str] = None
        self._lock = threading.Lock()

        # Ensure workbench directory exists
        os.makedirs(self.workbench_dir, exist_ok=True)

        # Migrate sessions from old location if needed (before creating new sessions_dir)
        self._migrate_sessions_location()

        # Ensure sessions directory exists
        os.makedirs(self.sessions_dir, exist_ok=True)

        # Load existing sessions or migrate
        self._load_sessions()

    def _generate_session_name(self, agent_name: Optional[str] = None) -> str:
        """Generate an auto-generated session name."""
        timestamp = datetime.now().strftime("%b %d %H:%M")
        if agent_name:
            return f"{agent_name} {timestamp}"
        return f"Session {timestamp}"

    def create_session(self,
                       name: Optional[str] = None,
                       agent_name: Optional[str] = None,
                       agent_type: Optional[str] = None) -> WorkbenchSession:
        """
        Create a new session with isolated directories.

        Args:
            name: Session name (auto-generated if not provided)
            agent_name: Currently selected agent
            agent_type: Type of agent ('tool', 'entry', 'kb')

        Returns:
            The created WorkbenchSession
        """
        with self._lock:
            session_id = str(uuid.uuid4())
            now = time.time()

            if not name:
                name = self._generate_session_name(agent_name)

            session = WorkbenchSession(
                session_id=session_id,
                name=name,
                created_at=now,
                last_activity=now,
                agent_name=agent_name,
                agent_type=agent_type,
                message_count=0,
                ui_state={}
            )

            # Create session directories
            self._create_session_directories(session_id)

            # Store and persist
            self.sessions[session_id] = session
            self.current_session_id = session_id
            self._persist()

            return session

    def _create_session_directories(self, session_id: str) -> None:
        """
        Create the session base directory.

        Note: Agent-specific input/output/workdir directories are created on-demand
        by get_session_dirs() when an agent is used.
        """
        session_base = os.path.join(self.sessions_dir, session_id)
        os.makedirs(session_base, exist_ok=True)

    def get_session(self, session_id: str) -> Optional[WorkbenchSession]:
        """Get session by ID."""
        with self._lock:
            return self.sessions.get(session_id)

    def get_current_session(self) -> Optional[WorkbenchSession]:
        """Get the current active session."""
        with self._lock:
            if self.current_session_id:
                return self.sessions.get(self.current_session_id)
            return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        List all sessions with metadata for UI display.

        Returns:
            List of session dictionaries sorted by last_activity (newest first)
        """
        with self._lock:
            sessions_list = []
            for session in self.sessions.values():
                session_dict = session.to_dict()
                session_dict['is_current'] = (session.session_id == self.current_session_id)

                # Populate agents_used from ui_states keys if empty (migration for old sessions)
                if not session_dict.get('agents_used') and session_dict.get('ui_states'):
                    session_dict['agents_used'] = list(session_dict['ui_states'].keys())
                # Also add current agent_name if not in the list
                if session_dict.get('agent_name'):
                    agents_used = session_dict.get('agents_used', [])
                    if session_dict['agent_name'] not in agents_used:
                        agents_used.append(session_dict['agent_name'])
                        session_dict['agents_used'] = agents_used

                sessions_list.append(session_dict)

            # Sort by last_activity descending
            sessions_list.sort(key=lambda x: x['last_activity'], reverse=True)
            return sessions_list

    def switch_session(self, session_id: str) -> Optional[WorkbenchSession]:
        """
        Switch to a different session.

        Args:
            session_id: ID of the session to switch to

        Returns:
            The switched-to session, or None if not found
        """
        with self._lock:
            if session_id not in self.sessions:
                return None

            self.current_session_id = session_id
            self.sessions[session_id].last_activity = time.time()
            self._persist()

            return self.sessions[session_id]

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and its directories.

        Args:
            session_id: ID of the session to delete

        Returns:
            True if deleted, False if not found or is current session
        """
        with self._lock:
            if session_id not in self.sessions:
                return False

            # Cannot delete current session
            if session_id == self.current_session_id:
                return False

            # Remove session directories
            session_base = os.path.join(self.sessions_dir, session_id)
            if os.path.exists(session_base):
                shutil.rmtree(session_base, ignore_errors=True)

            # Remove from storage
            del self.sessions[session_id]
            self._persist()

            return True

    def update_session(self,
                       session_id: str,
                       name: Optional[str] = None,
                       agent_name: Optional[str] = None,
                       agent_type: Optional[str] = None,
                       message_count: Optional[int] = None,
                       ui_state: Optional[Dict[str, Any]] = None) -> Optional[WorkbenchSession]:
        """
        Update session properties.

        Args:
            session_id: ID of the session to update
            name: New name (optional)
            agent_name: New agent name (optional)
            agent_type: New agent type (optional)
            message_count: New message count (optional)
            ui_state: New UI state (optional)

        Returns:
            Updated session or None if not found
        """
        with self._lock:
            if session_id not in self.sessions:
                return None

            session = self.sessions[session_id]

            if name is not None:
                session.name = name
            if agent_name is not None:
                session.agent_name = agent_name
                # Track agents used in this session
                if agent_name and agent_name not in session.agents_used:
                    session.agents_used.append(agent_name)
            if agent_type is not None:
                session.agent_type = agent_type
            if message_count is not None:
                session.message_count = message_count
            if ui_state is not None:
                session.ui_state = ui_state

            session.last_activity = time.time()
            self._persist()

            return session

    def update_session_activity(self, session_id: str) -> None:
        """Update last_activity timestamp for a session."""
        with self._lock:
            if session_id in self.sessions:
                self.sessions[session_id].last_activity = time.time()
                self._persist()

    def get_session_dirs(self, session_id: Optional[str] = None, agent_name: Optional[str] = None, create: bool = False) -> Dict[str, str]:
        """
        Get input/output/workdir paths for a session and optionally for a specific agent.

        Args:
            session_id: Session ID (uses current session if not provided)
            agent_name: Optional agent name. If provided, returns agent-specific directories.
            create: If True, create the directories. Default is False (just return paths).

        Returns:
            Dictionary with 'input', 'output', 'workdir' paths
        """
        with self._lock:
            sid = session_id or self.current_session_id
            if not sid:
                raise ValueError("No session ID provided and no current session is active. A session must be created first.")

            session_base = os.path.join(self.sessions_dir, sid)

            # If agent_name is provided, use agent-specific subdirectories
            if agent_name:
                safe_agent_name = agent_name.replace('/', '_').replace('\\', '_')
                session_base = os.path.join(session_base, safe_agent_name)

            dirs = {
                'input': os.path.join(session_base, 'input'),
                'output': os.path.join(session_base, 'output'),
                'workdir': os.path.join(session_base, 'workdir'),
                'state': os.path.join(session_base, '.state')
            }

            # Only create directories if explicitly requested
            if create:
                for path in dirs.values():
                    os.makedirs(path, exist_ok=True)

            return dirs

    def save_ui_state(self, session_id: str, ui_state: Dict[str, Any], agent_name: Optional[str] = None) -> None:
        """
        Save UI state for session restoration.

        Args:
            session_id: The session ID
            ui_state: The UI state to save
            agent_name: Optional agent name. If provided, saves agent-specific UI state.
                       If not provided, saves to legacy ui_state field.
        """
        with self._lock:
            if session_id in self.sessions:
                if agent_name:
                    # Save agent-specific UI state
                    self.sessions[session_id].ui_states[agent_name] = ui_state
                else:
                    # Legacy: save to ui_state field
                    self.sessions[session_id].ui_state = ui_state
                self._persist()

    def get_ui_state(self, session_id: str, agent_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get UI state for a session and optionally a specific agent.

        Args:
            session_id: The session ID
            agent_name: Optional agent name. If provided, returns agent-specific UI state.
                       If not provided, returns legacy ui_state field.

        Returns:
            The UI state dict, or None if not found
        """
        with self._lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                if agent_name:
                    # Return agent-specific UI state
                    return session.ui_states.get(agent_name)
                else:
                    # Return legacy UI state
                    return session.ui_state
            return None

    def increment_message_count(self, session_id: Optional[str] = None) -> None:
        """Increment message count for a session."""
        with self._lock:
            sid = session_id or self.current_session_id
            if sid and sid in self.sessions:
                self.sessions[sid].message_count += 1
                self.sessions[sid].last_activity = time.time()
                self._persist()

    def _persist(self) -> None:
        """Save sessions to disk.

        Note: current_session_id is NOT persisted - it's kept in browser tab memory only.
        This allows multiple browser tabs to have different active sessions.
        """
        data = {
            # Don't persist current_session_id - each browser tab manages its own
            'sessions': {
                sid: session.to_dict()
                for sid, session in self.sessions.items()
            }
        }

        try:
            with open(self.sessions_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to persist sessions: {e}")

    def _load_sessions(self) -> None:
        """Load sessions from disk or migrate from legacy structure.

        Note: current_session_id is NOT loaded from disk - each browser tab manages its own.
        This allows multiple browser tabs to have different active sessions.
        """
        if os.path.exists(self.sessions_file):
            try:
                with open(self.sessions_file, 'r') as f:
                    data = json.load(f)

                # Don't load current_session_id from file - it's per browser tab
                # (ignore any legacy current_session_id in the file)
                for sid, session_data in data.get('sessions', {}).items():
                    self.sessions[sid] = WorkbenchSession.from_dict(session_data)

                # current_session_id stays None until a browser tab sets it via API

            except Exception as e:
                print(f"Warning: Failed to load sessions, will migrate: {e}")
                self._migrate_legacy()
        else:
            # No sessions file - check for legacy directories to migrate
            self._migrate_legacy()

    def _migrate_sessions_location(self) -> None:
        """Migrate sessions from old location (base_dir/sessions) to new location (.workbench/sessions)."""
        old_sessions_dir = os.path.join(self.base_dir, 'sessions')

        # Skip if old location doesn't exist or new location already has content
        if not os.path.exists(old_sessions_dir):
            return

        if os.path.exists(self.sessions_dir) and os.listdir(self.sessions_dir):
            # New location already has content, don't overwrite
            return

        try:
            print(f"📦 Migrating sessions from {old_sessions_dir} to {self.sessions_dir}")
            # Move the entire sessions directory to new location
            shutil.move(old_sessions_dir, self.sessions_dir)
            print(f"✅ Sessions migrated successfully")
        except Exception as e:
            print(f"⚠️ Failed to migrate sessions: {e}")
            # If move failed, try to copy instead
            try:
                shutil.copytree(old_sessions_dir, self.sessions_dir)
                print(f"✅ Sessions copied to new location")
            except Exception as copy_err:
                print(f"❌ Failed to copy sessions: {copy_err}")

    def _migrate_legacy(self) -> None:
        """Migrate from legacy single-directory structure to sessions."""
        docker_shared = os.path.join(self.base_dir, 'docker-shared')
        legacy_input = os.path.join(docker_shared, 'input')
        legacy_output = os.path.join(docker_shared, 'output')
        legacy_workdir = os.path.join(docker_shared, 'workdir')

        # Check if legacy directories exist and have content
        has_legacy_content = any(
            os.path.exists(d) and os.listdir(d)
            for d in [legacy_input, legacy_output, legacy_workdir]
        )

        if has_legacy_content:
            # Create a default session from legacy content
            session_id = str(uuid.uuid4())
            now = time.time()

            session = WorkbenchSession(
                session_id=session_id,
                name="Migrated Session",
                created_at=now,
                last_activity=now,
                message_count=0
            )

            # Create session directory
            session_base = os.path.join(self.sessions_dir, session_id)
            os.makedirs(session_base, exist_ok=True)

            # Move legacy content to session
            for subdir in ['input', 'output', 'workdir']:
                legacy_path = os.path.join(docker_shared, subdir)
                session_path = os.path.join(session_base, subdir)

                if os.path.exists(legacy_path):
                    try:
                        shutil.move(legacy_path, session_path)
                    except Exception as e:
                        print(f"Warning: Failed to migrate {subdir}: {e}")
                        os.makedirs(session_path, exist_ok=True)
                else:
                    os.makedirs(session_path, exist_ok=True)

            self.sessions[session_id] = session
            self.current_session_id = session_id
            self._persist()
        else:
            # No legacy content - create fresh default session
            session = self.create_session(name="Session 1")
            # create_session already sets current_session_id and persists


# Global session manager instance (initialized in web_server.py)
session_manager: Optional[SessionManager] = None


def init_session_manager(base_dir: str) -> SessionManager:
    """Initialize the global session manager."""
    global session_manager
    session_manager = SessionManager(base_dir)
    return session_manager


def get_session_manager() -> Optional[SessionManager]:
    """Get the global session manager instance."""
    return session_manager
