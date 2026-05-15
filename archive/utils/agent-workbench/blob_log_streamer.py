"""
Azure Blob Log Streamer for Agent Workbench.

Provides efficient, cost-optimized streaming of log files from Azure Storage blobs
using ETag-based conditional requests and range reads to minimize API calls and costs.

Key features:
- ETag-based change detection (only fetch when content changes)
- Range reads for incremental content (only fetch new bytes)
- Integration with SSE EventBus for real-time updates
- Thread-safe operation for multiple concurrent streams
- Automatic cleanup of stale streams

Usage:
    from blob_log_streamer import get_log_streamer

    streamer = get_log_streamer(
        account_url='https://myaccount.blob.core.windows.net',
        tenant_id='...'
    )

    stream_id = streamer.start_stream(
        container_name='logs',
        blob_name='job-123/stdout.log',
        job_id='123',
        agent_name='my-agent'
    )

    # Later...
    streamer.stop_stream(stream_id)
"""

import threading
import time
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum

_LOG = logging.getLogger(__name__)


class StreamState(Enum):
    """States for a log stream."""
    PENDING = 'pending'
    RUNNING = 'running'
    PAUSED = 'paused'
    STOPPED = 'stopped'
    ERROR = 'error'
    COMPLETED = 'completed'


@dataclass
class BlobStreamInfo:
    """Tracks state for a single blob stream."""
    stream_id: str
    blob_url: str
    container_name: str
    blob_name: str
    job_id: str
    agent_name: Optional[str] = None
    session_id: Optional[str] = None

    # State tracking
    state: StreamState = StreamState.PENDING
    last_etag: Optional[str] = None
    last_modified: Optional[datetime] = None
    bytes_read: int = 0
    content_length: int = 0

    # Buffered content (for clients that reconnect)
    accumulated_content: str = ""

    # Timing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_poll_at: Optional[datetime] = None
    last_content_at: Optional[datetime] = None

    # Polling state
    current_poll_interval: float = 2.0
    polls_without_change: int = 0

    # Error tracking
    consecutive_errors: int = 0
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'stream_id': self.stream_id,
            'blob_url': self.blob_url,
            'container_name': self.container_name,
            'blob_name': self.blob_name,
            'job_id': self.job_id,
            'agent_name': self.agent_name,
            'session_id': self.session_id,
            'state': self.state.value,
            'bytes_read': self.bytes_read,
            'content_length': self.content_length,
            'last_etag': self.last_etag,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_poll_at': self.last_poll_at.isoformat() if self.last_poll_at else None,
            'last_content_at': self.last_content_at.isoformat() if self.last_content_at else None,
            'current_poll_interval': self.current_poll_interval,
            'consecutive_errors': self.consecutive_errors,
            'last_error': self.last_error
        }


class BlobLogStreamer:
    """
    Manages streaming of log content from Azure Storage blobs.

    Uses ETag-based conditional requests and range reads to minimize
    storage costs while providing real-time log updates.
    """

    def __init__(
        self,
        credential: Any,
        account_url: str,
        poll_interval: float = 2.0,
        max_poll_interval: float = 30.0,
        backoff_multiplier: float = 1.5,
        idle_timeout: float = 300.0,  # 5 minutes
        max_content_buffer: int = 1024 * 1024,  # 1MB
        publish_to_sse: bool = True
    ):
        """
        Initialize the log streamer.

        Args:
            credential: Azure credential for authentication
            account_url: Azure Storage account URL (e.g., https://account.blob.core.windows.net)
            poll_interval: Base polling interval in seconds
            max_poll_interval: Maximum polling interval (for backoff)
            backoff_multiplier: Multiplier for backoff on no-change polls
            idle_timeout: Stop stream after this many seconds with no new content
            max_content_buffer: Maximum accumulated content to buffer (bytes)
            publish_to_sse: Whether to publish updates to SSE EventBus
        """
        self._credential = credential
        self._account_url = account_url.rstrip('/')
        self._poll_interval = poll_interval
        self._max_poll_interval = max_poll_interval
        self._backoff_multiplier = backoff_multiplier
        self._idle_timeout = idle_timeout
        self._max_content_buffer = max_content_buffer
        self._publish_to_sse = publish_to_sse

        # Active streams: {stream_id: BlobStreamInfo}
        self._streams: Dict[str, BlobStreamInfo] = {}
        self._streams_lock = threading.Lock()

        # Callbacks: {stream_id: [callback_fn, ...]}
        self._callbacks: Dict[str, List[Callable]] = {}

        # Worker thread
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Blob service client (lazy initialization)
        self._blob_service = None
        self._blob_service_lock = threading.Lock()

    def _get_blob_service(self):
        """Lazy initialization of blob service client."""
        if self._blob_service is None:
            with self._blob_service_lock:
                if self._blob_service is None:
                    from azure.storage.blob import BlobServiceClient
                    self._blob_service = BlobServiceClient(
                        account_url=self._account_url,
                        credential=self._credential
                    )
        return self._blob_service

    def start_stream(
        self,
        container_name: str,
        blob_name: str,
        job_id: str,
        agent_name: Optional[str] = None,
        session_id: Optional[str] = None,
        on_content: Optional[Callable[[str, bool], None]] = None,
        initial_offset: int = 0
    ) -> str:
        """
        Start streaming a blob's content.

        Args:
            container_name: Azure container name
            blob_name: Blob path within container
            job_id: Job ID for SSE context
            agent_name: Optional agent name for SSE context
            session_id: Optional session ID for SSE context
            on_content: Callback(content, is_complete) for new content
            initial_offset: Start reading from this byte offset

        Returns:
            Stream ID for managing the stream
        """
        stream_id = f"bloblog_{job_id}_{uuid.uuid4().hex[:8]}"

        blob_url = f"{self._account_url}/{container_name}/{blob_name}"

        stream_info = BlobStreamInfo(
            stream_id=stream_id,
            blob_url=blob_url,
            container_name=container_name,
            blob_name=blob_name,
            job_id=job_id,
            agent_name=agent_name,
            session_id=session_id,
            bytes_read=initial_offset,
            state=StreamState.RUNNING,
            current_poll_interval=self._poll_interval
        )

        with self._streams_lock:
            self._streams[stream_id] = stream_info
            if on_content:
                self._callbacks[stream_id] = [on_content]

        # Publish SSE event that streaming has started
        if self._publish_to_sse:
            self._publish_sse_event(
                stream_info,
                f"Started streaming logs from {blob_name}",
                level='info',
                is_start=True
            )

        # Start worker thread if not running
        self._ensure_worker_running()

        _LOG.info(f"[BlobLogStreamer] Started stream {stream_id} for {blob_url}")
        return stream_id

    def stop_stream(self, stream_id: str, reason: str = "Stopped by request") -> bool:
        """Stop a specific stream."""
        with self._streams_lock:
            if stream_id in self._streams:
                info = self._streams[stream_id]
                info.state = StreamState.STOPPED

                # Publish SSE event that streaming has stopped
                if self._publish_to_sse:
                    self._publish_sse_event(
                        info,
                        f"Stopped streaming: {reason}",
                        level='info',
                        is_end=True
                    )

                self._callbacks.pop(stream_id, None)
                _LOG.info(f"[BlobLogStreamer] Stopped stream {stream_id}: {reason}")
                return True
        return False

    def stop_all_streams(self):
        """Stop all active streams."""
        with self._streams_lock:
            for stream_id in list(self._streams.keys()):
                self._streams[stream_id].state = StreamState.STOPPED
            self._callbacks.clear()

    def get_stream_info(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """Get current state of a stream."""
        with self._streams_lock:
            info = self._streams.get(stream_id)
            if info:
                return info.to_dict()
        return None

    def get_all_streams(self) -> List[Dict[str, Any]]:
        """Get info for all streams."""
        with self._streams_lock:
            return [info.to_dict() for info in self._streams.values()]

    def get_accumulated_content(self, stream_id: str) -> Optional[str]:
        """Get all accumulated content for a stream (for reconnecting clients)."""
        with self._streams_lock:
            info = self._streams.get(stream_id)
            if info:
                return info.accumulated_content
        return None

    def add_callback(self, stream_id: str, callback: Callable[[str, bool], None]) -> bool:
        """Add a callback to an existing stream."""
        with self._streams_lock:
            if stream_id in self._streams:
                if stream_id not in self._callbacks:
                    self._callbacks[stream_id] = []
                self._callbacks[stream_id].append(callback)
                return True
        return False

    def _ensure_worker_running(self):
        """Ensure the polling worker thread is running."""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._poll_worker,
                daemon=True,
                name="BlobLogStreamer-Worker"
            )
            self._worker_thread.start()
            _LOG.info("[BlobLogStreamer] Worker thread started")

    def _poll_worker(self):
        """Background worker that polls all active streams."""
        _LOG.info("[BlobLogStreamer] Poll worker starting")

        while not self._stop_event.is_set():
            try:
                # Get snapshot of active streams
                with self._streams_lock:
                    active_streams = [
                        (sid, info) for sid, info in self._streams.items()
                        if info.state == StreamState.RUNNING
                    ]

                if not active_streams:
                    # No active streams, wait and check again
                    time.sleep(1.0)
                    continue

                # Poll each stream
                for stream_id, stream_info in active_streams:
                    if self._stop_event.is_set():
                        break

                    try:
                        self._poll_stream(stream_id, stream_info)
                    except Exception as e:
                        _LOG.error(f"[BlobLogStreamer] Error polling {stream_id}: {e}")
                        stream_info.consecutive_errors += 1
                        stream_info.last_error = str(e)

                        # Mark as error after too many failures
                        if stream_info.consecutive_errors > 10:
                            stream_info.state = StreamState.ERROR
                            if self._publish_to_sse:
                                self._publish_sse_event(
                                    stream_info,
                                    f"Stream error after {stream_info.consecutive_errors} failures: {e}",
                                    level='error',
                                    is_end=True
                                )

                # Clean up completed/stopped streams
                self._cleanup_streams()

                # Sleep for minimum poll interval
                time.sleep(self._poll_interval)

            except Exception as e:
                _LOG.error(f"[BlobLogStreamer] Worker error: {e}")
                time.sleep(1.0)

        _LOG.info("[BlobLogStreamer] Poll worker stopped")

    def _poll_stream(self, stream_id: str, info: BlobStreamInfo):
        """Poll a single stream for new content."""
        from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

        blob_service = self._get_blob_service()
        blob_client = blob_service.get_blob_client(
            container=info.container_name,
            blob=info.blob_name
        )

        info.last_poll_at = datetime.now(timezone.utc)

        try:
            # Get blob properties (HEAD request - very cheap)
            properties = blob_client.get_blob_properties()

            current_etag = properties.etag
            current_length = properties.size

            # Check if content changed
            if info.last_etag and current_etag == info.last_etag:
                # No change - apply backoff
                info.polls_without_change += 1
                if info.current_poll_interval < self._max_poll_interval:
                    info.current_poll_interval = min(
                        info.current_poll_interval * self._backoff_multiplier,
                        self._max_poll_interval
                    )

                # Check for idle timeout
                if info.last_content_at:
                    idle_seconds = (datetime.now(timezone.utc) - info.last_content_at).total_seconds()
                    if idle_seconds > self._idle_timeout:
                        _LOG.info(f"[BlobLogStreamer] Stream {stream_id} idle timeout after {idle_seconds:.0f}s")
                        info.state = StreamState.COMPLETED
                        if self._publish_to_sse:
                            self._publish_sse_event(
                                info,
                                f"Log streaming completed (idle for {int(idle_seconds)}s)",
                                level='success',
                                is_end=True
                            )
                return

            # Content changed or first poll - reset backoff
            info.last_etag = current_etag
            info.content_length = current_length
            info.polls_without_change = 0
            info.current_poll_interval = self._poll_interval

            # Calculate range to read (only new bytes)
            if current_length > info.bytes_read:
                # Use range read to get only new content
                offset = info.bytes_read
                length = current_length - info.bytes_read

                # Download new content with range
                download_stream = blob_client.download_blob(
                    offset=offset,
                    length=length
                )
                new_content = download_stream.readall().decode('utf-8', errors='replace')

                # Update state
                info.bytes_read = current_length
                info.last_content_at = datetime.now(timezone.utc)
                info.consecutive_errors = 0

                # Accumulate content (with size limit)
                info.accumulated_content += new_content
                if len(info.accumulated_content) > self._max_content_buffer:
                    # Keep only recent content
                    info.accumulated_content = info.accumulated_content[-self._max_content_buffer:]

                # Notify via callbacks
                callbacks = self._callbacks.get(stream_id, [])
                for callback in callbacks:
                    try:
                        callback(new_content, False)  # is_complete=False
                    except Exception as e:
                        print(f"[BlobLogStreamer] Callback error: {e}")
                        _LOG.error(f"[BlobLogStreamer] Callback error: {e}")

                # Publish to SSE EventBus
                if self._publish_to_sse:
                    self._publish_sse_content(info, new_content)

            elif current_length < info.bytes_read:
                # File was truncated/rewritten - reset and read from start
                _LOG.warning(f"[BlobLogStreamer] Blob {info.blob_name} was truncated, resetting read position")
                info.bytes_read = 0
                info.accumulated_content = ""
                # Will fetch full content on next poll

        except ResourceNotFoundError:
            # Blob doesn't exist yet - wait for it
            info.consecutive_errors += 1
            if info.consecutive_errors == 1:
                _LOG.debug(f"[BlobLogStreamer] Blob not found yet: {info.blob_name}")

        except HttpResponseError as e:
            if e.status_code == 304:
                # Not modified - expected with conditional requests
                pass
            else:
                raise

    def _publish_sse_content(self, info: BlobStreamInfo, new_content: str):
        """Publish log content update to SSE EventBus."""
        try:
            from sse_streaming import event_bus, EventChannel, EventLevel

            # Truncate for summary message
            lines = new_content.strip().split('\n')
            if len(lines) > 3:
                preview = '\n'.join(lines[:2]) + f'\n... (+{len(lines) - 2} more lines)'
            else:
                preview = new_content.strip()

            if len(preview) > 200:
                preview = preview[:200] + '...'

            context = {'job_id': info.job_id}
            if info.agent_name:
                context['agent_name'] = info.agent_name
            if info.session_id:
                context['session_id'] = info.session_id
            context['stream_id'] = info.stream_id

            event_bus.publish(
                channel=EventChannel.BLOB_LOG,
                message=f"[LOG] {preview.replace(chr(10), ' ')}",
                level=EventLevel.INFO,
                context=context,
                metadata={
                    'bytes_read': info.bytes_read,
                    'content_length': info.content_length,
                    'blob_name': info.blob_name,
                    'new_bytes': len(new_content)
                },
                details=new_content  # Full content in expandable details
            )
        except Exception as e:
            _LOG.error(f"[BlobLogStreamer] SSE publish error: {e}")

    def _publish_sse_event(
        self,
        info: BlobStreamInfo,
        message: str,
        level: str = 'info',
        is_start: bool = False,
        is_end: bool = False
    ):
        """Publish a stream lifecycle event to SSE EventBus."""
        try:
            from sse_streaming import event_bus, EventChannel, EventLevel

            level_map = {
                'debug': EventLevel.DEBUG,
                'info': EventLevel.INFO,
                'success': EventLevel.SUCCESS,
                'warning': EventLevel.WARNING,
                'error': EventLevel.ERROR
            }

            context = {'job_id': info.job_id}
            if info.agent_name:
                context['agent_name'] = info.agent_name
            if info.session_id:
                context['session_id'] = info.session_id
            context['stream_id'] = info.stream_id

            metadata = {
                'blob_name': info.blob_name,
                'bytes_read': info.bytes_read,
                'is_stream_start': is_start,
                'is_stream_end': is_end
            }

            event_bus.publish(
                channel=EventChannel.BLOB_LOG,
                message=message,
                level=level_map.get(level, EventLevel.INFO),
                context=context,
                metadata=metadata
            )
        except Exception as e:
            _LOG.error(f"[BlobLogStreamer] SSE event publish error: {e}")

    def _cleanup_streams(self):
        """Remove completed/stopped/error streams after a delay."""
        now = datetime.now(timezone.utc)
        cleanup_delay = 60  # Keep ended streams for 60 seconds for status queries

        with self._streams_lock:
            to_remove = []
            for sid, info in self._streams.items():
                if info.state in (StreamState.STOPPED, StreamState.COMPLETED, StreamState.ERROR):
                    # Check if stream has been in terminal state long enough
                    if info.last_poll_at:
                        ended_seconds = (now - info.last_poll_at).total_seconds()
                        if ended_seconds > cleanup_delay:
                            to_remove.append(sid)

            for sid in to_remove:
                del self._streams[sid]
                self._callbacks.pop(sid, None)
                _LOG.debug(f"[BlobLogStreamer] Cleaned up stream {sid}")

    def shutdown(self):
        """Shutdown the streamer and stop all streams."""
        _LOG.info("[BlobLogStreamer] Shutting down")
        self._stop_event.set()
        self.stop_all_streams()
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
        _LOG.info("[BlobLogStreamer] Shutdown complete")


# Module-level singleton for shared use
_default_streamer: Optional[BlobLogStreamer] = None
_streamer_lock = threading.Lock()


def get_log_streamer(
    credential: Any = None,
    account_url: str = None,
    tenant_id: str = None,
    create_if_missing: bool = True
) -> Optional[BlobLogStreamer]:
    """
    Get or create the default BlobLogStreamer instance.

    Args:
        credential: Azure credential (will auto-obtain if not provided)
        account_url: Storage account URL
        tenant_id: Tenant ID for credential acquisition
        create_if_missing: If True, create new streamer if none exists

    Returns:
        BlobLogStreamer instance or None if initialization fails
    """
    global _default_streamer

    with _streamer_lock:
        if _default_streamer is not None:
            return _default_streamer

        if not create_if_missing:
            return None

        # Need both credential and account_url to create streamer
        if credential is None and tenant_id:
            try:
                from azure_auth_helpers import get_credential_for_tenant
                credential = get_credential_for_tenant(tenant_id, purpose='blob-log-streaming')
            except Exception as e:
                _LOG.error(f"[BlobLogStreamer] Failed to get credential: {e}")
                return None

        if credential is None or account_url is None:
            _LOG.debug("[BlobLogStreamer] Missing credential or account_url, cannot create streamer")
            return None

        _default_streamer = BlobLogStreamer(
            credential=credential,
            account_url=account_url
        )
        _LOG.info(f"[BlobLogStreamer] Created default streamer for {account_url}")

        return _default_streamer


def set_log_streamer(streamer: BlobLogStreamer) -> None:
    """Set the default streamer instance (for testing or custom configuration)."""
    global _default_streamer
    with _streamer_lock:
        _default_streamer = streamer


def shutdown_log_streamer():
    """Shutdown the default streamer."""
    global _default_streamer
    with _streamer_lock:
        if _default_streamer:
            _default_streamer.shutdown()
            _default_streamer = None
            _LOG.info("[BlobLogStreamer] Default streamer shutdown")


class LogFolderWatcher:
    """
    Watches a blob folder/prefix for .log files and auto-starts streaming them.

    This is useful when you don't know the exact log filenames upfront - the watcher
    will discover .log files as they appear and stream their content via BlobLogStreamer.

    Usage:
        watcher = LogFolderWatcher(
            credential=credential,
            account_url='https://account.blob.core.windows.net',
            container_name='outputs',
            prefix='job-123/output/',
            job_id='123',
            local_output_dir='/path/to/session/output'  # For Logs tab integration
        )
        watcher.start()
        # ... job runs ...
        watcher.stop()
    """

    def __init__(
        self,
        credential: Any,
        account_url: str,
        container_name: str,
        prefix: str,
        job_id: str,
        agent_name: Optional[str] = None,
        session_id: Optional[str] = None,
        scan_interval: float = 5.0,
        log_extensions: List[str] = None,
        local_output_dir: Optional[str] = None
    ):
        """
        Initialize the folder watcher.

        Args:
            credential: Azure credential
            account_url: Storage account URL
            container_name: Container to watch
            prefix: Blob prefix (folder path) to watch
            job_id: Job ID for context
            agent_name: Optional agent name
            session_id: Optional session ID
            scan_interval: How often to scan for new log files (seconds)
            log_extensions: List of extensions to watch (default: ['.log', '.out', '.err', '.stdout', '.stderr', '.output'])
            local_output_dir: Local directory to write streamed log content (for Logs tab)
        """
        self._credential = credential
        self._account_url = account_url.rstrip('/')
        self._container_name = container_name
        self._prefix = prefix.rstrip('/') + '/' if prefix else ''
        self._job_id = job_id
        self._agent_name = agent_name
        self._session_id = session_id
        self._scan_interval = scan_interval
        # Common log/output extensions from computational tools (LAMMPS, QE, etc.)
        self._log_extensions = log_extensions or ['.log', '.out', '.err', '.stdout', '.stderr', '.output']
        self._local_output_dir = local_output_dir

        self._streamer: Optional[BlobLogStreamer] = None
        self._active_streams: Dict[str, str] = {}  # blob_name -> stream_id
        self._local_files: Dict[str, str] = {}  # stream_id -> local_file_path
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._blob_service = None

    def _get_blob_service(self):
        """Lazy initialization of blob service client."""
        if self._blob_service is None:
            from azure.storage.blob import BlobServiceClient
            self._blob_service = BlobServiceClient(
                account_url=self._account_url,
                credential=self._credential
            )
        return self._blob_service

    def _get_streamer(self) -> BlobLogStreamer:
        """Get or create the streamer instance."""
        if self._streamer is None:
            # Don't publish to SSE - content goes to local files for Logs tab instead
            # Discovery API logs are published separately to SSE for stdout tab
            self._streamer = BlobLogStreamer(
                credential=self._credential,
                account_url=self._account_url,
                publish_to_sse=False
            )
        return self._streamer

    def start(self):
        """Start watching for .log files."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._watch_worker,
            daemon=True,
            name=f"LogFolderWatcher-{self._job_id[:8]}"
        )
        self._worker_thread.start()
        ext_list = ', '.join(self._log_extensions)

        # Publish start event
        try:
            from sse_streaming import event_bus, EventChannel, EventLevel
            event_bus.publish(
                channel=EventChannel.BLOB_LOG,
                message=f"📂 Started watching for log files in {self._prefix}",
                level=EventLevel.INFO,
                context={'job_id': self._job_id, 'agent_name': self._agent_name},
                metadata={'container': self._container_name, 'prefix': self._prefix, 'is_watcher_start': True}
            )
        except Exception:
            pass

    def stop(self):
        """Stop watching and stop all active streams."""
        self._stop_event.set()

        # Stop all active streams
        if self._streamer:
            for blob_name, stream_id in list(self._active_streams.items()):
                self._streamer.stop_stream(stream_id, reason="Watcher stopped")

        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)

        # Publish stop event
        try:
            from sse_streaming import event_bus, EventChannel, EventLevel
            event_bus.publish(
                channel=EventChannel.BLOB_LOG,
                message=f"📂 Stopped watching for log files",
                level=EventLevel.INFO,
                context={'job_id': self._job_id, 'agent_name': self._agent_name},
                metadata={'is_watcher_end': True, 'streams_stopped': len(self._active_streams)}
            )
        except Exception:
            pass

        self._active_streams.clear()

    def _watch_worker(self):
        """Background worker that scans for .log files and starts streaming them."""

        while not self._stop_event.is_set():
            try:
                self._scan_for_logs()
            except Exception as e:
                _LOG.error(f"[LogFolderWatcher] Scan error: {e}")

            # Wait for scan interval
            self._stop_event.wait(self._scan_interval)

    def _scan_for_logs(self):
        """Scan the prefix for .log files and start streaming any new ones."""
        import os
        try:
            blob_service = self._get_blob_service()
            container_client = blob_service.get_container_client(self._container_name)

            # List blobs with the prefix
            blobs = container_client.list_blobs(name_starts_with=self._prefix)

            blob_count = 0
            for blob in blobs:
                blob_name = blob.name
                blob_count += 1
                # Check if it's a log file
                is_log = any(blob_name.lower().endswith(ext) for ext in self._log_extensions)

                if is_log and blob_name not in self._active_streams:
                    # Start streaming this log file

                    try:
                        streamer = self._get_streamer()

                        # Set up local file for writing if output dir configured
                        local_file_path = None
                        content_callback = None
                        if self._local_output_dir:
                            # Use just the filename from blob_name
                            local_filename = os.path.basename(blob_name)
                            local_file_path = os.path.join(self._local_output_dir, local_filename)
                            os.makedirs(self._local_output_dir, exist_ok=True)
                            # Create/truncate the file
                            with open(local_file_path, 'w', encoding='utf-8') as f:
                                f.write('')  # Initialize empty

                            # Create callback to append content to local file
                            def make_callback(file_path):
                                def write_to_local(content: str, is_complete: bool):
                                    try:
                                        with open(file_path, 'a', encoding='utf-8') as f:
                                            f.write(content)
                                    except Exception as e:
                                        _LOG.error(f"[LogFolderWatcher] Failed to write to {file_path}: {e}")
                                return write_to_local
                            content_callback = make_callback(local_file_path)

                        stream_id = streamer.start_stream(
                            container_name=self._container_name,
                            blob_name=blob_name,
                            job_id=self._job_id,
                            agent_name=self._agent_name,
                            session_id=self._session_id,
                            on_content=content_callback
                        )
                        self._active_streams[blob_name] = stream_id
                        if local_file_path:
                            self._local_files[stream_id] = local_file_path
                    except Exception as e:
                        print(f"[LogFolderWatcher] Failed to start stream for {blob_name}: {e}")
                        _LOG.error(f"[LogFolderWatcher] Failed to start stream for {blob_name}: {e}")

            if blob_count == 0:
                print(f"[LogFolderWatcher] No blobs found in {self._container_name}/{self._prefix}")

        except Exception as e:
            print(f"[LogFolderWatcher] Failed to list blobs: {e}")
            _LOG.error(f"[LogFolderWatcher] Failed to list blobs: {e}")

    @property
    def active_stream_count(self) -> int:
        """Number of active log streams."""
        return len(self._active_streams)

    @property
    def watched_files(self) -> List[str]:
        """List of blob names being streamed."""
        return list(self._active_streams.keys())


# Active folder watchers for cleanup
_active_watchers: Dict[str, LogFolderWatcher] = {}
_watchers_lock = threading.Lock()


def start_log_folder_watcher(
    credential: Any,
    account_url: str,
    container_name: str,
    prefix: str,
    job_id: str,
    agent_name: Optional[str] = None,
    session_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    local_output_dir: Optional[str] = None
) -> Optional[LogFolderWatcher]:
    """
    Start watching a folder for .log files.

    Args:
        credential: Azure credential (will auto-obtain if tenant_id provided)
        account_url: Storage account URL
        container_name: Container name
        prefix: Blob prefix (folder) to watch
        job_id: Job ID for tracking
        agent_name: Optional agent name
        session_id: Optional session ID
        tenant_id: Tenant ID for credential acquisition
        local_output_dir: Local directory to write streamed logs (for Logs tab integration)

    Returns:
        LogFolderWatcher instance or None if failed
    """
    global _active_watchers

    if credential is None and tenant_id:
        try:
            from azure_auth_helpers import get_credential_for_tenant
            credential = get_credential_for_tenant(tenant_id, purpose='log-folder-watching')
        except Exception as e:
            _LOG.error(f"[LogFolderWatcher] Failed to get credential: {e}")
            return None

    if not credential:
        _LOG.error("[LogFolderWatcher] No credential available")
        return None

    watcher = LogFolderWatcher(
        credential=credential,
        account_url=account_url,
        container_name=container_name,
        prefix=prefix,
        job_id=job_id,
        agent_name=agent_name,
        session_id=session_id,
        local_output_dir=local_output_dir
    )
    watcher.start()

    with _watchers_lock:
        _active_watchers[job_id] = watcher

    return watcher


def stop_log_folder_watcher(job_id: str) -> bool:
    """Stop a log folder watcher by job ID."""
    global _active_watchers

    with _watchers_lock:
        watcher = _active_watchers.pop(job_id, None)

    if watcher:
        watcher.stop()
        return True
    return False


def stop_all_log_folder_watchers():
    """Stop all active folder watchers."""
    global _active_watchers

    with _watchers_lock:
        watchers = list(_active_watchers.values())
        _active_watchers.clear()

    for watcher in watchers:
        watcher.stop()
