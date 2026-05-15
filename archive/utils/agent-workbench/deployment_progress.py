"""
Real-time deployment progress tracker for web interface
"""

import json
import time
from threading import Thread, Event
import queue

class DeploymentProgress:
    """Track deployment progress with real-time updates."""
    
    def __init__(self):
        self.progress_queue = queue.Queue()
        self.is_complete = Event()
        self.current_stage = ""
        self.verbose_output = []
        
    def update_stage(self, stage_name, message=""):
        """Update the current deployment stage."""
        self.current_stage = stage_name
        progress_data = {
            'stage': stage_name,
            'message': message,
            'timestamp': time.time(),
            'verbose_output': self.verbose_output.copy()
        }
        self.progress_queue.put(progress_data)
    
    def add_verbose_output(self, message):
        """Add a message to verbose output."""
        self.verbose_output.append(message)
        # Send incremental update
        progress_data = {
            'stage': self.current_stage,
            'message': message,
            'timestamp': time.time(),
            'incremental_output': [message]
        }
        self.progress_queue.put(progress_data)
    
    def complete(self, success, final_message, image_url=None):
        """Mark deployment as complete."""
        final_data = {
            'stage': 'complete',
            'success': success,
            'message': final_message,
            'image_url': image_url,
            'timestamp': time.time(),
            'verbose_output': self.verbose_output.copy()
        }
        self.progress_queue.put(final_data)
        self.is_complete.set()
    
    def get_progress_updates(self):
        """Generator that yields progress updates."""
        while not self.is_complete.is_set():
            try:
                update = self.progress_queue.get(timeout=1.0)
                yield update
            except queue.Empty:
                continue
        
        # Get any remaining updates
        while not self.progress_queue.empty():
            yield self.progress_queue.get()

# Global progress tracker instance
_current_progress = None

def get_progress_tracker():
    """Get the current progress tracker."""
    global _current_progress
    return _current_progress

def start_deployment_tracking():
    """Start a new deployment tracking session."""
    global _current_progress
    _current_progress = DeploymentProgress()
    return _current_progress

def stop_deployment_tracking():
    """Stop the current deployment tracking session."""
    global _current_progress
    if _current_progress:
        _current_progress.is_complete.set()
    _current_progress = None
