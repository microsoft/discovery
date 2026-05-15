"""
Conversation Manager for Agent Test Application

This module handles conversation history management with token-aware context handling.
Supports multiple strategies for managing long conversations within token limits.
"""

import json
import time
import uuid
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from discovery_config_manager import DiscoveryConfigManager
from enum import Enum
try:
    import tiktoken
    _TIKTOKEN_AVAILABLE = True
except Exception:
    # tiktoken may require Rust on some platforms if a prebuilt wheel isn't available.
    # Provide a lightweight, pure-Python fallback encoder for approximate token counting.
    tiktoken = None
    _TIKTOKEN_AVAILABLE = False
    import re

    class _FallbackEncoder:
        """Very small tokenizer used only for token counting when tiktoken is unavailable.

        This is an approximation: it splits on word boundaries and punctuation. It is
        sufficient for heuristic token-count based pruning and summaries but not exact
        alignment with OpenAI/Anthropic tokenization.
        """
        def __init__(self):
            # split into words and punctuation
            self._re = re.compile(r"\w+|[^\s\w]", re.UNICODE)

        def encode(self, text: str):
            if not text:
                return []
            return self._re.findall(text)
import requests
import os


class ContextStrategy(Enum):
    """Strategies for managing context when approaching token limits"""
    SLIDING_WINDOW = "sliding_window"  # Keep most recent messages
    SUMMARIZATION = "summarization"    # Summarize older messages
    HYBRID = "hybrid"                  # Combine sliding window + summarization


@dataclass
class ConversationMessage:
    """Represents a single message in the conversation"""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    timestamp: float
    message_id: str
    token_count: int = 0
    tool_calls: Any = None  # For assistant messages with function calls
    tool_call_id: str = None  # For tool response messages
    data_handling_context: str = None  # For debugging: extracted data handling context from system messages
    
    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI API format"""
        msg = {"role": self.role}
        
        # Handle tool response messages
        if self.role == "tool":
            msg["tool_call_id"] = self.tool_call_id
            msg["content"] = self.content
        # Handle assistant messages with tool calls
        elif self.role == "assistant" and self.tool_calls:
            msg["tool_calls"] = self.tool_calls
            # content can be None for tool_calls
            if self.content:
                msg["content"] = self.content
        # Standard messages
        else:
            msg["content"] = self.content
        
        return msg


@dataclass
class ConversationSession:
    """Represents a complete conversation session"""
    session_id: str
    messages: List[ConversationMessage]
    created_at: float
    last_activity: float
    total_tokens: int = 0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ConversationManager:
    """
    Manages conversation sessions with token-aware context handling.
    
    Features:
    - Multiple conversation sessions
    - Token counting and limit enforcement
    - Context pruning strategies
    - Conversation summarization
    - Persistent storage
    """
    
    def __init__(self, 
                 max_tokens: int = 10000,
                 target_tokens: int = 8000,
                 strategy: ContextStrategy = ContextStrategy.HYBRID,
                 model_name: str = "gpt-4"):
        """
        Initialize the conversation manager.
        
        Args:
            max_tokens: Maximum tokens allowed in conversation context
            target_tokens: Target tokens to maintain after pruning
            strategy: Strategy for context management
            model_name: Model name for token counting
        """
        self.max_tokens = max_tokens
        self.target_tokens = target_tokens
        self.strategy = strategy
        self.model_name = model_name
        
        # Session storage
        self.sessions: Dict[str, ConversationSession] = {}
        self.current_session_id: Optional[str] = None
        
        # Token encoder for counting. Prefer tiktoken if available, otherwise use
        # the lightweight fallback encoder defined above. The fallback provides an
        # approximate token count so the conversation manager can still prune and
        # summarize without requiring the Rust toolchain during install.
        if _TIKTOKEN_AVAILABLE:
            try:
                self.encoder = tiktoken.encoding_for_model(model_name)
            except Exception:
                try:
                    self.encoder = tiktoken.encoding_for_model("gpt-4")
                except Exception:
                    # If tiktoken is present but model lookup fails, fall back
                    # to the pure-Python encoder.
                    self.encoder = _FallbackEncoder()
        else:
            self.encoder = _FallbackEncoder()
        # Set safe defaults for runtime conversation properties
        self.max_output_tokens = 16384
        self.max_retries = 3
        self.temperature = 0.1
        self.endpoint = None
        self.deployment = None
        self.subscription_key = None
        self.api_version = None
        self.api_url = None

        # Load runtime configuration from discovery config manager and override defaults
        try:
            cfg_mgr = DiscoveryConfigManager()
            azure_openai = cfg_mgr.get_azure_openai_config()
            conv_cfg = cfg_mgr.get_conversation_config()

            # Override manager limits if provided in discovery config
            try:
                self.max_output_tokens = int(conv_cfg.get('max_output_tokens', self.max_output_tokens))
            except Exception:
                # ignore parse errors and keep default
                pass

            try:
                self.max_tokens = int(conv_cfg.get('max_tokens', self.max_tokens))
            except Exception:
                pass

            try:
                self.target_tokens = int(conv_cfg.get('target_tokens', self.target_tokens))
            except Exception:
                pass

            strategy_name = conv_cfg.get('strategy', None)
            if strategy_name:
                try:
                    self.strategy = ContextStrategy(strategy_name)
                except Exception:
                    pass

            try:
                self.max_retries = int(conv_cfg.get('max_retries', self.max_retries))
            except Exception:
                pass

            try:
                self.temperature = float(conv_cfg.get('temperature', self.temperature))
            except Exception:
                pass

            # Azure OpenAI runtime keys (used for summarization API calls)
            if azure_openai:
                self.endpoint = azure_openai.get('endpoint_url')
                self.deployment = azure_openai.get('deployment_name')
                self.subscription_key = azure_openai.get('api_key')
                # read api_version if provided in discovery config
                try:
                    self.api_version = azure_openai.get('api_version') or self.api_version
                except Exception:
                    pass
            # Recompute the full API URL only when we have the minimal pieces
            self._recompute_api_url()
        except Exception:
            # If DiscoveryConfigManager cannot be read, keep defaults
            pass

    def _recompute_api_url(self):
        """Recompute the full chat/completions API URL from endpoint, deployment and api_version.
        """
        try:
            if not (self.endpoint and self.deployment and self.subscription_key and self.api_version):
                self.api_url = None
                return
            self.api_url = f"{self.endpoint.rstrip('/')}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"
        except Exception:
            self.api_url = None
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the appropriate encoder"""
        try:
            return len(self.encoder.encode(text))
        except Exception:
            # Fallback: rough estimation (1 token ≈ 4 characters)
            return len(text) // 4
    
    def create_session(self, system_prompt: str = None) -> str:
        """Create a new conversation session"""
        session_id = str(uuid.uuid4())
        current_time = time.time()
        
        messages = []
        if system_prompt:
            system_msg = ConversationMessage(
                role="system",
                content=system_prompt,
                timestamp=current_time,
                message_id=str(uuid.uuid4()),
                token_count=self.count_tokens(system_prompt)
            )
            messages.append(system_msg)
        
        session = ConversationSession(
            session_id=session_id,
            messages=messages,
            created_at=current_time,
            last_activity=current_time,
            total_tokens=sum(msg.token_count for msg in messages)
        )
        
        self.sessions[session_id] = session
        self.current_session_id = session_id
        
        return session_id
    
    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """Get a conversation session by ID"""
        return self.sessions.get(session_id)
    
    def set_current_session(self, session_id: str) -> bool:
        """Set the current active session"""
        if session_id in self.sessions:
            self.current_session_id = session_id
            return True
        return False
    
    def add_message(self, role: str, content: str, session_id: str = None) -> str:
        """
        Add a message to the conversation.
        
        Args:
            role: Message role (user, assistant, system)
            content: Message content
            session_id: Session ID (uses current session if None)
            
        Returns:
            Message ID
        """
        if session_id is None:
            session_id = self.current_session_id
        
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
          # Create message
        message_id = str(uuid.uuid4())
        token_count = self.count_tokens(content)
        
        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=time.time(),
            message_id=message_id,
            token_count=token_count
        )
        
        # Check if adding this message would exceed limits and pre-manage context
        projected_total = session.total_tokens + token_count
        if projected_total > self.max_tokens:
            # Pre-prune to make room for the new message
            temp_session = ConversationSession(
                session_id=session.session_id,
                messages=session.messages.copy(),
                created_at=session.created_at,
                last_activity=session.last_activity,
                total_tokens=session.total_tokens
            )
            temp_session.total_tokens = projected_total
            self._manage_context(temp_session)
            # Apply the pruning to the actual session
            session.messages = temp_session.messages
            session.total_tokens = temp_session.total_tokens - token_count  # Subtract the new message tokens
        
        # Add to session
        session.messages.append(message)
        session.total_tokens += token_count
        session.last_activity = time.time()
        
        # Final context management check (should rarely be needed now)
        self._manage_context(session)
        
        return message_id
    
    def add_message_with_tool_calls(self, role: str, content: str, tool_calls: Any, session_id: str = None) -> str:
        """
        Add an assistant message with tool_calls to the conversation.
        
        Args:
            role: Message role (should be "assistant")
            content: Message content (can be None for tool_calls)
            tool_calls: List of tool_call objects from Azure OpenAI
            session_id: Session ID (uses current session if None)
            
        Returns:
            Message ID
        """
        if session_id is None:
            session_id = self.current_session_id
        
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        message_id = str(uuid.uuid4())
        
        # Token count for tool_calls (approximate)
        token_count = self.count_tokens(json.dumps(tool_calls) if tool_calls else "")
        if content:
            token_count += self.count_tokens(content)
        
        message = ConversationMessage(
            role=role,
            content=content or "",
            timestamp=time.time(),
            message_id=message_id,
            token_count=token_count,
            tool_calls=tool_calls
        )
        
        # Add to session
        session.messages.append(message)
        session.total_tokens += token_count
        session.last_activity = time.time()
        
        self._manage_context(session)
        
        return message_id
    
    def add_tool_response(self, tool_call_id: str, content: str, session_id: str = None) -> str:
        """
        Add a tool response message to the conversation.
        
        Args:
            tool_call_id: ID of the tool call this is responding to
            content: Tool execution result (as JSON string)
            session_id: Session ID (uses current session if None)
            
        Returns:
            Message ID
        """
        if session_id is None:
            session_id = self.current_session_id
        
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        message_id = str(uuid.uuid4())
        token_count = self.count_tokens(content)
        
        message = ConversationMessage(
            role="tool",
            content=content,
            timestamp=time.time(),
            message_id=message_id,
            token_count=token_count,
            tool_call_id=tool_call_id
        )
        
        # Add to session
        session.messages.append(message)
        session.total_tokens += token_count
        session.last_activity = time.time()
        
        self._manage_context(session)
        
        return message_id
    
    def get_conversation_for_api(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get conversation messages formatted for OpenAI API.
        
        Args:
            session_id: Session ID (uses current session if None)
            
        Returns:
            List of messages in OpenAI format
        """
        if session_id is None:
            session_id = self.current_session_id
        
        if session_id not in self.sessions:
            return []
        
        session = self.sessions[session_id]
        return [msg.to_openai_format() for msg in session.messages]
    
    def _manage_context(self, session: ConversationSession):
        """Manage conversation context based on token limits"""
        if session.total_tokens <= self.max_tokens:
            return
        
        if self.strategy == ContextStrategy.SLIDING_WINDOW:
            self._apply_sliding_window(session)
        elif self.strategy == ContextStrategy.SUMMARIZATION:
            self._apply_summarization(session)
        elif self.strategy == ContextStrategy.HYBRID:
            self._apply_hybrid_strategy(session)
    
    def _apply_sliding_window(self, session: ConversationSession):
        """Apply sliding window strategy - keep recent messages.

        Tool call groups (assistant message with tool_calls + all following tool
        response messages) are kept or dropped atomically to avoid orphan tool messages.
        """
        # Always keep system message if it exists
        system_messages = [msg for msg in session.messages if msg.role == "system"]
        other_messages = [msg for msg in session.messages if msg.role != "system"]

        # Calculate tokens for system messages
        system_tokens = sum(msg.token_count for msg in system_messages)
        available_tokens = self.target_tokens - system_tokens

        # Group messages into logical units that must be kept together.
        # A tool call group = assistant message with tool_calls + all following tool responses.
        groups = []  # Each group is a list of messages that must stay together
        i = 0
        while i < len(other_messages):
            msg = other_messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                # Start of a tool call group - collect the assistant message and all tool responses
                group = [msg]
                i += 1
                while i < len(other_messages) and other_messages[i].role == "tool":
                    group.append(other_messages[i])
                    i += 1
                groups.append(group)
            else:
                # Regular message (user, assistant without tool_calls)
                groups.append([msg])
                i += 1

        # Keep as many recent groups as possible (working backwards)
        kept_messages = []
        current_tokens = 0

        for group in reversed(groups):
            group_tokens = sum(m.token_count for m in group)
            if current_tokens + group_tokens <= available_tokens:
                # Insert the group at the front (we're iterating in reverse)
                kept_messages = group + kept_messages
                current_tokens += group_tokens
            else:
                # Can't fit this group, stop here
                break

        # Update session
        session.messages = system_messages + kept_messages
        session.total_tokens = system_tokens + current_tokens
    
    def _apply_summarization(self, session: ConversationSession):
        """Apply summarization strategy - summarize older messages.

        Respects tool call group boundaries when splitting messages.
        """
        if not self.api_url:
            # Fallback to sliding window if no API available
            self._apply_sliding_window(session)
            return

        # Keep system messages and recent messages
        system_messages = [msg for msg in session.messages if msg.role == "system"]
        other_messages = [msg for msg in session.messages if msg.role != "system"]

        if len(other_messages) <= 4:  # Keep if conversation is short
            return

        # Group messages into logical units (same as sliding window)
        groups = []
        i = 0
        while i < len(other_messages):
            msg = other_messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                group = [msg]
                i += 1
                while i < len(other_messages) and other_messages[i].role == "tool":
                    group.append(other_messages[i])
                    i += 1
                groups.append(group)
            else:
                groups.append([msg])
                i += 1

        if len(groups) <= 2:  # Keep if too few groups to summarize
            return

        # Keep last 2 groups and summarize the rest (ensures complete tool call groups)
        recent_groups = groups[-2:]
        old_groups = groups[:-2]

        recent_messages = [msg for group in recent_groups for msg in group]
        old_messages = [msg for group in old_groups for msg in group]
        
        # Create summary of old messages
        summary = self._summarize_messages(old_messages)
        
        if summary:
            summary_msg = ConversationMessage(
                role="system",
                content=f"Previous conversation summary: {summary}",
                timestamp=time.time(),
                message_id=str(uuid.uuid4()),
                token_count=self.count_tokens(summary)
            )
            
            # Update session
            session.messages = system_messages + [summary_msg] + recent_messages
            session.total_tokens = sum(msg.token_count for msg in session.messages)
    
    def _apply_hybrid_strategy(self, session: ConversationSession):
        """Apply hybrid strategy - summarize old, keep recent"""
        # If we're only slightly over, use sliding window
        if session.total_tokens <= self.max_tokens * 1.2:
            self._apply_sliding_window(session)
        else:
            self._apply_summarization(session)
    
    def _summarize_messages(self, messages: List[ConversationMessage]) -> Optional[str]:
        """Summarize a list of messages using Azure OpenAI"""
        if not self.api_url or not messages:
            return None
        
        # Create conversation text for summarization
        conversation_text = ""
        for msg in messages:
            conversation_text += f"{msg.role.upper()}: {msg.content}\n\n"
        
        # Prepare summarization request
        summary_messages = [
            {
                "role": "system",
                "content": "Summarize the following conversation concisely, preserving key context and decisions. Focus on important information that would be needed to continue the conversation effectively."
            },
            {
                "role": "user",
                "content": f"Please summarize this conversation:\n\n{conversation_text}"
            }
        ]
        
        try:
            headers = {
                "Content-Type": "application/json",
                "api-key": self.subscription_key
            }
            
            payload = {
                "messages": summary_messages,
                "max_tokens": 500,  # Limit summary length
                "temperature": 0.1,  # Lower temperature for consistent summaries
                "stream": False
            }
            
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            response_data = response.json()
            if 'choices' in response_data and response_data['choices']:
                choice = response_data['choices'][0]
                if 'message' in choice and 'content' in choice['message']:
                    return choice['message']['content'].strip()
            
        except Exception as e:
            print(f"Summarization failed: {e}")
        
        return None
    
    def reset_session(self, session_id: Optional[str] = None, system_prompt: Optional[str] = None):
        """Reset a conversation session"""
        if session_id is None:
            session_id = self.current_session_id
        
        if session_id in self.sessions:
            del self.sessions[session_id]
        
        # Create new session with same ID
        self.current_session_id = session_id
        current_time = time.time()
        
        messages = []
        if system_prompt:
            system_msg = ConversationMessage(
                role="system",
                content=system_prompt,
                timestamp=current_time,
                message_id=str(uuid.uuid4()),
                token_count=self.count_tokens(system_prompt)
            )
            messages.append(system_msg)
        
        session = ConversationSession(
            session_id=session_id,
            messages=messages,
            created_at=current_time,
            last_activity=current_time,
            total_tokens=sum(msg.token_count for msg in messages)
        )
        
        self.sessions[session_id] = session
    
    def get_session_info(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Get information about a session"""
        if session_id is None:
            session_id = self.current_session_id
        
        if session_id not in self.sessions:
            return {}
        
        session = self.sessions[session_id]
        return {
            "session_id": session.session_id,
            "message_count": len(session.messages),
            "total_tokens": session.total_tokens,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "max_tokens": self.max_tokens,
            "target_tokens": self.target_tokens,
            "strategy": self.strategy.value
        }
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all conversation sessions"""
        return [self.get_session_info(session_id) for session_id in self.sessions.keys()]
    
    def cleanup_old_sessions(self, max_age_hours: int = 24):
        """Clean up sessions older than specified age"""
        current_time = time.time()
        cutoff_time = current_time - (max_age_hours * 3600)
        
        sessions_to_remove = []
        for session_id, session in self.sessions.items():
            if session.last_activity < cutoff_time:
                sessions_to_remove.append(session_id)
        
        for session_id in sessions_to_remove:
            if session_id != self.current_session_id:  # Don't remove current session
                del self.sessions[session_id]

        return len(sessions_to_remove)

    def save_session_to_file(self, session_id: str, file_path: str) -> bool:
        """
        Save a conversation session to a JSON file for persistence.

        Args:
            session_id: The session ID to save
            file_path: Path to save the conversation JSON

        Returns:
            True if saved successfully, False otherwise
        """
        if session_id not in self.sessions:
            return False

        session = self.sessions[session_id]

        try:
            # Convert session to serializable format
            session_data = {
                'session_id': session.session_id,
                'created_at': session.created_at,
                'last_activity': session.last_activity,
                'total_tokens': session.total_tokens,
                'metadata': session.metadata,
                'messages': []
            }

            for msg in session.messages:
                msg_data = {
                    'role': msg.role,
                    'content': msg.content,
                    'timestamp': msg.timestamp,
                    'message_id': msg.message_id,
                    'token_count': msg.token_count,
                    'tool_calls': msg.tool_calls,
                    'tool_call_id': msg.tool_call_id
                }

                # For system messages, extract and store data handling context separately for debugging
                if msg.role == "system":
                    data_context = None
                    # Check if data handling context is already stored on the message
                    if msg.data_handling_context:
                        data_context = msg.data_handling_context
                    else:
                        # Try to extract it from the content
                        content = msg.content or ""
                        # Look for "Data handling context:" marker
                        marker = "Data handling context:"
                        if marker in content:
                            start_idx = content.find(marker)
                            # Extract from marker to end of content (or next major section)
                            context_text = content[start_idx + len(marker):].strip()
                            # Try to find end of data handling context section
                            # Look for common section markers that might follow
                            end_markers = ["\n\n## ", "\n\n# ", "\n\n---", "\n\nYou are", "\n\nIMPORTANT:"]
                            end_idx = len(context_text)
                            for end_marker in end_markers:
                                pos = context_text.find(end_marker)
                                if pos != -1 and pos < end_idx:
                                    end_idx = pos
                            data_context = context_text[:end_idx].strip() if end_idx > 0 else context_text

                    if data_context:
                        msg_data['data_handling_context'] = data_context

                session_data['messages'].append(msg_data)

            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)

            return True
        except Exception as e:
            print(f"Error saving conversation to {file_path}: {e}")
            return False

    def load_session_from_file(self, file_path: str, session_id: str = None) -> Optional[str]:
        """
        Load a conversation session from a JSON file.

        Args:
            file_path: Path to the conversation JSON file
            session_id: Optional session ID to use (uses file's session_id if not provided)

        Returns:
            The session_id if loaded successfully, None otherwise
        """
        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)

            # Use provided session_id or the one from file
            sid = session_id or session_data.get('session_id', str(uuid.uuid4()))

            # Reconstruct messages
            messages = []
            for msg_data in session_data.get('messages', []):
                msg = ConversationMessage(
                    role=msg_data['role'],
                    content=msg_data['content'],
                    timestamp=msg_data.get('timestamp', time.time()),
                    message_id=msg_data.get('message_id', str(uuid.uuid4())),
                    token_count=msg_data.get('token_count', 0),
                    tool_calls=msg_data.get('tool_calls'),
                    tool_call_id=msg_data.get('tool_call_id'),
                    data_handling_context=msg_data.get('data_handling_context')
                )
                messages.append(msg)

            # Create session
            session = ConversationSession(
                session_id=sid,
                messages=messages,
                created_at=session_data.get('created_at', time.time()),
                last_activity=session_data.get('last_activity', time.time()),
                total_tokens=session_data.get('total_tokens', 0),
                metadata=session_data.get('metadata', {})
            )

            # Store in memory
            self.sessions[sid] = session

            return sid
        except Exception as e:
            print(f"Error loading conversation from {file_path}: {e}")
            return None

    def get_or_create_session_for_workbench(self, workbench_session_id: str,
                                            conversation_file_path: str,
                                            system_prompt: str = None) -> str:
        """
        Get an existing conversation session or create/load one for a workbench session.

        This links the workbench session with the conversation session.

        Args:
            workbench_session_id: The workbench session ID to link with
            conversation_file_path: Path to the conversation file for this session
            system_prompt: System prompt to use if creating new session

        Returns:
            The conversation session_id (same as workbench_session_id)
        """
        # Check if session already in memory
        if workbench_session_id in self.sessions:
            self.current_session_id = workbench_session_id
            return workbench_session_id

        # Try to load from file
        if os.path.exists(conversation_file_path):
            loaded_id = self.load_session_from_file(conversation_file_path, workbench_session_id)
            if loaded_id:
                self.current_session_id = loaded_id
                return loaded_id

        # Create new session with the workbench session ID
        now = time.time()
        messages = []

        if system_prompt:
            system_msg = ConversationMessage(
                role="system",
                content=system_prompt,
                timestamp=now,
                message_id=str(uuid.uuid4()),
                token_count=self.count_tokens(system_prompt)
            )
            messages.append(system_msg)

        session = ConversationSession(
            session_id=workbench_session_id,
            messages=messages,
            created_at=now,
            last_activity=now,
            total_tokens=sum(m.token_count for m in messages)
        )

        self.sessions[workbench_session_id] = session
        self.current_session_id = workbench_session_id

        return workbench_session_id
