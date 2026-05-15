"""
Server-Sent Events (SSE) Streaming Infrastructure for Agent Workbench.

This module provides a robust, reusable SSE infrastructure for real-time
communication between the backend and frontend. It supports:

- Multiple event channels (job traces, build traces, system events)
- Context-based filtering (events tied to specific jobs, builds, agents)
- Event buffering for reconnection scenarios
- Thread-safe event publishing
- Automatic cleanup of old events

Usage:
    from sse_streaming import event_bus, create_sse_response
    
    # Publish an event
    event_bus.publish('job_trace', 'Uploading files...', context={'job_id': '123'})
    
    # Create SSE endpoint response
    @app.route('/api/sse/events')
    def sse_events():
        return create_sse_response(request.args)
"""

import json
import time
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, List, Any, Generator, Callable
from dataclasses import dataclass, field, asdict
from collections import deque
from flask import Response, request


class EventLevel(Enum):
    """Log levels for events."""
    DEBUG = 'debug'
    INFO = 'info'
    SUCCESS = 'success'
    WARNING = 'warning'
    ERROR = 'error'
    PROGRESS = 'progress'  # For progress updates with percentage


class EventChannel(Enum):
    """Event channels for routing."""
    JOB_TRACE = 'job_trace'           # Job submission traces (upload, cleanup, etc.)
    BUILD_TRACE = 'build_trace'       # Docker build traces
    DEPLOY_TRACE = 'deploy_trace'     # ACR/Discovery deployment traces
    EXECUTION = 'execution'           # Code execution output
    INTERACTIVE = 'interactive'       # Interactive session events
    SYSTEM = 'system'                 # System-wide notifications
    VALIDATION = 'validation'         # YAML/config validation events
    BLOB_LOG = 'blob_log'             # Real-time Azure blob log streaming


@dataclass
class Event:
    """Represents a single SSE event."""
    id: str
    channel: str
    level: str
    message: str
    timestamp: str
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    details: Optional[str] = None  # Expandable details (JSON, logs, etc.)
    is_update: bool = False  # True if this is an update to an existing event
    
    def to_sse(self) -> str:
        """Format event for SSE transmission."""
        data = {
            'id': self.id,
            'channel': self.channel,
            'level': self.level,
            'message': self.message,
            'timestamp': self.timestamp,
            'context': self.context,
            'metadata': self.metadata
        }
        if self.details:
            data['details'] = self.details
        if self.is_update:
            data['is_update'] = True
        # SSE format: data: {...}\n\n
        # Use 'update' event type for updates so client can differentiate
        event_type = 'update' if self.is_update else self.channel
        return f"id: {self.id}\nevent: {event_type}\ndata: {json.dumps(data)}\n\n"
    
    def matches_filter(self, channels: List[str] = None, context_filter: Dict[str, str] = None) -> bool:
        """Check if event matches the given filters."""
        # Channel filter
        if channels and self.channel not in channels:
            return False
        
        # Context filter (all specified keys must match)
        if context_filter:
            for key, value in context_filter.items():
                if self.context.get(key) != value:
                    return False
        
        return True


class EventBus:
    """
    Central event bus for SSE streaming.
    
    Thread-safe event publishing and subscription with buffering
    for reconnection scenarios.
    """
    
    def __init__(self, buffer_size: int = 500, buffer_ttl_seconds: int = 300):
        """
        Initialize the event bus.
        
        Args:
            buffer_size: Maximum number of events to keep in buffer
            buffer_ttl_seconds: How long to keep events (for reconnect)
        """
        self._buffer: deque = deque(maxlen=buffer_size)
        self._buffer_lock = threading.Lock()
        self._buffer_ttl = buffer_ttl_seconds
        
        # Active subscribers: {subscriber_id: {'queue': Queue, 'filters': {...}}}
        self._subscribers: Dict[str, Dict] = {}
        self._subscribers_lock = threading.Lock()
        
        # Event counter for ordering
        self._event_counter = 0
        self._counter_lock = threading.Lock()
        
        # Callbacks for event processing (useful for logging, metrics)
        self._callbacks: List[Callable[[Event], None]] = []
    
    def _next_event_id(self) -> str:
        """Generate a unique, ordered event ID."""
        with self._counter_lock:
            self._event_counter += 1
            return f"evt_{int(time.time() * 1000)}_{self._event_counter}"
    
    def publish(
        self,
        channel: str | EventChannel,
        message: str,
        level: str | EventLevel = EventLevel.INFO,
        context: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None,
        event_id: str = None,
        is_update: bool = False,
        details: str = None
    ) -> Event:
        """
        Publish an event to all matching subscribers.
        
        Args:
            channel: Event channel (use EventChannel enum or string)
            message: Human-readable message (summary)
            level: Event level (use EventLevel enum or string)
            context: Context for filtering (job_id, agent_name, etc.)
            metadata: Additional data (progress %, file paths, etc.)
            event_id: Optional fixed event ID (for updates)
            is_update: If True, marks this as an update to an existing event
            details: Optional expandable details (accumulated history, logs, etc.)
        
        Returns:
            The created Event object
        """
        # Normalize enums to strings
        if isinstance(channel, EventChannel):
            channel = channel.value
        if isinstance(level, EventLevel):
            level = level.value
        
        event = Event(
            id=event_id or self._next_event_id(),
            channel=channel,
            level=level,
            message=message,
            timestamp=datetime.now(timezone.utc).isoformat(),
            context=context or {},
            metadata=metadata or {},
            is_update=is_update,
            details=details
        )
        
        # Add to buffer for reconnect scenarios (only if not an update, or if it's the first time)
        with self._buffer_lock:
            if is_update:
                # Replace existing event with same ID in buffer
                for i, buffered_event in enumerate(self._buffer):
                    if buffered_event.id == event.id:
                        self._buffer[i] = event
                        break
                else:
                    # First update - add to buffer
                    self._buffer.append(event)
            else:
                self._buffer.append(event)
        
        # Notify all matching subscribers
        with self._subscribers_lock:
            for sub_id, sub_info in list(self._subscribers.items()):
                try:
                    filters = sub_info.get('filters', {})
                    channels = filters.get('channels')
                    context_filter = filters.get('context')
                    
                    if event.matches_filter(channels, context_filter):
                        sub_info['queue'].append(event)
                except Exception as e:
                    print(f"⚠️ Error notifying subscriber {sub_id}: {e}")
        
        # Call registered callbacks
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"⚠️ Error in event callback: {e}")
        
        return event
    
    def update_event(
        self,
        event_id: str,
        message: str = None,
        details: str = None,
        level: str = None,
        metadata: Dict[str, Any] = None
    ) -> Optional[Event]:
        """
        Update an existing event and notify subscribers.
        
        This is useful for streaming logs or progress updates to a single entry.
        
        Args:
            event_id: ID of the event to update
            message: New message (optional, keeps existing if None)
            details: New details content (optional)
            level: New level (optional)
            metadata: Metadata to merge (optional)
        
        Returns:
            The updated Event object, or None if not found
        """
        # Find the event in buffer
        with self._buffer_lock:
            event = None
            for e in self._buffer:
                if e.id == event_id:
                    event = e
                    break
            
            if not event:
                return None
            
            # Update fields
            if message is not None:
                event.message = message
            if details is not None:
                event.details = details
            if level is not None:
                # Handle both EventLevel enum and string
                event.level = level.value if hasattr(level, 'value') else level
            if metadata is not None:
                event.metadata.update(metadata)
            
            # Update timestamp to now
            event.timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create update notification (marked as update)
        update_event = Event(
            id=event.id,
            channel=event.channel,
            level=event.level,
            message=event.message,
            timestamp=event.timestamp,
            context=event.context,
            metadata=event.metadata,
            details=event.details,
            is_update=True
        )
        
        # Notify all matching subscribers about the update
        with self._subscribers_lock:
            for sub_id, sub_info in list(self._subscribers.items()):
                try:
                    filters = sub_info.get('filters', {})
                    channels = filters.get('channels')
                    context_filter = filters.get('context')
                    
                    if update_event.matches_filter(channels, context_filter):
                        sub_info['queue'].append(update_event)
                except Exception as e:
                    print(f"⚠️ Error notifying subscriber {sub_id} of update: {e}")
        
        return event
    
    def subscribe(
        self,
        channels: List[str] = None,
        context_filter: Dict[str, str] = None,
        last_event_id: str = None
    ) -> tuple[str, deque]:
        """
        Subscribe to events.
        
        Args:
            channels: List of channels to subscribe to (None = all)
            context_filter: Filter by context values
            last_event_id: Resume from this event ID (for reconnect)
        
        Returns:
            Tuple of (subscriber_id, event_queue)
        """
        subscriber_id = str(uuid.uuid4())
        event_queue = deque(maxlen=100)  # Per-subscriber buffer
        
        # If reconnecting, replay missed events
        if last_event_id:
            with self._buffer_lock:
                found_last = False
                for event in self._buffer:
                    if found_last:
                        if event.matches_filter(channels, context_filter):
                            event_queue.append(event)
                    elif event.id == last_event_id:
                        found_last = True
        
        with self._subscribers_lock:
            self._subscribers[subscriber_id] = {
                'queue': event_queue,
                'filters': {
                    'channels': channels,
                    'context': context_filter
                },
                'created_at': time.time()
            }
        
        return subscriber_id, event_queue
    
    def unsubscribe(self, subscriber_id: str) -> None:
        """Remove a subscriber."""
        with self._subscribers_lock:
            self._subscribers.pop(subscriber_id, None)
    
    def get_recent_events(
        self,
        channels: List[str] = None,
        context_filter: Dict[str, str] = None,
        limit: int = 50
    ) -> List[Event]:
        """Get recent events matching filters (for initial page load)."""
        with self._buffer_lock:
            matching = [
                e for e in self._buffer
                if e.matches_filter(channels, context_filter)
            ]
            return matching[-limit:]
    
    def add_callback(self, callback: Callable[[Event], None]) -> None:
        """Add a callback for all events (for logging, metrics)."""
        self._callbacks.append(callback)
    
    def cleanup_old_subscribers(self, max_age_seconds: int = 300) -> int:
        """Remove stale subscribers (call periodically)."""
        now = time.time()
        removed = 0
        with self._subscribers_lock:
            stale = [
                sub_id for sub_id, info in self._subscribers.items()
                if now - info['created_at'] > max_age_seconds
            ]
            for sub_id in stale:
                del self._subscribers[sub_id]
                removed += 1
        return removed
    
    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        with self._subscribers_lock:
            return len(self._subscribers)
    
    @property
    def buffer_size(self) -> int:
        """Number of events in buffer."""
        with self._buffer_lock:
            return len(self._buffer)


# Global event bus instance
event_bus = EventBus()


def create_sse_response(
    channels: List[str] = None,
    context_filter: Dict[str, str] = None,
    last_event_id: str = None,
    heartbeat_interval: int = 15
) -> Response:
    """
    Create a Flask Response for SSE streaming.
    
    Args:
        channels: List of channels to subscribe to
        context_filter: Filter by context (e.g., {'job_id': '123'})
        last_event_id: Resume from this event (for reconnect)
        heartbeat_interval: Seconds between keep-alive pings
    
    Returns:
        Flask Response with SSE stream
    """
    def generate() -> Generator[str, None, None]:
        subscriber_id, event_queue = event_bus.subscribe(
            channels=channels,
            context_filter=context_filter,
            last_event_id=last_event_id
        )
        print(f"[SSE] New subscriber {subscriber_id!s} channels={channels} context={context_filter}")
        # Suggest client reconnection wait time (ms)
        yield "retry: 10000\n\n"
        
        try:
            last_heartbeat = time.time()
            
            while True:
                # Check for events
                try:
                    while event_queue:
                        event = event_queue.popleft()
                        yield event.to_sse()
                        last_heartbeat = time.time()
                except IndexError:
                    pass
                
                # Send heartbeat if no events for a while
                if time.time() - last_heartbeat >= heartbeat_interval:
                    # Send an explicit ping event (some proxies drop comment-only heartbeats)
                    yield f"event: ping\ndata: {json.dumps({'ts': int(time.time())})}\n\n"
                    last_heartbeat = time.time()
                
                # Small sleep to prevent CPU spin
                time.sleep(0.1)
                
        except GeneratorExit:
            # Client disconnected
            print(f"[SSE] GeneratorExit for subscriber {subscriber_id}")
            raise
        except Exception as e:
            print(f"[SSE] Exception in SSE generator for {subscriber_id}: {e}")
            raise
        finally:
            event_bus.unsubscribe(subscriber_id)
            print(f"[SSE] Unsubscribed {subscriber_id}")
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
            'Access-Control-Allow-Origin': '*'
        }
    )


# ============================================================================
# Convenience functions for common event types
# ============================================================================

def trace_job(
    message: str,
    job_id: str,
    agent_name: str = None,
    level: EventLevel = EventLevel.INFO,
    metadata: Dict[str, Any] = None,
    details: str = None
) -> Event:
    """Publish a job trace event.
    
    Args:
        message: Human-readable summary message
        job_id: Job identifier
        agent_name: Optional agent name
        level: Event level
        metadata: Additional metadata
        details: Optional expandable details (JSON string, logs, etc.)
    """
    context = {'job_id': job_id}
    if agent_name:
        context['agent_name'] = agent_name
    
    event = Event(
        id=event_bus._next_event_id(),
        channel=EventChannel.JOB_TRACE.value,
        level=level.value if isinstance(level, EventLevel) else level,
        message=message,
        timestamp=datetime.now(timezone.utc).isoformat(),
        context=context,
        metadata=metadata or {},
        details=details
    )
    
    # Add to buffer
    with event_bus._buffer_lock:
        event_bus._buffer.append(event)
    
    # Notify subscribers
    with event_bus._subscribers_lock:
        for sub_id, sub_info in list(event_bus._subscribers.items()):
            try:
                filters = sub_info.get('filters', {})
                channels = filters.get('channels')
                context_filter = filters.get('context')
                if event.matches_filter(channels, context_filter):
                    sub_info['queue'].append(event)
            except Exception:
                pass
    
    return event


def update_job_trace(
    event_id: str,
    message: str = None,
    details: str = None,
    level: str = None,
    metadata: Dict[str, Any] = None
) -> Optional[Event]:
    """Update an existing job trace event.
    
    Useful for streaming logs or progress updates to a single Activity entry.
    
    Args:
        event_id: ID of the event to update (returned from trace_job)
        message: New message (optional)
        details: New details content (optional)
        level: New level (optional)
        metadata: Metadata to merge (optional)
    
    Returns:
        Updated Event, or None if not found
    """
    if isinstance(level, EventLevel):
        level = level.value
    return event_bus.update_event(event_id, message=message, details=details, level=level, metadata=metadata)


def trace_build(
    message: str,
    agent_name: str,
    level: EventLevel = EventLevel.INFO,
    metadata: Dict[str, Any] = None,
    session_id: str = None
) -> Event:
    """Publish a Docker build trace event."""
    context = {'agent_name': agent_name}
    if session_id:
        context['session_id'] = session_id
    return event_bus.publish(
        EventChannel.BUILD_TRACE,
        message,
        level=level,
        context=context,
        metadata=metadata
    )


def trace_deploy(
    message: str,
    agent_name: str,
    level: EventLevel = EventLevel.INFO,
    metadata: Dict[str, Any] = None,
    session_id: str = None
) -> Event:
    """Publish a deployment trace event."""
    context = {'agent_name': agent_name}
    if session_id:
        context['session_id'] = session_id
    return event_bus.publish(
        EventChannel.DEPLOY_TRACE,
        message,
        level=level,
        context=context,
        metadata=metadata
    )


def trace_progress(
    message: str,
    job_id: str,
    progress_percent: int,
    agent_name: str = None
) -> Event:
    """Publish a progress event with percentage."""
    context = {'job_id': job_id}
    if agent_name:
        context['agent_name'] = agent_name
    return event_bus.publish(
        EventChannel.JOB_TRACE,
        message,
        level=EventLevel.PROGRESS,
        context=context,
        metadata={'progress': progress_percent}
    )


def trace_system(
    message: str,
    level: EventLevel = EventLevel.INFO,
    metadata: Dict[str, Any] = None,
    details: str = None
) -> Event:
    """Publish a system-wide event.
    
    Args:
        message: Human-readable message
        level: Event level
        metadata: Additional metadata
        details: Optional expandable details (JSON string, logs, etc.)
    """
    if details:
        # If details provided, create event manually like trace_job does
        event = Event(
            id=event_bus._next_event_id(),
            channel=EventChannel.SYSTEM.value,
            level=level.value if isinstance(level, EventLevel) else level,
            message=message,
            timestamp=datetime.now(timezone.utc).isoformat(),
            context={},
            metadata=metadata or {},
            details=details
        )
        
        # Add to buffer
        with event_bus._buffer_lock:
            event_bus._buffer.append(event)
        
        # Notify subscribers
        with event_bus._subscribers_lock:
            for sub_id, sub_info in list(event_bus._subscribers.items()):
                try:
                    filters = sub_info.get('filters', {})
                    channels = filters.get('channels')
                    context_filter = filters.get('context')
                    if event.matches_filter(channels, context_filter):
                        sub_info['queue'].append(event)
                except Exception:
                    pass
        
        return event
    else:
        # No details, use normal publish
        return event_bus.publish(
            EventChannel.SYSTEM,
            message,
            level=level,
            metadata=metadata
        )


# ============================================================================
# Helper class for scoped tracing (job context)
# ============================================================================

class JobTracer:
    """
    Context manager for job-scoped tracing.
    
    Usage:
        with JobTracer(job_id, agent_name) as tracer:
            tracer.info("Starting upload...")
            tracer.progress("Uploading", 50)
            tracer.success("Upload complete")
    """
    
    def __init__(self, job_id: str, agent_name: str = None):
        self.job_id = job_id
        self.agent_name = agent_name
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.error(f"Job failed: {exc_val}")
        return False
    
    def _trace(self, message: str, level: EventLevel, metadata: Dict = None):
        trace_job(message, self.job_id, self.agent_name, level, metadata)
    
    def debug(self, message: str, **metadata):
        self._trace(message, EventLevel.DEBUG, metadata or None)
    
    def info(self, message: str, **metadata):
        self._trace(message, EventLevel.INFO, metadata or None)
    
    def success(self, message: str, **metadata):
        self._trace(message, EventLevel.SUCCESS, metadata or None)
    
    def warning(self, message: str, **metadata):
        self._trace(message, EventLevel.WARNING, metadata or None)
    
    def error(self, message: str, **metadata):
        self._trace(message, EventLevel.ERROR, metadata or None)
    
    def progress(self, message: str, percent: int):
        trace_progress(message, self.job_id, percent, self.agent_name)
    
    @property
    def elapsed_seconds(self) -> float:
        if self.start_time:
            return time.time() - self.start_time
        return 0


# ============================================================================
# Operation class for consolidated events
# ============================================================================

class OperationStatus(Enum):
    """Operation lifecycle states."""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    SUCCESS = 'success'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class Operation:
    """
    Manages a single high-level operation as a consolidated Activity event.

    Instead of publishing many individual events for a user action (e.g., ACR deployment),
    this class creates a single event that gets updated as progress is made. Steps are
    accumulated in the expandable details section.

    Usage with context manager:
        with Operation("ACR Deployment", channel=EventChannel.DEPLOY_TRACE,
                       context={'agent_name': 'my-agent'}, icon="🚀") as op:
            op.step("Authenticating to Azure...")
            op.step("Pushing image to ACR...")
            op.complete("Image pushed successfully")

    Manual usage:
        op = Operation("Docker Build", channel=EventChannel.BUILD_TRACE, icon="🔨")
        op.start()
        try:
            op.step("Building layer 1/5...")
            op.complete("Build successful")
        except Exception as e:
            op.fail(str(e))
    """

    def __init__(
        self,
        title: str,
        channel: EventChannel = EventChannel.SYSTEM,
        context: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None,
        icon: str = None
    ):
        """
        Initialize an operation.

        Args:
            title: Short description of the operation (e.g., "ACR Deployment")
            channel: Event channel for routing
            context: Context for filtering (agent_name, job_id, etc.)
            metadata: Additional metadata
            icon: Optional emoji icon (e.g., "🚀", "🔨")
        """
        self.title = title
        self.channel = channel
        self.context = context or {}
        self.metadata = metadata or {}
        self.icon = icon

        self.event_id: Optional[str] = None
        self.status = OperationStatus.PENDING
        self.steps: List[Dict[str, Any]] = []
        self.started_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
        self.error_message: Optional[str] = None

    def start(self, message: str = None) -> 'Operation':
        """Begin the operation - creates the initial event."""
        self.started_at = datetime.now(timezone.utc)
        self.status = OperationStatus.IN_PROGRESS

        initial_step = message or "Starting..."
        self.steps.append({
            'timestamp': self.started_at.isoformat(),
            'message': initial_step,
            'level': 'info'
        })

        display_message = f"{self.icon} {self.title}" if self.icon else self.title

        event = event_bus.publish(
            channel=self.channel,
            message=display_message,
            level=EventLevel.INFO,
            context=self.context,
            metadata={**self.metadata, 'operation_status': self.status.value},
            details=self._build_details()
        )
        self.event_id = event.id
        return self

    def step(self, message: str, level: EventLevel = EventLevel.INFO) -> 'Operation':
        """Add a step to the operation - updates the event in-place."""
        if self.event_id is None:
            self.start()

        level_str = level.value if isinstance(level, EventLevel) else level
        self.steps.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'message': message,
            'level': level_str
        })

        display_message = f"{self.icon} {self.title}: {message}" if self.icon else f"{self.title}: {message}"
        event_bus.update_event(
            self.event_id,
            message=display_message,
            details=self._build_details(),
            metadata={'operation_status': self.status.value}
        )
        return self

    def progress(self, message: str, percent: int) -> 'Operation':
        """Update with progress percentage."""
        if self.event_id is None:
            self.start()

        self.steps.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'message': message,
            'level': 'progress',
            'progress': percent
        })

        display_message = f"{self.icon} {self.title}: {message}" if self.icon else f"{self.title}: {message}"
        event_bus.update_event(
            self.event_id,
            message=display_message,
            level=EventLevel.PROGRESS,
            details=self._build_details(),
            metadata={'operation_status': self.status.value, 'progress': percent}
        )
        return self

    def complete(self, message: str = None) -> 'Operation':
        """Mark operation as successfully completed."""
        self.ended_at = datetime.now(timezone.utc)
        self.status = OperationStatus.SUCCESS

        final_message = message or "Completed"
        self.steps.append({
            'timestamp': self.ended_at.isoformat(),
            'message': final_message,
            'level': 'success'
        })

        display_message = f"{self.icon} {self.title}: {final_message}" if self.icon else f"{self.title}: {final_message}"
        event_bus.update_event(
            self.event_id,
            message=display_message,
            level=EventLevel.SUCCESS,
            details=self._build_details(),
            metadata={'operation_status': self.status.value, 'duration_ms': self._duration_ms()}
        )
        return self

    def fail(self, error: str) -> 'Operation':
        """Mark operation as failed."""
        self.ended_at = datetime.now(timezone.utc)
        self.status = OperationStatus.FAILED
        self.error_message = error

        # Truncate error for display message
        short_error = error[:100] + '...' if len(error) > 100 else error
        self.steps.append({
            'timestamp': self.ended_at.isoformat(),
            'message': f"Failed: {error}",
            'level': 'error'
        })

        display_message = f"{self.icon} {self.title}: Failed" if self.icon else f"{self.title}: Failed"
        event_bus.update_event(
            self.event_id,
            message=display_message,
            level=EventLevel.ERROR,
            details=self._build_details(),
            metadata={'operation_status': self.status.value, 'error': short_error, 'duration_ms': self._duration_ms()}
        )
        return self

    def cancel(self, reason: str = "Cancelled by user") -> 'Operation':
        """Mark operation as cancelled."""
        self.ended_at = datetime.now(timezone.utc)
        self.status = OperationStatus.CANCELLED

        self.steps.append({
            'timestamp': self.ended_at.isoformat(),
            'message': reason,
            'level': 'warning'
        })

        display_message = f"{self.icon} {self.title}: Cancelled" if self.icon else f"{self.title}: Cancelled"
        event_bus.update_event(
            self.event_id,
            message=display_message,
            level=EventLevel.WARNING,
            details=self._build_details(),
            metadata={'operation_status': self.status.value, 'duration_ms': self._duration_ms()}
        )
        return self

    def _build_details(self) -> str:
        """Build the expandable details content showing step history."""
        if not self.steps:
            return ""

        lines = []
        for step in self.steps:
            # Extract time portion from ISO timestamp
            ts = step['timestamp'].split('T')[1][:8]  # HH:MM:SS
            level_icon = {
                'debug': '🔍',
                'info': 'ℹ️',
                'success': '✅',
                'warning': '⚠️',
                'error': '❌',
                'progress': '⏳'
            }.get(step['level'], '•')

            msg = step['message']
            if 'progress' in step:
                msg = f"{msg} ({step['progress']}%)"

            lines.append(f"[{ts}] {level_icon} {msg}")

        # Add duration if completed
        if self.ended_at:
            duration_ms = self._duration_ms()
            duration_s = duration_ms / 1000
            lines.append(f"\n--- Duration: {duration_s:.1f}s ---")

        return '\n'.join(lines)

    def _duration_ms(self) -> int:
        """Calculate operation duration in milliseconds."""
        if self.started_at and self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds() * 1000)
        return 0

    def __enter__(self) -> 'Operation':
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.fail(str(exc_val))
        elif self.status == OperationStatus.IN_PROGRESS:
            self.complete()
        return False


# ============================================================================
# Operation factory functions
# ============================================================================

def acr_deploy_operation(agent_name: str, image_name: str, acr_name: str) -> Operation:
    """Create an ACR deployment operation."""
    return Operation(
        title=f"Deploy {agent_name} to ACR",
        channel=EventChannel.DEPLOY_TRACE,
        context={'agent_name': agent_name},
        metadata={'image': image_name, 'acr': acr_name},
        icon="🚀"
    )


def docker_build_operation(agent_name: str, image_name: str = None, session_id: str = None) -> Operation:
    """Create a Docker build operation."""
    context = {'agent_name': agent_name}
    if session_id:
        context['session_id'] = session_id
    return Operation(
        title=f"Build {agent_name}",
        channel=EventChannel.BUILD_TRACE,
        context=context,
        metadata={'image': image_name} if image_name else {},
        icon="🔨"
    )


def auth_operation(purpose: str = None, tenant_id: str = None) -> Operation:
    """Create an Azure authentication operation."""
    ctx = {}
    if purpose:
        ctx['purpose'] = purpose
    meta = {}
    if tenant_id:
        meta['tenant_id'] = tenant_id[:8] + '...' if len(tenant_id) > 8 else tenant_id
    return Operation(
        title="Azure Authentication",
        channel=EventChannel.SYSTEM,
        context=ctx,
        metadata=meta,
        icon="🔐"
    )


def container_operation(agent_name: str, container_name: str, image_name: str = None) -> Operation:
    """Create a container start operation."""
    return Operation(
        title=f"Start {container_name}",
        channel=EventChannel.SYSTEM,
        context={'agent_name': agent_name},
        metadata={'container_name': container_name, 'image': image_name} if image_name else {'container_name': container_name},
        icon="🚀"
    )


# ============================================================================
# Flask route helper
# ============================================================================

def register_sse_routes(app):
    """
    Register SSE routes on a Flask app.
    
    Call this in web_server.py:
        from sse_streaming import register_sse_routes
        register_sse_routes(app)
    """
    
    @app.route('/api/sse/events', methods=['GET'])
    def sse_events():
        """
        SSE endpoint for real-time events.
        
        Query parameters:
            channels: Comma-separated list of channels (optional)
            job_id: Filter by job ID (optional)
            agent_name: Filter by agent name (optional)
            last_event_id: Resume from event ID (optional)
        """
        # Parse query parameters
        channels_param = request.args.get('channels')
        channels = channels_param.split(',') if channels_param else None
        
        context_filter = {}
        if request.args.get('job_id'):
            context_filter['job_id'] = request.args.get('job_id')
        if request.args.get('agent_name'):
            context_filter['agent_name'] = request.args.get('agent_name')
        
        last_event_id = request.args.get('last_event_id') or request.headers.get('Last-Event-ID')
        
        return create_sse_response(
            channels=channels,
            context_filter=context_filter if context_filter else None,
            last_event_id=last_event_id
        )
    
    @app.route('/api/sse/events/recent', methods=['GET'])
    def sse_recent_events():
        """
        Get recent events (for initial page load).
        
        Query parameters same as /api/sse/events plus:
            limit: Max events to return (default 50)
        """
        channels_param = request.args.get('channels')
        channels = channels_param.split(',') if channels_param else None
        
        context_filter = {}
        if request.args.get('job_id'):
            context_filter['job_id'] = request.args.get('job_id')
        if request.args.get('agent_name'):
            context_filter['agent_name'] = request.args.get('agent_name')
        
        limit = int(request.args.get('limit', 50))
        
        events = event_bus.get_recent_events(
            channels=channels,
            context_filter=context_filter if context_filter else None,
            limit=limit
        )
        
        return {
            'success': True,
            'events': [asdict(e) for e in events],
            'count': len(events)
        }
    
    @app.route('/api/sse/status', methods=['GET'])
    def sse_status():
        """Get SSE system status."""
        return {
            'success': True,
            'subscribers': event_bus.subscriber_count,
            'buffer_size': event_bus.buffer_size
        }
    
    print("✅ SSE streaming routes registered")
