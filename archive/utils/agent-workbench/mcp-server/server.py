#!/usr/bin/env python3
"""MCP Server for Discovery Agent Workbench"""
import json
import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import subprocess
from typing import Dict, Any, Optional, List
import traceback
import re
from collections import defaultdict
from datetime import datetime
import requests

# Suppress debug output from helper modules by default to avoid VS Code MCP warnings
# The helper modules (azure_auth_helpers.py, discovery_publisher.py) use _debug_print()
# which only outputs when DEBUG_AUTH or DEBUG_DISCOVERY environment variables are set.
#
# To enable verbose debug output:
#   - Set DEBUG_AUTH=true for authentication debug messages
#   - Set DEBUG_DISCOVERY=true for Discovery API debug messages
#   - Set both to see all debug output
#
# Debug messages are logged via the Python logging system and will appear in the log file
# (utils/agent-workbench/logs/mcp_server.log) when enabled.
os.environ.setdefault('DEBUG_AUTH', 'false')
os.environ.setdefault('DEBUG_DISCOVERY', 'false')

# Add the workbench directory to the path
# The workbench is one level up from this file (mcp-server/server.py)
workbench_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, workbench_dir)

try:
    from agent_manager import StaticAgentManager
    from discovery_config_manager import DiscoveryConfigManager
    from devtunnel import (
        InteractiveSessionManager, 
        InteractiveSessionConfig, 
        DevTunnelError
    )
    HAS_WORKBENCH = True
    HAS_DEVTUNNEL = True
except ImportError as e:
    # Write to stderr instead of stdout to avoid interfering with JSON-RPC protocol
    import sys
    sys.stderr.write(f"Warning: Could not import workbench components: {e}\n")
    sys.stderr.write(f"Tried to import from: {workbench_dir}\n")
    sys.stderr.flush()
    HAS_WORKBENCH = False
    HAS_DEVTUNNEL = False

# Set up file-based logging to avoid VS Code stderr warnings
def setup_logging():
    """Configure file-based logging with rotation"""
    # Store logs in the workbench directory, not in the mcp-server package
    workbench_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    log_dir = os.path.join(workbench_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "mcp_server.log")
    
    # Create rotating file handler (10MB max, keep 5 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    
    return logging.getLogger(__name__)

logger = setup_logging()

# Sensitive data masking utility
class SensitiveDataMasker:
    """Utility to mask sensitive data in logs"""
    
    SENSITIVE_PATTERNS = [
        (re.compile(r'(api[_-]?key["\']?\s*[:=]\s*["\']?)([^"\',\s]+)', re.IGNORECASE), r'\1***MASKED***'),
        (re.compile(r'(password["\']?\s*[:=]\s*["\']?)([^"\',\s]+)', re.IGNORECASE), r'\1***MASKED***'),
        (re.compile(r'(token["\']?\s*[:=]\s*["\']?)([^"\',\s]+)', re.IGNORECASE), r'\1***MASKED***'),
        (re.compile(r'(secret["\']?\s*[:=]\s*["\']?)([^"\',\s]+)', re.IGNORECASE), r'\1***MASKED***'),
        (re.compile(r'(authorization["\']?\s*[:=]\s*["\']?)([^"\',\s]+)', re.IGNORECASE), r'\1***MASKED***'),
    ]
    
    @staticmethod
    def mask(text: str) -> str:
        """Mask sensitive data in text before logging"""
        if not isinstance(text, str):
            text = str(text)
        
        for pattern, replacement in SensitiveDataMasker.SENSITIVE_PATTERNS:
            text = pattern.sub(replacement, text)
        
        return text

# Error tracking and metrics
class ErrorTracker:
    """Track errors and metrics for monitoring and debugging"""
    
    def __init__(self):
        self.error_counts = defaultdict(int)
        self.error_details = []
        self.max_details = 100  # Keep last 100 errors
    
    def record_error(self, error_type: str, error_message: str, context: Optional[Dict[str, Any]] = None):
        """Record an error occurrence"""
        self.error_counts[error_type] += 1
        
        error_detail = {
            "timestamp": datetime.now().isoformat(),
            "type": error_type,
            "message": SensitiveDataMasker.mask(error_message),
            "context": SensitiveDataMasker.mask(str(context)) if context else None
        }
        
        self.error_details.append(error_detail)
        
        # Keep only last N errors to prevent memory issues
        if len(self.error_details) > self.max_details:
            self.error_details = self.error_details[-self.max_details:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get error statistics"""
        return {
            "error_counts": dict(self.error_counts),
            "total_errors": sum(self.error_counts.values()),
            "recent_errors": self.error_details[-10:]  # Last 10 errors
        }
    
    def reset(self):
        """Reset error tracking"""
        self.error_counts.clear()
        self.error_details.clear()

# Global error tracker instance
error_tracker = ErrorTracker()

logger.info("MCP Server logging initialized - logs written to logs/mcp_server.log")

class DiscoveryMCPServer:
    """MCP Server for Discovery Agent Workbench"""
    
    def __init__(self):
        self.agent_manager: Optional[StaticAgentManager] = None
        self.config_manager: Optional[DiscoveryConfigManager] = None
        self._initialized = False
        
        # Investigation tracking
        self._current_investigation_id: Optional[str] = None
        self._investigation_counter = 0
        
        # Cache for published agents/tools to reduce API calls
        self._published_agents_cache = None
        self._published_agents_cache_time = None
        self._published_tools_cache = None
        self._published_tools_cache_time = None
        self._cache_ttl_seconds = 3600  # 1 hour TTL for caches
        
        # Config file monitoring for automatic reload
        self._config_file_path: Optional[str] = None
        self._config_file_mtime: Optional[float] = None
        
        # Define tools
        self.tools = [
            {
                "name": "create_investigation",
                "description": "Create a new investigation ID for organizing work. CRITICAL: Call this at the start of working on a new user request to get an investigation_id. All subsequent tool calls (especially write_organized_file, submit_job, upload_input_files) must include this investigation_id to keep files and jobs organized together. The investigation creates a folder structure automatically under investigations/inv_XXX/ with subdirectories for scripts/, inputs/, outputs/, tests/, and docs/. The investigation_id groups all related work in this dedicated folder structure. Returns a unique investigation ID (e.g., 'inv_001', 'inv_002').",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Optional: Brief description of the investigation (e.g., 'EGFR inhibitor screening', 'protein structure analysis')."
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "list_published_agents_and_tools",
                "description": "List all computational agents and scientific workflows deployed in your Azure Discovery workspace, with their attached tools and complete tool details. For each agent, shows the tools it can use with their infrastructure configuration (infra nodes) and code execution environments. Returns agents with their complete tool information including tool names, resource IDs, infrastructure specifications, and code environments. Use this as the primary catalog to discover what research capabilities are available - from drug discovery pipelines and molecular dynamics workflows to quantum chemistry tools and protein structure analysis software.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name_filter": {
                            "type": "string",
                            "description": "Optional: Filter by specific agent or tool name. If not provided, lists everything."
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "get_published_agent_usage",
                "description": "Get usage instructions for a specific computational agent or scientific workflow. Returns the agent's instructions field which explains how to use the agent/tool, what it does, and how to write scripts for it. ALWAYS call this before writing scripts to understand the agent's capabilities and requirements. Essential for understanding tool usage patterns, input/output expectations, and best practices.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Required: Name of the agent to retrieve details for."
                        }
                    },
                    "required": ["agent_name"]
                }
            },
            {
                "name": "upload_input_files",
                "description": "Upload local files to Azure Storage to be used as inputs for computational jobs. Uploads files from a local directory to a designated blob storage location under the configured data asset path. Automatically appends a unique GUID to the path to avoid conflicts. Returns 'remote_prefix' (including GUID) which you MUST pass to submit_job's input_files_prefix parameter. Essential for providing input data files (molecular structures, parameters, datasets) to scientific computations running on the Discovery Supercomputer.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "local_path": {
                            "type": "string",
                            "description": "Required: Absolute path to local directory or file to upload. If a directory, all files within will be uploaded recursively."
                        },
                        "remote_prefix": {
                            "type": "string",
                            "description": "Optional: Remote path prefix/folder name under the data asset where files will be uploaded. A unique GUID will be automatically appended to this prefix. If not provided, a timestamped folder will be created automatically (e.g., 'upload-20231108-123456/{guid}')."
                        }
                    },
                    "required": ["local_path"]
                }
            },
            {
                "name": "submit_job",
                "description": "Submit a computational job to execute on the Azure Discovery Supercomputer. Execute scientific Python code using specialized tools (molecular dynamics simulators like GROMACS, protein structure databases like PDB, chemical property calculators, quantum chemistry tools, etc.) on high-performance computing infrastructure. Select the most appropriate nodepool based on your agent's requirements and job complexity and Provide the nodepool_name parameter. Supports automatic job chaining - specify depends_on_job_id to automatically mount outputs from a completed parent job as inputs. Ideal for multi-stage workflows like protein preparation → grid generation → docking. By default, waits for job completion and returns final status. Returns job ID for monitoring and result retrieval. 🚫 CRITICAL LIMITATION: Each job can ONLY use ONE tool/agent. DO NOT create scripts that import or use multiple tool utilities.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Required: Name of the agent/tool to use for execution (e.g., 'pdbSearch', 'gromacs', 'molToolkit'). This determines which tool definition and container image will be used."
                        },
                        "script_path": {
                            "type": "string",
                            "description": "Required: Path to a Python script file to execute. The file will be uploaded and executed on the supercomputer. Create and save your script file before calling this tool."
                        },
                        "input_files_prefix": {
                            "type": "string",
                            "description": "Optional: Remote path prefix returned from upload_input_files. If provided, input files at this location will be mounted at /input/ in the job container. Ignored if depends_on_job_id is specified (parent outputs take precedence)."
                        },
                        "nodepool_name": {
                            "type": "string",
                            "description": "Required: Name of the specific nodepool to use for execution (e.g., 'mynodepool', 'nodepool01'). MUST call list_nodepools first to discover available nodepools. Use the 'name' field from list_nodepools output, NOT the 'vm_size' field. Select the appropriate nodepool based on its CPU, memory, GPU requirements, and pool type matching your tool's compute needs."
                        },
                        "depends_on_job_id": {
                            "type": "string",
                            "description": "Optional: Job ID of a parent job whose outputs should be automatically mounted as inputs at /input/. When specified, this job will use the parent job's /output/ directory as its /input/ directory, enabling seamless job chaining. The parent job must be in Succeeded status (or will wait if wait_for_parent=true)."
                        },
                        "wait_for_parent": {
                            "type": "boolean",
                            "description": "Optional: Only used with depends_on_job_id. If true (default), automatically waits for parent job to complete before submitting. If false, submits immediately (parent must already be Succeeded)."
                        },
                        "wait_for_completion": {
                            "type": "boolean",
                            "description": "Optional: If true (default), waits for the job to complete and returns final status. If false, returns immediately after submission without waiting."
                        },
                        "timeout_seconds": {
                            "type": "number",
                            "description": "Optional: Maximum time to wait for job completion in seconds (default: 3600 = 1 hour). Only used when wait_for_completion=true."
                        },
                        "interactive_mode": {
                            "type": "string",
                            "enum": ["none", "vscode", "novnc"],
                            "description": "Optional: Enable interactive remote access via VS Code CLI tunnels. 'vscode' opens VS Code tunnel for debugging/editing directly in container. 'novnc' opens graphical desktop for GUI apps. Default: 'none'. When enabled, automatically waits for tunnel auth info and returns authentication URL and code - no manual polling needed."
                        },
                        "interactive_timeout_minutes": {
                            "type": "number",
                            "description": "Optional: How long to keep interactive tunnel alive (default: 30 minutes)."
                        }
                    },
                    "required": ["agent_name", "script_path", "nodepool_name"]
                }
            },
            {
                "name": "get_job_results",
                "description": "Download and retrieve output files and results from completed computational jobs. Automatically saves files to the investigation's outputs directory (investigations/inv_XXX/output/job_<id>/) for easy access via read_file tool. Returns simulation trajectories, calculated molecular properties, protein structures, energy profiles, analytical results, log files, and other scientific data generated by your computations. Use this after job completion to access molecular dynamics trajectories, docking scores, quantum chemistry results, or any other scientific outputs.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Required: The Discovery job/operation ID."
                        },
                        "investigation_id": {
                            "type": "string",
                            "description": "Required: Investigation ID from create_investigation. Results will be saved to the investigation's outputs directory (investigations/inv_XXX/output/job_<id>/)."
                        }
                    },
                    "required": ["job_id", "investigation_id"]
                }
            },
            {
                "name": "get_job_logs",
                "description": "Retrieve execution logs for a computational job running on the Discovery Supercomputer. Returns console output, error messages, progress indicators, and diagnostic information from the running or completed job. The returned log text is verbatim from the backend; callers should not inject truncation markers (e.g., '(truncated for brevity)') into saved copies. Note: tail is best-effort and the backend may cap the amount of log text returned. Use wait_for_completion=true to poll until the job finishes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Required: The Discovery job/operation ID returned from submit_job."
                        },
                        "tail": {
                            "type": "number",
                            "description": "Optional: Number of last lines to retrieve (default: 100). Best-effort: the backend may return fewer lines than requested. Use smaller values (20-50) for quick checks, larger values (500-1000+) when supported."
                        },
                        "wait_for_completion": {
                            "type": "boolean",
                            "description": "Optional: If true, polls the job status every poll_interval seconds until the job reaches a terminal state (Succeeded, Failed, or Canceled), then returns the final logs. Default: false (returns immediately with current logs)."
                        },
                        "poll_interval": {
                            "type": "number",
                            "description": "Optional: Seconds between status checks when wait_for_completion=true. Default: 30 seconds. Minimum: 10 seconds."
                        },
                        "timeout_seconds": {
                            "type": "number",
                            "description": "Optional: Maximum time to wait for job completion in seconds when wait_for_completion=true. Default: 3600 (1 hour)."
                        }
                    },
                    "required": ["job_id"]
                }
            },
            {
                "name": "cancel_job",
                "description": "Cancel a running or queued computational job on the Discovery Supercomputer. Use this when you realize a mistake in job configuration, need to free up resources, or want to stop a long-running computation. The job will be terminated and marked as Canceled. This is useful for stopping jobs with incorrect parameters, wrong input files, or computational tasks that are taking longer than expected.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Required: The Discovery job/operation ID to cancel."
                        }
                    },
                    "required": ["job_id"]
                }
            },
            {
                "name": "check_interactive_prerequisites",
                "description": "Check if Dev Tunnels CLI is installed and ready for interactive mode. Call this before using interactive_mode in submit_job. Returns installation status and setup instructions if Dev Tunnels is not ready. Interactive mode allows VS Code remote access or graphical desktop without requiring Kubernetes access.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_interactive_session",
                "description": "Get connection information for an interactive session associated with a job. Returns the tunnel URL and connection instructions for VS Code or noVNC access. Use this after submitting a job with interactive_mode to get the access details.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Required: The job ID to get interactive session info for."
                        }
                    },
                    "required": ["job_id"]
                }
            },
            {
                "name": "close_interactive_session",
                "description": "Close an interactive debugging session and CANCEL the underlying job to free the container. Use this when you're done debugging. This stops the running job, terminates the VS Code tunnel, and releases the compute resources. Always call this when finished debugging to avoid wasting resources.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {
                            "type": "string",
                            "description": "Required: The job ID whose interactive session should be closed and canceled."
                        }
                    },
                    "required": ["job_id"]
                }
            },
            {
                "name": "cleanup_files",
                "description": "Delete files or directories from local filesystem or Azure Storage. Use this to clean up temporary files, remove old job outputs, free up storage space, or maintain workspace hygiene. Supports deleting local files/directories and remote Azure Storage paths. For remote cleanup, provide the full discovery:// URI or blob path. Be cautious as deletions are permanent and cannot be undone.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Required: Path to file or directory to delete. Can be local path (e.g., './output/old_results') or remote Azure Storage path (e.g., 'discovery://dataassets/.../output' or blob URL)."
                        },
                        "location": {
                            "type": "string",
                            "enum": ["local", "remote"],
                            "description": "Required: Specify 'local' for local filesystem or 'remote' for Azure Storage."
                        },
                        "recursive": {
                            "type": "boolean",
                            "description": "Optional: If true, recursively delete directories and their contents (default: false). Required for non-empty directories."
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "Optional: Safety check - must be true to proceed with deletion (default: false). Prevents accidental deletions."
                        }
                    },
                    "required": ["path", "location"]
                }
            },
            {
                "name": "cleanup_folder",
                "description": "Delete an entire folder and all its contents (local or remote). Use this to clean up workflow directories, remove old test results, clear temporary data, or reset workspace organization. Can target local filesystem directories (scripts/, tests/, outputs/, etc.) or remote Azure Storage paths. CAUTION: This permanently deletes the folder and all files within it - cannot be undone.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "folder_path": {
                            "type": "string",
                            "description": "Required: Path to folder to delete. For local: relative path like './investigations/inv_001/tests/01_prepwizard' or absolute path. For remote: Azure Storage path (e.g., 'discovery://dataassets/.../output/job_xxx')."
                        },
                        "location": {
                            "type": "string",
                            "enum": ["local", "remote"],
                            "description": "Required: Specify 'local' for local filesystem or 'remote' for Azure Storage."
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "Optional: Safety check - must be true to proceed with deletion (default: false). Prevents accidental deletions."
                        }
                    },
                    "required": ["folder_path", "location"]
                }
            },
            {
                "name": "write_organized_file",
                "description": "Write content to a file in an organized directory structure. Use this instead of creating files in arbitrary locations. Automatically organizes files into appropriate subdirectories (scripts/, inputs/, outputs/, tests/, docs/) based on file purpose. Creates parent directories as needed. This tool helps maintain a clean workspace and prevents scattered files. Always use this tool when creating test scripts, result files, or any other files. CRITICAL: Always provide investigation_id (from create_investigation) to keep all files for the same investigation organized together.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "investigation_id": {
                            "type": "string",
                            "description": "Required: Investigation ID from create_investigation. All files for the same investigation will be organized in the same folder structure."
                        },
                        "content": {
                            "type": "string",
                            "description": "Required: Content to write to the file."
                        },
                        "filename": {
                            "type": "string",
                            "description": "Required: Name of the file (e.g., 'test_prepwizard.py', 'results.json'). Just the filename, not the full path."
                        },
                        "category": {
                            "type": "string",
                            "enum": ["script", "input", "output", "test", "doc", "config"],
                            "description": "Required: File category for organization. 'script' → scripts/, 'input' → inputs/, 'output' → outputs/, 'test' → tests/, 'doc' → docs/, 'config' → config/"
                        },
                        "subdirectory": {
                            "type": "string",
                            "description": "Optional: Additional subdirectory within category (e.g., 'prepwizard' for tests/02_prepwizard/). Automatically numbered sequentially (01_, 02_, 03_, etc.) to show workflow order. Use to group related files."
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "Optional: Whether to overwrite if file exists (default: false). Set true to update existing files."
                        }
                    },
                    "required": ["investigation_id", "content", "filename", "category"]
                }
            },
            {
                "name": "lessons_learned",
                "description": "Manage a structured knowledge base of lessons learned, best practices, and debugging insights. Supports: 'read' (get all or specific entries), 'update' (add new lessons), 'search' (find by keyword/category), 'categories' (list all categories), 'delete' (remove entry by ID). Data is stored as JSON for efficient querying while maintaining Markdown export capability.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["read", "update", "search", "categories", "delete"],
                            "description": "Required: 'read' to retrieve lessons, 'update' to add new lesson, 'search' to find lessons, 'categories' to list all categories, 'delete' to remove an entry."
                        },
                        "content": {
                            "type": "string",
                            "description": "Required for 'update': The lesson content in markdown format."
                        },
                        "category": {
                            "type": "string",
                            "description": "Optional for 'update', used for filtering in 'search': Category/topic (e.g., 'ChEMBL API', 'Job Submission')."
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional for 'update': List of tags for the lesson (e.g., ['testing', 'molToolkit', 'bug-fix'])."
                        },
                        "query": {
                            "type": "string",
                            "description": "Required for 'search': Search term to find in lesson content, category, or tags."
                        },
                        "entry_id": {
                            "type": "string",
                            "description": "Required for 'delete', optional for 'read': Specific entry ID to delete or retrieve."
                        },
                        "investigation_id": {
                            "type": "string",
                            "description": "Optional for 'update': Link lesson to a specific investigation."
                        },
                        "job_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional for 'update': Link lesson to specific job IDs."
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["critical", "warning", "info"],
                            "description": "Optional for 'update': Priority level of the lesson. Default: 'info'."
                        },
                        "format": {
                            "type": "string",
                            "enum": ["json", "markdown"],
                            "description": "Optional for 'read': Output format. Default: 'json'."
                        }
                    },
                    "required": ["action"]
                }
            },
            {
                "name": "list_nodepools",
                "description": "List all available nodepools in your Azure Discovery Supercomputer with their key characteristics (CPU, memory, storage, pool type, GPU support). Use this to compare nodepool capabilities with your tool/agent requirements to decide which is the best nodepool to use for your jobs. Returns detailed specifications for each nodepool including compute resources, infrastructure type, and pool configuration. Each nodepool has a 'name' field (e.g., 'deadpool2', 'nodepool01') - this is what you pass to submit_job's nodepool_name parameter. The 'vm_size' field (e.g., 'Standard_D4s_v6') is for informational purposes only and should NOT be used as the nodepool_name.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]

    def _find_config_file(self) -> Optional[str]:
        """Find discovery config file in common locations"""
        # Get the agent-workbench directory path (parent of mcp-server)
        workbench_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        possible_paths = [
            # Environment variable
            os.environ.get("DISCOVERY_CONFIG_PATH"),
            # Agent-workbench directory (prioritized - parent of mcp-server)
            os.path.join(workbench_dir, "discovery_config.json"),
            # MCP server directory
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "discovery_config.json"),
            # Current directory
            "discovery_config.json",
            # Parent directory
            "../discovery_config.json",
            # Discovery root
            "../../discovery_config.json",
            # User home directory
            os.path.expanduser("~/discovery_config.json"),
        ]
        
        for path in possible_paths:
            if path and os.path.isfile(path):
                return os.path.abspath(path)
        
        return None

    def _find_catalog_file(self) -> Optional[str]:
        """Find agent catalog file in common locations"""
        # Get the agent-workbench directory path (parent of mcp-server)
        workbench_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        possible_paths = [
            # Environment variable
            os.environ.get("AGENTS_CATALOG_PATH"),
            # Agent-workbench directory (prioritized - parent of mcp-server)
            os.path.join(workbench_dir, "agents-catalog.yaml"),
            # Current directory
            "agents-catalog.yaml",
            # Parent directory
            "../agents-catalog.yaml",
            # Discovery root
            "../../agents-catalog.yaml",
            # Solutions directory
            "../../6-solutions/agents-catalog.yaml",
            # User home directory
            os.path.expanduser("~/agents-catalog.yaml"),
        ]
        
        for path in possible_paths:
            if path and os.path.isfile(path):
                return os.path.abspath(path)
        
        return None
    
    # Helper methods for common authentication and configuration patterns
    
    def _get_azure_config_with_validation(self, required_fields: list) -> tuple:
        """Get and validate Azure configuration
        
        Args:
            required_fields: List of required field names (e.g., ['subscription_id', 'tenant_id', 'workspace'])
            
        Returns:
            Tuple of (azure_config, azure_compute_config, extracted_values_dict)
            
        Raises:
            ValueError: If config manager not initialized or required fields missing
        """
        if not self.config_manager:
            raise ValueError("Configuration manager not initialized")
        
        azure_config = self.config_manager.get_azure_config()
        azure_compute_config = self.config_manager.get_azure_compute_config()
        
        if not azure_config or not azure_compute_config:
            raise ValueError("Azure configuration or compute configuration is missing")
        
        # Extract and validate required fields
        extracted = {}
        missing_configs = []
        
        # Map of field names to their config source
        field_mapping = {
            'subscription_id': (azure_config, 'subscription_id'),
            'resource_group': (azure_config, 'resource_group'),
            'tenant_id': (azure_config, 'tenant_id'),
            'supercomputer_name': (azure_compute_config, 'discovery_supercomputer'),
            'workspace_name': (azure_compute_config, 'workspace'),
            'project_name': (azure_compute_config, 'project'),
            'storage_account': (azure_compute_config, 'storage_account'),
            'discovery_storage': (azure_compute_config, 'discovery_storage')
        }
        
        for field in required_fields:
            if field not in field_mapping:
                raise ValueError(f"Unknown configuration field: {field}")
            
            config_source, config_key = field_mapping[field]
            value = config_source.get(config_key, '').strip()
            
            if not value:
                missing_configs.append(config_key)
            
            extracted[field] = value
        
        if missing_configs:
            raise ValueError(f"Missing required configuration: {', '.join(missing_configs)}")
        
        return azure_config, azure_compute_config, extracted
    
    def _get_discovery_token(self, workspace_name: str, tenant_id: str, server_traces: list, 
                            purpose: str = 'discovery') -> str:
        """Get Discovery API access token with automatic scope fallback
        
        Args:
            workspace_name: Name of the Discovery workspace
            tenant_id: Azure tenant ID
            server_traces: List to append trace messages to
            purpose: Purpose string for logging (default: 'discovery')
            
        Returns:
            Discovery API access token
            
        Raises:
            ValueError: If token acquisition fails for all scope candidates
        """
        try:
            from azure_auth_helpers import get_token_for_tenant
        except ImportError:
            raise ValueError("azure_auth_helpers module not found")
        
        scope_candidates = (
            "https://discovery.azure.com/.default",
            f"https://{workspace_name}.workspace.discovery.azure.com/.default",
            "https://discovery.azure.com/access_as_user"
        )
        
        for scope_candidate in scope_candidates:
            try:
                local_traces = []
                token = get_token_for_tenant(scope_candidate, tenant_id, local_traces, purpose=purpose)
                if token:
                    server_traces.append("Authenticated to Discovery API")
                    return token
            except Exception:
                continue
        
        raise ValueError("Failed to obtain Discovery workspace access token")

    def _get_azure_management_token(self, tenant_id: str, server_traces: list) -> str:
        """Get Azure Management API access token with tenant-aware authentication
        
        Args:
            tenant_id: Azure tenant ID
            server_traces: List to append trace messages to
            
        Returns:
            Azure Management API access token
            
        Raises:
            ValueError: If token acquisition fails
        """
        try:
            from azure_auth_helpers import get_token_for_tenant
        except ImportError:
            raise ValueError("azure_auth_helpers module not found")
        
        token = get_token_for_tenant(
            "https://management.azure.com/.default",
            tenant_id,
            server_traces,
            purpose='azure_management'
        )
        
        if not token:
            raise ValueError("Failed to obtain Azure Management API access token")
        
        return token

    async def _ensure_initialized(self):
        """Ensure the server components are initialized"""
        if self._initialized:
            return
            
        if not HAS_WORKBENCH:
            raise ValueError("Workbench components not available. Please ensure agent_manager and discovery_config_manager modules are installed.")

        # Try to load discovery config - require actual files, don't create placeholders
        config_path = self._find_config_file()
        if not config_path:
            workbench_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            raise ValueError(
                f"Discovery configuration file not found. Please create:\n"
                f"  {os.path.join(workbench_dir, 'discovery_config.json')}\n"
                f"Configure it with your Azure subscription, resource group, workspace, and supercomputer details.\n"
                f"You can also use 'discovery_config_template.json' as a template."
            )
        
        self.config_manager = DiscoveryConfigManager(config_path)
        logger.info(f"Loaded discovery config from: {config_path}")
        
        # Store config file path and modification time for change detection
        self._config_file_path = config_path
        self._config_file_mtime = os.path.getmtime(config_path)
        logger.info(f"Monitoring config file for changes: {config_path}")
        
        # Try to load agent catalog - require actual files, don't create placeholders
        catalog_path = self._find_catalog_file()
        if not catalog_path:
            workbench_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            raise ValueError(
                f"Agent catalog file not found. Please create:\n"
                f"  {os.path.join(workbench_dir, 'agents-catalog.yaml')}\n"
                f"Define your available agents and tools for local development.\n"
                f"You can also use 'agents-catalog-template.yaml' as a template."
            )
        
        self.agent_manager = StaticAgentManager(catalog_path)
        logger.info(f"Loaded agent catalog from: {catalog_path}")
        
        self._initialized = True
        logger.info("Server components initialized successfully")

    async def _check_and_reload_config(self):
        """Check if config file has changed and reload if necessary"""
        if not self._initialized or not self._config_file_path:
            return
        
        try:
            current_mtime = os.path.getmtime(self._config_file_path)
            
            # If file modification time has changed, reload the config
            if current_mtime != self._config_file_mtime:
                logger.info(f"Config file changed detected (mtime: {self._config_file_mtime} -> {current_mtime}), reloading...")
                
                # Reload the config manager
                self.config_manager = DiscoveryConfigManager(self._config_file_path)
                self._config_file_mtime = current_mtime
                
                # Clear caches since we're potentially in a different environment
                self._published_agents_cache = None
                self._published_agents_cache_time = None
                self._published_tools_cache = None
                self._published_tools_cache_time = None
                
                logger.info(f"Config reloaded successfully from {self._config_file_path}")
        except Exception as e:
            logger.warning(f"Error checking/reloading config file: {e}")

    def handle_initialize(self, request_id: int) -> Dict[str, Any]:
        """Handle initialize request"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": True
                    }
                },
                "serverInfo": {
                    "name": "discovery-workbench",
                    "version": "1.0.0",
                    "description": "Azure Discovery platform for scientific and engineering high-performance computing. Execute computational workloads on Azure supercomputers using deployed agents and tools. Query available capabilities, submit jobs remotely, and orchestrate complex computational pipelines. For agent catalog management, configuration, tool publishing, and workflow visualization, use the companion discovery-management server."
                },
                "instructions": "Purpose: MCP server for scientific/engineering jobs—treat resources as expensive-don't run anything locally unless no other tool can perform the job; Plan: analyze request, pick correct published agent/tool, sketch steps, clarify only if ambiguous; Discoverability: call list_published_agents_and_tools, read each agent’s agent_description and attached_tools. You MUST call get_published_agent_details to know more precisely when and how to use the agents and their tools. actions, names are case-sensitive; Investigation: when uploading inputs, writing files, or running jobs, call create_investigation() once per task and reuse its ID—purely read-only control-plane calls (list_published_agents_and_tools, list_nodepools, tool publishing, etc.) do not need an investigation; Files: always write_organized_file(investigation_id, category=script|test|input|doc) → investigations/inv_XXX/(scripts|tests/inputs|docs)/ with auto 01_, 02_ numbering—do not write ad-hoc paths; Job execution (REQUIRED STEPS): BEFORE submit_job → MUST call list_nodepools to discover available compute resources → SELECT appropriate nodepool using its NAME field (e.g., 'deadpool2', NOT the vm_size like 'Standard_D4s_v6') based on tool requirements (CPU/memory/GPU/pool type) → THEN submit_job(agent_name, script_path, nodepool_name[, depends_on_job_id]) where nodepool_name is the 'name' from list_nodepools → wait for completion → get_job_results(job_id, investigation_id) which saves results to investigations/inv_XXX/output/job_YYY; Script rules: save Python to file, validate/compile before submit, one tool/agent per job (no multi-tool imports); Data flow (remote-first): keep compute/intermediates remote, chain with depends_on_job_id, download only for final analysis/visualization/debug, avoid download→upload loops; Testing: test with small datasets first, then scale to full data; Monitoring: get_job_logs(job_id). When saving logs, persist the returned logs verbatim; do NOT insert manual placeholders like '(truncated for brevity)'. If you need a short view, save a separate summary. Note: even with a large tail value, the backend may cap how many lines are available/returned; if you need more context, also download artifacts via get_job_results(job_id, investigation_id) and inspect any log files in outputs; Cleanup: cleanup_folder('./investigations/inv_XXX','local') when done; Typical workflow: create_investigation → choose proper tools → write_organized_file → list_nodepools → select nodepool BY NAME → upload_input_files → submit_job(with nodepool_name from list_nodepools) → get_job_results(job_id, investigation_id) → (optional chain via depends_on_job_id) → cleanup; Multi-tool pipelines: split into sequential jobs Job1(tool A) → Job2(tool B, depends_on Job1) → Job3(tool C, depends_on Job2) (e.g., Prep → Grid → Dock)."
            }
        }

    def handle_initialized(self) -> None:
        """Handle initialized notification"""
        pass

    def handle_list_tools(self, request_id: int) -> Dict[str, Any]:
        """Handle list tools request"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": self.tools
            }
        }

    async def handle_call_tool(self, request_id: int, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tool call request"""
        try:
            result = await self._handle_tool_call(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ],
                    "isError": False
                }
            }
        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {str(e)}"
                        }
                    ],
                    "isError": True
                }
            }

    async def _handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle individual tool calls"""
        await self._ensure_initialized()
        
        # Check if config file has changed and reload if necessary
        await self._check_and_reload_config()

        if name == "create_investigation":
            description = arguments.get("description")
            return await self._create_investigation(description)
        elif name == "list_published_agents_and_tools":
            name_filter = arguments.get("name_filter")
            return await self._list_published_agents_and_tools(name_filter)
        elif name == "get_published_agent_usage":
            agent_name = arguments.get("agent_name")
            if not agent_name:
                raise ValueError("agent_name is required")
            return await self._get_published_agent_usage(agent_name)
        elif name == "upload_input_files":
            local_path = arguments.get("local_path")
            remote_prefix = arguments.get("remote_prefix")
            if not local_path:
                raise ValueError("local_path is required")
            return await self._upload_input_files(local_path, remote_prefix)
        elif name == "submit_job":
            agent_name = arguments.get("agent_name")
            script_path = arguments.get("script_path")
            input_files_prefix = arguments.get("input_files_prefix")
            nodepool_name = arguments.get("nodepool_name")
            depends_on_job_id = arguments.get("depends_on_job_id")
            wait_for_parent = arguments.get("wait_for_parent", True)
            wait_for_completion = arguments.get("wait_for_completion", True)
            timeout_seconds = arguments.get("timeout_seconds", 3600)
            interactive_mode = arguments.get("interactive_mode", "none")
            interactive_timeout_minutes = arguments.get("interactive_timeout_minutes", 30)
            if not agent_name:
                raise ValueError("agent_name is required")
            if not script_path:
                raise ValueError("script_path is required")
            if not nodepool_name:
                raise ValueError("nodepool_name is required. Use list_nodepools to see available nodepools.")
            logger.info(f"Tool call handler: interactive_mode = {interactive_mode}")
            return await self._submit_job(agent_name, script_path, nodepool_name, input_files_prefix, depends_on_job_id, wait_for_parent, wait_for_completion, timeout_seconds, interactive_mode, interactive_timeout_minutes)
        elif name == "get_job_results":
            job_id = arguments.get("job_id")
            investigation_id = arguments.get("investigation_id")
            if not job_id:
                raise ValueError("job_id is required")
            if not investigation_id:
                raise ValueError("investigation_id is required")
            return await self._get_job_results(job_id, investigation_id)
        elif name == "cancel_job":
            job_id = arguments.get("job_id")
            if not job_id:
                raise ValueError("job_id is required")
            return await self._cancel_job(job_id)
        
        elif name == "check_interactive_prerequisites":
            return await self._check_interactive_prerequisites()
        
        elif name == "get_interactive_session":
            job_id = arguments.get("job_id")
            if not job_id:
                raise ValueError("job_id is required")
            return await self._get_interactive_session(job_id)
        
        elif name == "close_interactive_session":
            job_id = arguments.get("job_id")
            if not job_id:
                raise ValueError("job_id is required")
            return await self._close_interactive_session(job_id)
        
        elif name == "cleanup_files":
            path = arguments.get("path")
            location = arguments.get("location")
            recursive = arguments.get("recursive", False)
            confirm = arguments.get("confirm", False)
            if not path or not location:
                raise ValueError("path and location are required")
            return await self._cleanup_files(path, location, recursive, confirm)
        
        elif name == "cleanup_folder":
            folder_path = arguments.get("folder_path")
            location = arguments.get("location")
            confirm = arguments.get("confirm", False)
            if not folder_path or not location:
                raise ValueError("folder_path and location are required")
            return await self._cleanup_folder(folder_path, location, confirm)
        
        elif name == "write_organized_file":
            investigation_id = arguments.get("investigation_id")
            content = arguments.get("content")
            filename = arguments.get("filename")
            category = arguments.get("category")
            subdirectory = arguments.get("subdirectory")
            overwrite = arguments.get("overwrite", False)
            if not investigation_id or not content or not filename or not category:
                raise ValueError("investigation_id, content, filename, and category are required")
            return await self._write_organized_file(investigation_id, content, filename, category, subdirectory, overwrite)
        
        elif name == "lessons_learned":
            action = arguments.get("action")
            if not action:
                raise ValueError("action is required")

            # Extract all parameters
            params = {
                "content": arguments.get("content"),
                "category": arguments.get("category"),
                "tags": arguments.get("tags"),
                "query": arguments.get("query"),
                "entry_id": arguments.get("entry_id"),
                "investigation_id": arguments.get("investigation_id"),
                "job_ids": arguments.get("job_ids"),
                "priority": arguments.get("priority", "info"),
                "format": arguments.get("format", "json"),
            }

            # Validate required params based on action
            if action == "update" and not params["content"]:
                raise ValueError("content is required for update action")
            if action == "search" and not params["query"]:
                raise ValueError("query is required for search action")
            if action == "delete" and not params["entry_id"]:
                raise ValueError("entry_id is required for delete action")

            return await self._lessons_learned(action, **params)
        
        elif name == "get_job_status":
            job_id = arguments.get("job_id")
            include_logs = arguments.get("include_logs", True)
            log_lines = arguments.get("log_lines", 20)
            if not job_id:
                raise ValueError("job_id is required")
            return await self._get_job_status(job_id, include_logs, log_lines)
        
        elif name == "get_job_logs":
            job_id = arguments.get("job_id")
            tail = arguments.get("tail")
            wait_for_completion = arguments.get("wait_for_completion", False)
            poll_interval = arguments.get("poll_interval", 30)
            timeout_seconds = arguments.get("timeout_seconds", 3600)
            if not job_id:
                raise ValueError("job_id is required")
            return await self._get_job_logs(job_id, tail, wait_for_completion, poll_interval, timeout_seconds)
        
        elif name == "get_job_results":
            job_id = arguments.get("job_id")
            investigation_id = arguments.get("investigation_id")
            if not job_id:
                raise ValueError("job_id is required")
            if not investigation_id:
                raise ValueError("investigation_id is required")
            return await self._get_job_results(job_id, investigation_id)
        
        elif name == "list_nodepools":
            return await self._list_nodepools()
        
        else:
            raise ValueError(f"Unknown tool: {name}")

    async def _list_local_agents(self) -> Dict[str, Any]:
        """List all available agents from the catalog.

        Note: Agent selection is now session-scoped in the web UI.
        This MCP endpoint lists available agents but doesn't track which is "current".
        """
        if not self.agent_manager:
            return {
                "agents": {
                    "tool_agents": [],
                    "workflow_agents": [],
                    "knowledge_base_agents": []
                },
                "total_count": 0,
                "error": "Agent manager not initialized"
            }

        try:
            tool_agents = list(self.agent_manager.agents.keys())
            entry_agents = list(self.agent_manager.workflow_agents.keys())
            kb_agents = list(self.agent_manager.kb_agents.keys())

            return {
                "agents": {
                    "tool_agents": tool_agents,
                    "workflow_agents": entry_agents,
                    "knowledge_base_agents": kb_agents
                },
                "total_count": len(tool_agents) + len(entry_agents) + len(kb_agents),
                "note": "Agent selection is session-scoped. Use switch_agent to select an agent for your context."
            }
        except Exception as e:
            logger.error(f"Error in _list_local_agents: {e}")
            return {
                "agents": {
                    "tool_agents": [],
                    "workflow_agents": [],
                    "knowledge_base_agents": []
                },
                "total_count": 0,
                "error": str(e).encode('ascii', 'ignore').decode('ascii')
            }

    async def _get_agent_config(self, agent_name: str) -> Dict[str, Any]:
        """Get configuration for a specific agent - checks local catalog first, then queries published agents"""
        
        # Try local catalog first
        if self.agent_manager:
            try:
                agent_info = None
                agent_type = None
                
                if agent_name in self.agent_manager.agents:
                    agent_info = self.agent_manager.agents[agent_name]
                    agent_type = "tool_agent"
                elif agent_name in self.agent_manager.workflow_agents:
                    agent_info = self.agent_manager.workflow_agents[agent_name]
                    agent_type = "workflow_agent"
                elif agent_name in self.agent_manager.kb_agents:
                    agent_info = self.agent_manager.kb_agents[agent_name]
                    agent_type = "knowledge_base_agent"
                
                if agent_info:
                    return {
                        "source": "local_catalog",
                        "agent_name": agent_name,
                        "type": agent_type,
                        "config": agent_info
                    }
            except Exception as local_e:
                logger.debug(f"Local catalog check failed: {local_e}")
        
        # If not found in local catalog, try published agents
        try:
            logger.info(f"Agent '{agent_name}' not found in local catalog, querying published agents...")
            published_result = await self._get_published_agent_usage(agent_name)
            
            if published_result.get('success'):
                return {
                    "source": "published_agent",
                    "agent_name": agent_name,
                    "type": "published",
                    "config": published_result.get('agent_details', {}),
                    "note": "This agent is deployed in Azure Discovery. Use submit_job to execute it."
                }
            else:
                return {
                    "error": f"Agent '{agent_name}' not found in local catalog or published agents",
                    "suggestion": "Use list_local_agents to see local catalog, or list_published_agents to see deployed agents"
                }
        except Exception as e:
            return {
                "error": f"Agent '{agent_name}' not found",
                "details": str(e)
            }

    async def _switch_agent(self, agent_name: str) -> Dict[str, Any]:
        """Validate and select an agent for use.

        Note: Agent selection is now session-scoped. This endpoint validates
        that the requested agent exists and returns its info. The caller
        should track which agent they're using in their own context.
        """
        if not self.agent_manager:
            return {"error": "Agent manager not initialized"}

        try:
            # Determine agent type
            agent_type = self.agent_manager.get_agent_type(agent_name)

            if not agent_type:
                return {"error": f"Agent '{agent_name}' not found in catalog"}

            # Map internal type names to friendly names
            type_display = {
                'tool': 'tool_agent',
                'entry': 'workflow_agent',
                'kb': 'knowledge_base_agent'
            }.get(agent_type, agent_type)

            return {
                "success": True,
                "agent_name": agent_name,
                "agent_type": type_display,
                "message": f"Agent '{agent_name}' is available. Use this agent name in subsequent requests."
            }
        except Exception as e:
            return {"error": str(e)}

    async def _get_discovery_config(self) -> Dict[str, Any]:
        """Get current Discovery configuration"""
        if not self.config_manager:
            return {"error": "Config manager not initialized"}

        try:
            config = self.config_manager.load_config()
            
            # Mask sensitive information
            if isinstance(config, dict) and "azure_openai" in config and isinstance(config["azure_openai"], dict):
                if "api_key" in config["azure_openai"]:
                    config["azure_openai"]["api_key"] = "***masked***"
            
            return {
                "config": config,
                "config_file": str(self.config_manager.config_file)
            }
        except Exception as e:
            return {"error": str(e)}

    async def _list_docker_containers(self) -> Dict[str, Any]:
        """List Docker containers"""
        try:
            import docker
            client = docker.from_env()
            containers = client.containers.list(all=True)
            
            container_list = []
            for container in containers:
                # Get port info
                ports = container.attrs.get('NetworkSettings', {}).get('Ports', {})
                port_info = []
                if ports:
                    for internal_port, external_ports in ports.items():
                        if external_ports:
                            for external_port in external_ports:
                                port_info.append(f"{external_port['HostPort']}:{internal_port}")
                
                container_list.append({
                    "id": container.short_id,
                    "name": container.name,
                    "image": container.image.tags[0] if container.image.tags else container.image.short_id,
                    "status": container.status,
                    "ports": ", ".join(port_info)
                })
            
            return {
                "success": True,
                "containers": container_list,
                "total_count": len(container_list)
            }
        except Exception as e:
            return {"error": str(e)}

    async def _upload_agent_catalog(self, catalog_content: str, catalog_name: str) -> Dict[str, Any]:
        """Upload and set agent catalog from content string"""
        try:
            if not HAS_WORKBENCH:
                return {"error": "Workbench components not available"}
            
            import tempfile
            import yaml
            import os
            
            # Validate YAML content
            try:
                yaml.safe_load(catalog_content)
            except yaml.YAMLError as e:
                return {"error": f"Invalid YAML content: {str(e)}"}
            
            # Create temporary file in the server's working directory
            temp_path = f"temp_catalog_{catalog_name}.yaml"
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(catalog_content)
            
            # Initialize agent manager with temporary catalog
            self.agent_manager = StaticAgentManager(temp_path)
            
            # Get updated agent counts
            result = await self._list_local_agents()
            result["message"] = f"Agent catalog uploaded and loaded: {catalog_name}"
            result["catalog_name"] = catalog_name
            result["temp_file"] = temp_path
            
            return result
        except Exception as e:
            return {"error": str(e)}

    async def _upload_discovery_config(self, config_content: str, config_name: str) -> Dict[str, Any]:
        """Upload and set discovery configuration from content string"""
        try:
            if not HAS_WORKBENCH:
                return {"error": "Workbench components not available"}
            
            import json
            import os
            
            # Validate JSON content
            try:
                config_data = json.loads(config_content)
            except json.JSONDecodeError as e:
                return {"error": f"Invalid JSON content: {str(e)}"}
            
            # Create temporary config file in the server's working directory
            temp_path = f"temp_config_{config_name}.json"
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(config_content)
            
            # Note: DiscoveryConfigManager might need to be reinitialized to pick up new config
            # This depends on how it's implemented - may need to modify working directory
            original_cwd = os.getcwd()
            try:
                # Change to temp file directory (if needed)
                temp_dir = os.path.dirname(os.path.abspath(temp_path))
                os.chdir(temp_dir)
                
                # Reinitialize config manager
                self.config_manager = DiscoveryConfigManager()
                
                result = await self._get_discovery_config()
                result["message"] = f"Discovery config uploaded and loaded: {config_name}"
                result["config_name"] = config_name
                result["temp_file"] = temp_path
                
                return result
            finally:
                os.chdir(original_cwd)
                
        except Exception as e:
            return {"error": str(e)}

    async def _set_agent_catalog(self, catalog_path: str) -> Dict[str, Any]:
        """Set and reload agent catalog"""
        try:
            if not HAS_WORKBENCH:
                return {"error": "Workbench components not available"}
            
            # Validate catalog file exists
            import os
            if not os.path.exists(catalog_path):
                return {"error": f"Catalog file not found: {catalog_path}"}
            
            # Reinitialize agent manager with new catalog
            self.agent_manager = StaticAgentManager(catalog_path)
            
            # Get updated agent counts
            result = await self._list_local_agents()
            result["message"] = f"Agent catalog reloaded from: {catalog_path}"
            result["catalog_path"] = catalog_path
            
            return result
        except Exception as e:
            return {"error": str(e)}

    async def _set_discovery_config(self, config_path: str) -> Dict[str, Any]:
        """Set and reload discovery configuration from the specified file path.
        
        This method reloads the workbench by:
        1. Validating the config file exists
        2. Reinitializing the config manager with the new config file path
        3. Loading the configuration from the specified file
        
        Args:
            config_path: Absolute path to the discovery_config.json file
            
        Returns:
            Dict containing the loaded configuration and status message
        """
        try:
            if not HAS_WORKBENCH:
                return {"error": "Workbench components not available"}
            
            # Validate config file exists
            import os
            if not os.path.exists(config_path):
                return {"error": f"Config file not found: {config_path}"}
            
            # Reinitialize config manager with the specified config file path
            # This will reload the workbench with the new configuration
            self.config_manager = DiscoveryConfigManager(config_file=config_path)
            
            result = await self._get_discovery_config()
            result["message"] = f"Discovery config reloaded from: {config_path}"
            result["config_path"] = config_path
            
            return result
        except Exception as e:
            return {"error": str(e)}

    async def _reload_workbench(self, catalog_path: Optional[str] = None, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Reload both agent catalog and discovery configuration"""
        try:
            results = {"operations": [], "message": ""}
            
            # Reload catalog if specified
            if catalog_path:
                catalog_result = await self._set_agent_catalog(catalog_path)
                results["operations"].append({"type": "catalog", "result": catalog_result})
            
            # Reload config if specified
            if config_path:
                config_result = await self._set_discovery_config(config_path)
                results["operations"].append({"type": "config", "result": config_result})
            
            # If neither specified, just reinitialize with current paths
            if not catalog_path and not config_path:
                await self._ensure_initialized()
                agent_result = await self._list_local_agents()
                config_result = await self._get_discovery_config()
                results["operations"].append({"type": "agents", "result": agent_result})
                results["operations"].append({"type": "config", "result": config_result})
            
            results["message"] = "Workbench reloaded successfully"
            return results
        except Exception as e:
            return {"error": str(e)}

    async def _list_profiles(self) -> Dict[str, Any]:
        """List all available configuration profiles"""
        try:
            if not self.config_manager:
                return {"error": "Config manager not initialized"}
            
            profiles = self.config_manager.profile_manager.list_profiles()
            active_profile = self.config_manager.profile_manager.get_active_profile_name()
            
            return {
                "success": True,
                "profiles": profiles,
                "active_profile": active_profile,
                "total_count": len(profiles)
            }
        except Exception as e:
            return {"error": f"Failed to list profiles: {str(e)}"}

    async def _switch_profile(self, profile_name: str) -> Dict[str, Any]:
        """Switch to a different configuration profile"""
        try:
            if not self.config_manager:
                return {"error": "Config manager not initialized"}
            
            # Switch profile (this saves the change to disk)
            result = self.config_manager.profile_manager.switch_profile(profile_name)
            
            if not result.get('success'):
                return result
            
            # Reload ProfileManager from disk to pick up the change
            self.config_manager.profile_manager._load_config()
            
            # Reload DiscoveryConfigManager to load the new active profile
            self.config_manager.load_config()
            
            # Clear cached data since we're switching environments
            self._published_agents_cache = None
            self._published_agents_cache_time = None
            self._published_tools_cache = None
            self._published_tools_cache_time = None
            logger.info(f"Cleared published agents/tools cache after profile switch to {profile_name}")
            
            # Get new Azure config from the switched profile
            azure_config = self.config_manager.get_azure_config()
            
            return {
                "success": True,
                "message": result.get('message'),
                "profile_name": profile_name,
                "azure_config": {
                    "subscription_id": azure_config.get('subscription_id', ''),
                    "resource_group": azure_config.get('resource_group', ''),
                    "location": azure_config.get('location', ''),
                    "acr_name": azure_config.get('acr_name', '')
                }
            }
        except Exception as e:
            return {"error": f"Failed to switch profile: {str(e)}"}

    async def _get_supercomputer_info(self, supercomputer_name: Optional[str] = None) -> Dict[str, Any]:
        """Get comprehensive supercomputer information including nodepools"""
        try:
            # Get Azure configuration
            if not self.config_manager:
                return {"error": "Config manager not initialized"}
            
            azure_config = self.config_manager.get_azure_config()
            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            
            if not subscription_id or not resource_group:
                return {
                    "error": "Azure subscription_id and resource_group must be configured",
                    "config_hint": "Please configure Azure settings in discovery_config.json"
                }
            
            # Get Azure access token
            access_token = await self._get_azure_token()
            if not access_token:
                return {"error": "Failed to obtain Azure access token. Please ensure you are authenticated."}
            
            result = {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "supercomputers": []
            }
            
            # If specific supercomputer requested, get detailed info
            if supercomputer_name:
                detailed_info = await self._get_detailed_supercomputer_info(
                    subscription_id, resource_group, supercomputer_name, access_token
                )
                if "error" in detailed_info:
                    return detailed_info
                result["supercomputers"] = [detailed_info]
                result["requested_supercomputer"] = supercomputer_name
            else:
                # Get all supercomputers
                all_supercomputers = await self._get_all_supercomputers(
                    subscription_id, resource_group, access_token
                )
                if "error" in all_supercomputers:
                    return all_supercomputers
                result["supercomputers"] = all_supercomputers["supercomputers"]
            
            result["total_count"] = len(result["supercomputers"])
            return result
            
        except Exception as e:
            return {"error": f"Failed to get supercomputer info: {str(e)}"}

    async def _validate_agent_definition(self, agent_yaml: Optional[str] = None, 
                                       agent_type: Optional[str] = None, 
                                       file_path: Optional[str] = None) -> Dict[str, Any]:
        """Validate an agent definition YAML against the Discovery schema"""
        try:
            import yaml
            import json
            import jsonschema
            from pathlib import Path
            
            # Get the YAML content
            yaml_content = None
            source_info = ""
            
            if file_path:
                # Read from file
                try:
                    if not os.path.isabs(file_path):
                        # Make relative paths relative to agent-workbench directory
                        workbench_dir = os.path.dirname(os.path.abspath(__file__))
                        file_path = os.path.join(workbench_dir, file_path)
                    
                    with open(file_path, 'r', encoding='utf-8') as f:
                        yaml_content = f.read()
                    source_info = f"file: {file_path}"
                except Exception as e:
                    return {"error": f"Failed to read file {file_path}: {str(e)}"}
            elif agent_yaml:
                # Use provided YAML content
                yaml_content = agent_yaml
                source_info = "provided YAML content"
            else:
                return {"error": "Must provide either agent_yaml content or file_path"}
            
            # Parse YAML
            try:
                agent_data = yaml.safe_load(yaml_content)
            except yaml.YAMLError as e:
                return {
                    "valid": False,
                    "errors": [f"Invalid YAML syntax: {str(e)}"],
                    "source": source_info
                }

            def _find_forbidden_extension_input_names(doc: Any) -> List[str]:
                """Return forbidden names declared under extension.inputs.

                These names are reserved runtime context placeholders and must NOT be declared
                as user-provided inputs in agent definitions.
                """
                forbidden_names = {"nodePoolContext", "dataHandlingContext", "messageId"}
                found = set()

                if not isinstance(doc, dict):
                    return []

                extension_block = doc.get("extension")
                if not isinstance(extension_block, dict):
                    return []

                inputs_block = extension_block.get("inputs")
                if not inputs_block:
                    return []

                # Common shape: list of {name, type, ...}
                if isinstance(inputs_block, list):
                    for item in inputs_block:
                        if isinstance(item, dict):
                            name = item.get("name")
                            if isinstance(name, str) and name in forbidden_names:
                                found.add(name)
                # Tolerate dict-of-inputs too
                elif isinstance(inputs_block, dict):
                    for name in inputs_block.keys():
                        if isinstance(name, str) and name in forbidden_names:
                            found.add(name)

                return sorted(found)
            
            # Determine agent type if not provided
            if not agent_type:
                # Try to infer agent type from content
                if isinstance(agent_data, dict):
                    if "tools" in agent_data or "tool_definition" in agent_data:
                        agent_type = "tool"
                    elif "workflow" in agent_data or "components" in agent_data:
                        agent_type = "entry"
                    elif "knowledge_base" in agent_data or "documents" in agent_data:
                        agent_type = "knowledge_base"
                    else:
                        agent_type = "tool"  # Default assumption
                else:
                    agent_type = "tool"  # Default assumption
            
            # Load the appropriate schema
            workbench_dir = os.path.dirname(os.path.abspath(__file__))
            schema_file = None
            
            if agent_type == "tool":
                schema_file = os.path.join(workbench_dir, "yaml-schemas", "agent_definition_schema.json")
            elif agent_type == "entry":
                schema_file = os.path.join(workbench_dir, "yaml-schemas", "workflow_definition_schema.json")
            elif agent_type == "knowledge_base":
                schema_file = os.path.join(workbench_dir, "yaml-schemas", "agent_definition_schema.json")
            else:
                return {"error": f"Unknown agent type: {agent_type}. Must be 'tool', 'entry', or 'knowledge_base'"}
            
            # Check if schema file exists
            if not os.path.exists(schema_file):
                return {
                    "valid": False,
                    "errors": [f"Schema file not found: {schema_file}"],
                    "warnings": ["Performing basic validation only"],
                    "agent_type": agent_type,
                    "source": source_info
                }
            
            # Load and validate against schema
            try:
                with open(schema_file, 'r', encoding='utf-8') as f:
                    schema_data = json.load(f)
                
                # Validate against schema
                validator = jsonschema.Draft7Validator(schema_data)
                errors = list(validator.iter_errors(agent_data))
                
                validation_errors = []
                for error in errors:
                    error_path = " -> ".join(str(p) for p in error.path) if error.path else "root"
                    validation_errors.append(f"At '{error_path}': {error.message}")
                
                # Perform additional Discovery-specific validations
                warnings = []
                additional_errors = []
                
                # Basic structure checks
                if isinstance(agent_data, dict):
                    # Check for required fields based on agent type
                    # Look for fields both at root level and under 'agent' key
                    agent_info = agent_data.get('agent', agent_data)

                    # Disallow reserved runtime context placeholders as declared inputs
                    # (Only applies to agent definitions, not workflow definitions)
                    if agent_type in ("tool", "knowledge_base"):
                        forbidden = _find_forbidden_extension_input_names(agent_data)
                        if forbidden:
                            forbidden_list = ", ".join(forbidden)
                            additional_errors.append(
                                "Reserved inputs are not allowed in agent definition extension.inputs: "
                                f"{forbidden_list}. Remove them from extension.inputs."
                            )
                    
                    if agent_type == "tool":
                        if "name" not in agent_info and "name" not in agent_data:
                            additional_errors.append("Missing required field 'name'")
                        if "description" not in agent_info and "description" not in agent_data:
                            warnings.append("Missing recommended field 'description'")
                        if ("tools" not in agent_info and "tool_definition" not in agent_info and 
                            "tools" not in agent_data and "tool_definition" not in agent_data):
                            warnings.append("No 'tools' or 'tool_definition' found - may not be a valid tool agent")
                    
                    elif agent_type == "entry":
                        if "name" not in agent_info and "name" not in agent_data:
                            additional_errors.append("Missing required field 'name'")
                        if ("workflow" not in agent_info and "workflow" not in agent_data):
                            warnings.append("No 'workflow' section found - may not be a valid workflow agent")
                    
                    elif agent_type == "knowledge_base":
                        if "name" not in agent_info and "name" not in agent_data:
                            additional_errors.append("Missing required field 'name'")
                        if ("knowledge_base" not in agent_info and "documents" not in agent_info and
                            "knowledge_base" not in agent_data and "documents" not in agent_data):
                            warnings.append("No 'knowledge_base' or 'documents' found - may not be a valid KB agent")
                
                # Combine all errors
                all_errors = validation_errors + additional_errors
                
                is_valid = len(all_errors) == 0
                
                result = {
                    "valid": is_valid,
                    "agent_type": agent_type,
                    "source": source_info,
                    "schema_file": schema_file
                }
                
                if all_errors:
                    result["errors"] = all_errors
                
                if warnings:
                    result["warnings"] = warnings
                
                if is_valid:
                    result["message"] = f"Agent definition is valid for type '{agent_type}'"
                    
                    # Add some helpful information about the agent
                    if isinstance(agent_data, dict):
                        agent_info = agent_data.get('agent', agent_data)
                        if "name" in agent_info:
                            result["agent_name"] = agent_info["name"]
                        elif "name" in agent_data:
                            result["agent_name"] = agent_data["name"]
                        if "description" in agent_info:
                            result["agent_description"] = agent_info["description"]
                        elif "description" in agent_data:
                            result["agent_description"] = agent_data["description"]
                else:
                    result["message"] = f" X Agent definition has {len(all_errors)} error(s)"
                
                return result
                
            except json.JSONDecodeError as e:
                return {
                    "valid": False,
                    "errors": [f"Invalid schema file JSON: {str(e)}"],
                    "agent_type": agent_type,
                    "source": source_info
                }
            except Exception as e:
                return {
                    "valid": False,
                    "errors": [f"Schema validation failed: {str(e)}"],
                    "agent_type": agent_type,
                    "source": source_info
                }
                
        except ImportError as e:
            missing_module = str(e).split("'")[1] if "'" in str(e) else "unknown"
            return {"error": f"Missing required module for validation: {missing_module}. Please install it with: pip install {missing_module}"}
        except Exception as e:
            logger.error(f"Validation error: {e}")
            logger.debug(traceback.format_exc())
            return {"error": f"Failed to validate agent definition: {str(e)}"}
    
    async def _generate_mermaid_diagram(self, yaml_content: Optional[str] = None, 
                                       workflow_name: Optional[str] = None,
                                       file_path: Optional[str] = None) -> Dict[str, Any]:
        """Generate a Mermaid diagram from workflow YAML using LLM
        
        Args:
            yaml_content: YAML content as string
            workflow_name: Name of the workflow (for auto-saving)
            file_path: Path to YAML file (alternative to yaml_content)
        
        Returns:
            Dict with success status, diagram text, and optional file path
        """
        try:
            import requests
            
            # Get YAML content from file if path provided
            if file_path and not yaml_content:
                if not os.path.exists(file_path):
                    return {
                        "success": False,
                        "error": f"File not found: {file_path}"
                    }
                with open(file_path, 'r', encoding='utf-8') as f:
                    yaml_content = f.read()
                # Extract workflow name from file if not provided
                if not workflow_name:
                    workflow_name = os.path.splitext(os.path.basename(file_path))[0]
                    # Remove common suffixes
                    workflow_name = workflow_name.replace('-wfl', '').replace('_wfl', '')
            
            if not yaml_content:
                return {
                    "success": False,
                    "error": "Missing input. Provide either 'yaml_content' or 'file_path'."
                }
            
            # Get Azure OpenAI configuration
            if not self.config_manager:
                return {
                    "success": False,
                    "error": "Config manager not initialized. Cannot access Azure OpenAI settings."
                }
            
            try:
                azure_openai_config = self.config_manager.get_azure_openai_config()
                endpoint = azure_openai_config.get('endpoint_url', '')
                deployment = azure_openai_config.get('deployment_name', 'gpt-4o')
                api_key = azure_openai_config.get('api_key', '')
                api_version = azure_openai_config.get('api_version', '2024-12-01-preview')
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to get Azure OpenAI config: {str(e)}"
                }
            
            if not endpoint:
                return {
                    "success": False,
                    "error": "Azure OpenAI endpoint not configured. Please set endpoint_url in discovery_config.json."
                }
            
            # Load mermaid prompt template
            prompts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts')
            mermaid_prompt_path = os.path.join(prompts_dir, 'mermaid_system.txt')
            
            # Compose prompt
            escaped_yaml = yaml_content.replace("'", "''")
            
            if os.path.exists(mermaid_prompt_path):
                try:
                    with open(mermaid_prompt_path, 'r', encoding='utf-8') as f:
                        template = f.read()
                    prompt = template.replace('{yaml}', escaped_yaml)
                except Exception as e:
                    logger.warning(f"Failed to load mermaid prompt template: {e}, using fallback")
                    prompt = self._get_fallback_mermaid_prompt(escaped_yaml)
            else:
                logger.info("Mermaid prompt template not found, using fallback")
                prompt = self._get_fallback_mermaid_prompt(escaped_yaml)
            
            # Build Azure OpenAI request
            url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
            
            headers = {'Content-Type': 'application/json'}
            
            # Try API key first, fall back to Azure AD
            if api_key:
                headers['api-key'] = api_key
            else:
                # Try to get Azure AD token
                token = await self._get_azure_openai_token()
                if not token:
                    return {
                        "success": False,
                        "error": "Azure OpenAI authentication failed. Please set api_key or configure Azure AD credentials."
                    }
                headers['Authorization'] = f"Bearer {token}"
            
            payload = {
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You generate Mermaid diagrams and must return ONLY the final Mermaid text.'
                    },
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0,
                'top_p': 0,
                'max_tokens': 2000
            }
            
            # Call Azure OpenAI
            logger.info(f"Calling Azure OpenAI to generate Mermaid diagram...")
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"LLM request failed: {response.status_code} {response.text[:500]}"
                }
            
            data = response.json()
            
            # Extract diagram content
            diagram = None
            try:
                if data.get('choices'):
                    diagram = data['choices'][0].get('message', {}).get('content', '')
            except Exception as e:
                logger.error(f"Failed to extract diagram from response: {e}")
            
            if not diagram:
                return {
                    "success": False,
                    "error": "No diagram content returned by LLM."
                }
            
            # Clean up the diagram
            diagram = self._clean_mermaid_diagram(diagram)
            
            # Auto-save if workflow name provided
            saved_to = None
            if workflow_name and workflow_name.strip():
                saved_to = self._save_mermaid_diagram(diagram, workflow_name)
            
            result = {
                "success": True,
                "diagram": diagram,
                "message": "Mermaid diagram generated successfully"
            }
            
            if saved_to:
                result["saved_to"] = saved_to
                result["message"] += f" and saved to {saved_to}"
            
            return result
            
        except ImportError as e:
            return {
                "success": False,
                "error": f"Missing required module: {str(e)}. Install with: pip install requests"
            }
        except Exception as e:
            logger.error(f"Mermaid generation error: {e}")
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "error": f"Failed to generate mermaid diagram: {str(e)}"
            }
    
    def _get_fallback_mermaid_prompt(self, escaped_yaml: str) -> str:
        """Get fallback mermaid prompt when template file is not available"""
        return (
            "Generate a Mermaid sequence diagram from the provided workflow YAML. Return ONLY Mermaid text.\\n\\n"
            "Requirements: sequenceDiagram; autonumber; participants (User + one per agent, use aliases when needed); "
            "alt/else per routing events; colored rect blocks; balanced activate/deactivate; strict lines only (no prose).\\n\\n"
            f"YAML:\\n'{escaped_yaml}'\\n"
        )
    
    async def _generate_mermaid_svg(self, mermaid_text: Optional[str] = None,
                                   output_file: Optional[str] = None,
                                   file_path: Optional[str] = None) -> Dict[str, Any]:
        """Generate SVG from Mermaid diagram text
        
        Args:
            mermaid_text: Mermaid diagram text
            output_file: Output file path for SVG
            file_path: Path to file containing Mermaid text (alternative to mermaid_text)
            
        Returns:
            Dict with success status, SVG content, and file path
        """
        try:
            import requests
            import base64
            from datetime import datetime
            
            # Get Mermaid text from file if path provided
            if file_path and not mermaid_text:
                if not os.path.exists(file_path):
                    return {
                        "success": False,
                        "error": f"File not found: {file_path}"
                    }
                with open(file_path, 'r', encoding='utf-8') as f:
                    mermaid_text = f.read()
                    
                # Clean up if it's a markdown file
                if file_path.endswith('.md'):
                    # Extract mermaid code block
                    if '```mermaid' in mermaid_text:
                        parts = mermaid_text.split('```mermaid')
                        if len(parts) > 1:
                            mermaid_text = parts[1].split('```')[0].strip()
            
            if not mermaid_text:
                return {
                    "success": False,
                    "error": "Missing input. Provide either 'mermaid_text' or 'file_path'."
                }
            
            # Clean the Mermaid text
            mermaid_text = self._clean_mermaid_diagram(mermaid_text)
            
            # Use Mermaid.ink service to render SVG
            # This is a free public service that converts Mermaid to SVG
            logger.info("Converting Mermaid diagram to SVG...")
            
            # Encode the Mermaid text to base64 for the URL
            mermaid_bytes = mermaid_text.encode('utf-8')
            mermaid_b64 = base64.urlsafe_b64encode(mermaid_bytes).decode('ascii')
            
            # Use the Mermaid.ink API
            svg_url = f"https://mermaid.ink/svg/{mermaid_b64}"
            
            logger.info(f"Fetching SVG from Mermaid.ink service...")
            response = requests.get(svg_url, timeout=30)
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to generate SVG: HTTP {response.status_code}"
                }
            
            svg_content = response.text
            
            # Determine output file path
            if not output_file:
                # Generate default filename with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = f"mermaid_diagram_{timestamp}.svg"
            
            # Ensure .svg extension
            if not output_file.endswith('.svg'):
                output_file += '.svg'
            
            # Make path absolute if relative
            if not os.path.isabs(output_file):
                # Save to current working directory or samples directory if available
                if file_path:
                    # Save next to the source file
                    output_file = os.path.join(os.path.dirname(os.path.abspath(file_path)), output_file)
                else:
                    output_file = os.path.abspath(output_file)
            
            # Save SVG file
            try:
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(svg_content)
                logger.info(f"SVG saved to: {output_file}")
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to save SVG file: {str(e)}"
                }
            
            return {
                "success": True,
                "svg_file": output_file,
                "svg_size_bytes": len(svg_content),
                "message": f"SVG generated successfully and saved to {output_file}"
            }
            
        except ImportError as e:
            return {
                "success": False,
                "error": f"Missing required module: {str(e)}. Install with: pip install requests"
            }
        except Exception as e:
            logger.error(f"SVG generation error: {e}")
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "error": f"Failed to generate SVG: {str(e)}"
            }
    
    def _clean_mermaid_diagram(self, diagram: str) -> str:
        """Clean up Mermaid diagram by removing code fences and fixing common issues"""
        content = diagram.strip()
        
        # Remove code fences if present
        if content.startswith('```') and content.endswith('```'):
            first_nl = content.find('\\n')
            last_fence = content.rfind('```')
            if first_nl != -1 and last_fence != -1 and last_fence > first_nl:
                content = content[first_nl+1:last_fence].strip()
        
        # Normalize line endings
        content = content.replace('\\r\\n', '\\n').replace('\\r', '\\n')
        
        # Ensure init fence is present
        mermaid_init_fence = "%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#4a90e2'}}}%%"
        head = content.lstrip()
        if not head.startswith('%%{init:'):
            content = f"{mermaid_init_fence}\\n" + content
        
        # Fix "Endend" concatenation issue (common LLM error)
        try:
            import re
            content = re.sub(r'(^[^\\n]*?:[^\\n]*?)\\b[Ee]ndend(\\s*$)', r'\\1End\\nend\\2', content, flags=re.MULTILINE)
        except Exception:
            pass
        
        return content
    
    def _save_mermaid_diagram(self, diagram: str, workflow_name: str) -> Optional[str]:
        """Save mermaid diagram to file in the workflow directory"""
        try:
            # Get workflow agents directory from config
            if not self.config_manager:
                logger.warning("Config manager not available for saving diagram")
                return None
            
            directories = self.config_manager.get_directories_config()
            workflow_agents_dir = directories.get('workflow_agents_dir', '../../6-solutions/tools-and-models/')
            workflow_agents_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), workflow_agents_dir)
            
            if not os.path.exists(workflow_agents_base):
                logger.warning(f"Entry agents directory not found: {workflow_agents_base}")
                return None
            
            # Find workflow folder
            workflow_folder = None
            for folder_name in os.listdir(workflow_agents_base):
                folder_path = os.path.join(workflow_agents_base, folder_name)
                if os.path.isdir(folder_path):
                    workflow_file = os.path.join(folder_path, f"{workflow_name.lower()}-wfl.yaml")
                    if os.path.exists(workflow_file):
                        workflow_folder = folder_path
                        break
            
            if not workflow_folder:
                logger.info(f"Workflow folder not found for '{workflow_name}', skipping auto-save")
                return None
            
            # Save diagram
            diagram_filename = f"{workflow_name.lower()}-diagram.mmd"
            diagram_path = os.path.join(workflow_folder, diagram_filename)
            
            with open(diagram_path, 'w', encoding='utf-8') as f:
                f.write(diagram)
            
            logger.info(f" Saved Mermaid diagram to: {diagram_path}")
            return diagram_path
            
        except Exception as e:
            logger.error(f"Failed to save mermaid diagram: {e}")
            return None
    
    async def _get_azure_openai_token(self) -> Optional[str]:
        """Get Azure OpenAI token using DefaultAzureCredential"""
        try:
            from azure.identity import DefaultAzureCredential
            
            credential = DefaultAzureCredential()
            token = credential.get_token("https://cognitiveservices.azure.com/.default")
            return token.token
        except ImportError:
            logger.warning("azure-identity not available")
            return None
        except Exception as e:
            logger.error(f"Failed to get Azure OpenAI token: {e}")
            return None
    
    async def _get_azure_token(self) -> Optional[str]:
        """Get Azure management token using tenant-aware authentication"""
        try:
            if not self.config_manager:
                logger.warning("Config manager not initialized")
                return None
            
            azure_config = self.config_manager.get_azure_config()
            if not azure_config:
                logger.warning("Azure config not available")
                return None
            
            tenant_id = azure_config.get('tenant_id', '').strip()
            if not tenant_id:
                logger.warning("tenant_id not configured")
                return None
            
            server_traces = []
            token = self._get_azure_management_token(tenant_id, server_traces)
            
            if not token:
                logger.warning("Failed to acquire Azure token")
                return None
            
            return token
        except Exception as e:
            logger.error(f"Failed to get Azure token: {e}")
            return None
    
    async def _get_all_supercomputers(self, subscription_id: str, resource_group: str, access_token: str) -> Dict[str, Any]:
        """Get all supercomputers from Azure API"""
        try:
            import requests
            
            url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/supercomputers"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            params = {'api-version': '2025-07-01-preview'}
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                supercomputers = data.get('value', [])
                
                # Transform to more usable format
                supercomputer_list = []
                for sc in supercomputers:
                    properties = sc.get('properties', {})
                    supercomputer_info = {
                        'name': sc.get('name', ''),
                        'id': sc.get('id', ''),
                        'location': sc.get('location', ''),
                        'type': sc.get('type', ''),
                        'provisioningState': properties.get('provisioningState', ''),
                        'status': properties.get('status', ''),
                        'resourceGroup': resource_group
                    }
                    supercomputer_list.append(supercomputer_info)
                
                return {"supercomputers": supercomputer_list}
            else:
                return {"error": f"Azure API returned {response.status_code}: {response.text}"}
                
        except Exception as e:
            return {"error": f"Failed to fetch supercomputers: {str(e)}"}
    
    async def _get_detailed_supercomputer_info(self, subscription_id: str, resource_group: str, 
                                              supercomputer_name: str, access_token: str) -> Dict[str, Any]:
        """Get detailed information for a specific supercomputer including nodepools"""
        try:
            import requests
            
            # Get supercomputer details
            sc_url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/supercomputers/{supercomputer_name}"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            params = {'api-version': '2025-07-01-preview'}
            
            sc_response = requests.get(sc_url, headers=headers, params=params, timeout=30)
            
            if sc_response.status_code != 200:
                return {"error": f"Supercomputer '{supercomputer_name}' not found: {sc_response.status_code} {sc_response.text}"}
            
            sc_data = sc_response.json()
            properties = sc_data.get('properties', {})
            
            supercomputer_info = {
                'name': sc_data.get('name', ''),
                'id': sc_data.get('id', ''),
                'location': sc_data.get('location', ''),
                'type': sc_data.get('type', ''),
                'provisioningState': properties.get('provisioningState', ''),
                'status': properties.get('status', ''),
                'resourceGroup': resource_group,
                'nodepools': []
            }
            
            # Get nodepools for this supercomputer
            np_url = f"{sc_url}/nodepools"
            np_response = requests.get(np_url, headers=headers, params=params, timeout=30)
            
            if np_response.status_code == 200:
                np_data = np_response.json()
                nodepools = np_data.get('value', [])
                
                for np in nodepools:
                    np_properties = np.get('properties', {})
                    nodepool_info = {
                        'name': np.get('name', ''),
                        'id': np.get('id', ''),
                        'vmSize': np_properties.get('vmSize', 'Unknown'),
                        'maxNodes': np_properties.get('maxNodeCount', 0),
                        'minNodes': np_properties.get('minNodeCount', 0),
                        'currentNodes': np_properties.get('currentNodeCount', 0),
                        'provisioningState': np_properties.get('provisioningState', ''),
                        'location': np.get('location', ''),
                        'type': np.get('type', ''),
                        'subnetId': np_properties.get('subnetId', '')
                    }
                    supercomputer_info['nodepools'].append(nodepool_info)
                
                supercomputer_info['nodepool_count'] = len(supercomputer_info['nodepools'])
            else:
                supercomputer_info['nodepool_error'] = f"Failed to fetch nodepools: {np_response.status_code}"
            
            return supercomputer_info
            
        except Exception as e:
            return {"error": f"Failed to get detailed supercomputer info: {str(e)}"}

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle incoming JSON-RPC request"""
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params", {})
        
        if method == "initialize":
            return self.handle_initialize(request_id)
        elif method == "initialized":
            self.handle_initialized()
            return None  # No response for notification
        elif method == "tools/list":
            return self.handle_list_tools(request_id)
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            # This needs to be handled in async context
            return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}}
        else:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

    async def _list_published_agents_and_tools(self, name_filter: Optional[str] = None) -> Dict[str, Any]:
        """List agents with their attached tools from Azure Discovery workspace
        
        Args:
            name_filter: Optional name filter for agents
            
        Returns:
            Dict with agents list including their attached tools information
        """
        try:
            import time
            
            # Check cache if querying all agents (name_filter is None)
            if not name_filter:
                current_time = time.time()
                if (self._published_agents_cache is not None and 
                    self._published_agents_cache_time is not None and
                    (current_time - self._published_agents_cache_time) < self._cache_ttl_seconds):
                    logger.info("Using cached published agents list")
                    cached_result = self._published_agents_cache.copy()
                    cached_result['from_cache'] = True
                    cached_result['cache_age_seconds'] = int(current_time - self._published_agents_cache_time)
                    return cached_result
            
            # Get Azure configuration
            config = self.config_manager.load_config()
            if not config:
                return {"success": False, "error": "Config manager not initialized"}
            
            azure_config = config.get('azure', {})
            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            tenant_id = azure_config.get('tenant_id', '').strip()
            
            if not subscription_id or not resource_group:
                return {
                    "success": False,
                    "error": "Azure subscription_id and resource_group must be configured",
                    "config_hint": "Please configure Azure settings in discovery_config.json"
                }
            
            # Import discovery publisher
            try:
                from discovery_publisher import AzureDiscoveryClient
            except ImportError:
                return {"success": False, "error": "Discovery publisher module not available"}
            
            # Initialize client and list agents
            azure_client = AzureDiscoveryClient()
            
            logger.info(f"Listing published Discovery agents with tools in {resource_group}...")
            
            # Use name_filter as pattern (or "*" for all)
            pattern = name_filter if name_filter else "*"
            result = azure_client.list_discovery_agents(subscription_id, resource_group, pattern, tenant_id=tenant_id)
            
            if not result.get('exists'):
                return {
                    "success": True,
                    "agents": [],
                    "summary": {"total_agents": 0, "total_tools_attached": 0},
                    "message": result.get('message', 'No agents found'),
                    "subscription_id": subscription_id,
                    "resource_group": resource_group
                }
            
            # Extract agent details including tools from properties
            agents_data = result.get('all_agents', [])
            agents_list = []
            
            # Filter suffixes - exclude agents ending with these
            excluded_suffixes = ('-pln', '-rtr', '-sum', '-wfl')
            # Exact names to exclude
            excluded_names = {'ChemistryAgent'}
            
            total_tools_attached = 0
            
            for agent_info in agents_data:
                # Handle both formats: structured (with agent_data) and raw Azure objects
                if 'agent_data' in agent_info:
                    agent_data = agent_info.get('agent_data', {})
                else:
                    agent_data = agent_info
                
                # Extract agent name early to check exclusion
                agent_name_extracted = agent_info.get('agent_name') or agent_data.get('name', 'unknown')
                
                # Skip agents with excluded suffixes or exact names
                if agent_name_extracted.lower().endswith(excluded_suffixes) or agent_name_extracted in excluded_names:
                    logger.debug(f"Filtering out excluded agent: {agent_name_extracted}")
                    continue
                
                properties = agent_data.get('properties') or {}
                
                # Get provisioning state - only include Succeeded agents
                if 'provisioning_state' in agent_info:
                    provisioning_state = agent_info['provisioning_state']
                elif properties and 'provisioningState' in properties:
                    provisioning_state = properties['provisioningState']
                elif 'provisioningState' in agent_data:
                    provisioning_state = agent_data['provisioningState']
                else:
                    provisioning_state = 'unknown'
                
                # Skip agents that are not in Succeeded state
                if provisioning_state != 'Succeeded':
                    logger.debug(f"Filtering out agent '{agent_name_extracted}' with provisioning state: {provisioning_state}")
                    continue
                
                # Extract tools from properties.tools (NOT from definitionContent)
                # This is the authoritative source for agent tool attachments
                attached_tools = []
                tools_from_properties = properties.get('tools', [])
                
                if isinstance(tools_from_properties, list):
                    for tool in tools_from_properties:
                        if isinstance(tool, dict):
                            tool_name = tool.get('name', 'unknown')
                            tool_id = tool.get('toolId', '')
                            
                            # Fetch tool details to get infra and code_environments
                            infra_nodes = []
                            code_environments = []
                            
                            if tool_id:
                                try:
                                    logger.debug(f"Fetching details for tool '{tool_name}' ({tool_id})")
                                    # Get tool details from Azure
                                    tool_response = azure_client.get_discovery_tool_details(tool_id, tenant_id=tenant_id)
                                    
                                    if tool_response:
                                        # Unwrap the response - API returns {success, data: {...}}
                                        tool_details = tool_response.get('data', tool_response)
                                        tool_props = tool_details.get('properties', {})
                                        tool_def_content = tool_props.get('definitionContent', {})
                                        
                                        # Extract infra and code_environments from tool's definitionContent
                                        if isinstance(tool_def_content, dict):
                                            infra_nodes = tool_def_content.get('infra', [])
                                            code_environments = tool_def_content.get('code_environments', [])
                                            logger.debug(f"Tool '{tool_name}': found {len(infra_nodes) if isinstance(infra_nodes, list) else 0} infra nodes, {len(code_environments) if isinstance(code_environments, list) else 0} code environments")
                                    else:
                                        logger.warning(f"Could not fetch details for tool '{tool_name}': get_discovery_tool_details returned None")
                                except Exception as tool_error:
                                    logger.warning(f"Error fetching details for tool '{tool_name}': {tool_error}")
                            
                            tool_info = {
                                'name': tool_name,
                                'tool_id': tool_id,
                                'infra': infra_nodes if isinstance(infra_nodes, list) else [],
                                'code_environments': code_environments if isinstance(code_environments, list) else []
                            }
                            attached_tools.append(tool_info)
                            total_tools_attached += 1
                
                # Extract agent metadata - removed location, model_name, provisioning_state
                agent_name = agent_name_extracted
                resource_id = agent_info.get('resource_id') or agent_data.get('id', '')
                
                agent_entry = {
                    'name': agent_name,
                    'resource_id': resource_id,
                    'attached_tools': attached_tools,
                    'tools_count': len(attached_tools)
                }
                
                agents_list.append(agent_entry)
            
            result_data = {
                "success": True,
                "agents": agents_list,
                "summary": {
                    "total_agents": len(agents_list),
                    "total_tools_attached": total_tools_attached,
                    "agents_with_tools": sum(1 for a in agents_list if a['tools_count'] > 0)
                },
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "message": f"Found {len(agents_list)} agent(s) with {total_tools_attached} tool(s) attached"
            }
            
            # Cache result if querying all agents
            if not name_filter:
                import time
                self._published_agents_cache = result_data.copy()
                self._published_agents_cache_time = time.time()
                logger.info(f"Cached {len(agents_list)} published agents with tools for {self._cache_ttl_seconds}s")
            
            return result_data
            
        except Exception as e:
            logger.error(f"Failed to list published agents and tools: {e}")
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "error": f"Failed to list published agents and tools: {str(e)}"
            }
    
    async def _get_published_agent_usage(self, agent_name: str) -> Dict[str, Any]:
        """Get usage instructions for a specific Discovery agent
        
        Retrieves the agent's instructions field which explains how to use it.
        This is the most important information for writing scripts that use the agent.
        
        Args:
            agent_name: Name of the agent to retrieve instructions for
            
        Returns:
            Dict with agent instructions
        """
        try:
            # Get Azure configuration
            config = self.config_manager.load_config()
            if not config:
                return {"error": "Config manager not initialized"}
            
            azure_config = config.get('azure', {})
            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            tenant_id = azure_config.get('tenant_id', '').strip()
            
            if not subscription_id or not resource_group:
                return {
                    "error": "Azure subscription_id and resource_group must be configured",
                    "config_hint": "Please configure Azure settings in discovery_config.json"
                }
            
            # Import discovery publisher
            try:
                from discovery_publisher import AzureDiscoveryClient
            except ImportError as e:
                return {"error": f"Discovery publisher module not available: {str(e)}"}
            
            logger.info(f"Getting usage instructions for agent '{agent_name}'...")
            
            # Initialize client and get agent details
            azure_client = AzureDiscoveryClient()
            result = azure_client.get_discovery_agent_details(subscription_id, resource_group, agent_name, tenant_id=tenant_id)
            
            if not result.get('success'):
                error_type = result.get('error', '')
                if error_type == 'resource_not_found':
                    return {
                        "success": False,
                        "error": f"Agent '{agent_name}' not found in resource group '{resource_group}'",
                        "agent_name": agent_name,
                        "resource_group": resource_group
                    }
                else:
                    return {
                        "success": False,
                        "error": result.get('message') or result.get('error', 'Failed to retrieve agent')
                    }
            
            # Get agent data - the result from get_discovery_agent_details wraps the actual data
            # The structure is: {'success': True, 'agent_data': {'success': True, 'data': {...actual agent...}}}
            result_data = result.get('agent_data')
            if not result_data:
                return {
                    "success": False,
                    "error": "No agent data returned from API",
                    "debug_info": {
                        "result_keys": list(result.keys()) if isinstance(result, dict) else "not a dict",
                        "result": str(result)[:500]
                    }
                }
            
            # The actual agent data is nested inside 'data' key
            agent_data = result_data.get('data') if isinstance(result_data, dict) else result_data
            if not agent_data:
                return {
                    "success": False,
                    "error": "No agent data in response",
                    "debug_info": {
                        "result_data_keys": list(result_data.keys()) if isinstance(result_data, dict) else "not a dict"
                    }
                }
            
            # Log the raw agent_data for debugging
            logger.info(f"Retrieved agent data keys: {list(agent_data.keys()) if isinstance(agent_data, dict) else 'not a dict'}")
            
            # Extract key information
            properties = agent_data.get('properties', {})
            definition_content = properties.get('definitionContent', {})
            
            # Debug logging
            logger.debug(f"properties keys: {list(properties.keys()) if isinstance(properties, dict) else 'not a dict'}")
            logger.debug(f"definition_content keys: {list(definition_content.keys()) if isinstance(definition_content, dict) else 'not a dict'}")
            
            # Debug: Log what we have
            logger.debug(f"agent_data type: {type(agent_data)}")
            logger.debug(f"agent_data keys: {list(agent_data.keys()) if isinstance(agent_data, dict) else 'not a dict'}")
            logger.debug(f"properties type: {type(properties)}")
            logger.debug(f"properties keys: {list(properties.keys()) if isinstance(properties, dict) else 'not a dict'}")
            logger.debug(f"definition_content type: {type(definition_content)}")
            logger.debug(f"definition_content: {definition_content if len(str(definition_content)) < 500 else str(definition_content)[:500]}")
            
            # The agent definition is nested under 'agent' key in definitionContent
            # Based on the example: properties.definitionContent.agent.instructions
            if 'agent' in definition_content and isinstance(definition_content['agent'], dict):
                agent_def = definition_content['agent']
            else:
                agent_def = definition_content
            
            # Extract instructions - this is the most important field
            # Try multiple possible locations for instructions
            instructions = (
                agent_def.get('instructions') or 
                agent_def.get('Instructions') or
                definition_content.get('instructions') or
                definition_content.get('Instructions') or
                properties.get('instructions') or
                properties.get('Instructions') or
                ''
            )
            
            if not instructions:
                # Return debug information to understand the structure
                return {
                    "success": False,
                    "error": f"No instructions found for agent '{agent_name}'",
                    "agent_name": agent_name,
                    "debug_info": {
                        "agent_def_keys": list(agent_def.keys()) if isinstance(agent_def, dict) else "not a dict",
                        "properties_keys": list(properties.keys()) if isinstance(properties, dict) else "not a dict",
                        "definition_content_keys": list(definition_content.keys()) if isinstance(definition_content, dict) else "not a dict",
                        "has_nested_agent": 'agent' in definition_content,
                        "agent_data_keys": list(agent_data.keys()) if isinstance(agent_data, dict) else "not a dict",
                        "agent_data_sample": str(agent_data)[:1000] if agent_data else "empty"
                    }
                }
            
            return {
                "success": True,
                "agent_name": agent_name,
                "instructions": instructions
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Request timed out while retrieving agent details"
            }
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Failed to parse agent data: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Failed to get agent details: {e}")
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "error": f"Failed to get agent details: {str(e)}"
            }
    
    async def _list_nodepools(self) -> Dict[str, Any]:
        """List all available nodepools with their key characteristics
        
        Retrieves detailed information about all nodepools in the Discovery supercomputer,
        including compute resources, pool types, and infrastructure specifications.
        Use this to compare nodepool capabilities with tool requirements to select
        the best nodepool for your jobs via the nodepool_name parameter in submit_job.
            
        Returns:
            Dict with list of nodepools and their characteristics including VM specifications
        """
        try:
            # Get Azure configuration
            config = self.config_manager.load_config()
            if not config:
                return {"success": False, "error": "Config manager not initialized"}
            
            azure_config = config.get('azure', {})
            azure_compute_config = config.get('azure_compute', {})
            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            supercomputer_name = azure_compute_config.get('discovery_supercomputer', 'discoverySupercomputer1').strip()
            tenant_id = azure_config.get('tenant_id', '').strip()
            # Prefer region defined under azure_compute (used for supercomputer resources),
            # then fall back to top-level azure.location, then default to 'swedencentral'.
            location = azure_config.get('location')
            location = str(location).strip()
            
            if not subscription_id or not resource_group or not tenant_id:
                return {
                    "success": False,
                    "error": "Azure subscription_id, resource_group, and tenant_id must be configured",
                    "config_hint": "Please configure Azure settings in discovery_config.json"
                }
            
            logger.info(f"Fetching nodepools for supercomputer '{supercomputer_name}'...")
            
            # Get access token for Azure API calls - follow same pattern as other methods
            try:
                from azure_auth_helpers import get_token_for_tenant
                server_traces = []
                access_token = await asyncio.to_thread(
                    get_token_for_tenant,
                    "https://management.azure.com/.default",
                    tenant_id,
                    server_traces,
                    purpose='list-nodepools'
                )
                if not access_token:
                    return {"success": False, "error": "Failed to obtain Azure access token"}
            except Exception as e:
                return {"success": False, "error": f"Failed to get access token: {str(e)}"}
            
            # Build a mapping of VM sizes to their SKU details by fetching SKU information
            vm_sku_details = await self._fetch_vm_sku_details(access_token, subscription_id, location)
            logger.debug(f"VM SKU Details retrieved: {vm_sku_details}")
            
            # Query nodepools from Azure Discovery API
            url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/supercomputers/{supercomputer_name}/nodepools"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            params = {'api-version': '2025-07-01-preview'}
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to fetch nodepools: {response.status_code}",
                    "details": response.text[:500] if response.text else None
                }
            
            nodepool_data = response.json()
            nodepools = nodepool_data.get('value', [])
            
            logger.info(f"Nodepool count: {len(nodepools)}")
            logger.info(f"Raw nodepool response: {json.dumps(nodepool_data, indent=2)}")
            print(f"[DEBUG] Nodepool count: {len(nodepools)}", file=sys.stderr)
            print(f"[DEBUG] Raw nodepool response: {json.dumps(nodepool_data, indent=2)}", file=sys.stderr)
            
            if not nodepools:
                return {
                    "success": True,
                    "nodepools": [],
                    "count": 0,
                    "message": "No nodepools found in supercomputer"
                }
            
            # Extract and organize nodepool information
            nodepool_list = []
            logger.info(f"Processing {len(nodepools)} nodepools...")
            print(f"[DEBUG] Processing {len(nodepools)} nodepools...", file=sys.stderr)
            
            for np in nodepools:
                np_name = np.get('name', 'unknown')
                np_id = np.get('id', '')
                properties = np.get('properties', {})
                
                logger.info(f"Processing nodepool: {np_name}")
                print(f"[DEBUG] Processing nodepool: {np_name}", file=sys.stderr)

                # Filter: only include nodepools that are in 'Succeeded' provisioning state
                provisioning_state = properties.get('provisioningState', 'Unknown')
                if provisioning_state != 'Succeeded':
                    logger.debug("Skipping nodepool '%s' with provisioning state: %s", np_name, provisioning_state)
                    continue
                
                # Extract compute and infrastructure details
                compute_profile = properties.get('computeProfile', {})
                vm_config = compute_profile.get('vmConfiguration', {})
                # VM size is at the root level of properties, not nested
                vm_size = properties.get('vmSize', vm_config.get('vmSize', 'Unknown'))
                
                logger.debug(f"Nodepool '{np_name}': vm_size={vm_size}, compute_profile={compute_profile}, vm_config={vm_config}")
                print(f"[DEBUG] Nodepool '{np_name}': vm_size={vm_size}", file=sys.stderr)
                
                # Get detailed VM SKU information if available
                vm_specs = vm_sku_details.get(vm_size, {})
                logger.debug(f"Nodepool '{np_name}': vm_sku_details lookup for '{vm_size}' returned: {vm_specs}")
                print(f"[DEBUG] vm_specs for '{vm_size}': {vm_specs}", file=sys.stderr)
                
                # If SKU details are not available, populate from nodepool properties
                if not vm_specs:
                    vm_specs = {
                        'cpu_cores': compute_profile.get('cpuCores', compute_profile.get('vCPUs', 'Unknown')),
                        'memory_gb': compute_profile.get('memoryGB', 'Unknown'),
                        'gpu_count': vm_config.get('gpuCount', 0),
                        'gpu_type': vm_config.get('gpuType', None),
                    }
                    # Remove None and empty values
                    vm_specs = {k: v for k, v in vm_specs.items() if v is not None and v != ''}
                    logger.debug(f"Nodepool '{np_name}': Fallback vm_specs from properties: {vm_specs}")
                
                # Remove 'restrictions' from vm_specs if present to avoid leaking internal details
                if isinstance(vm_specs, dict) and 'restrictions' in vm_specs:
                    vm_specs.pop('restrictions', None)

                # Extract top-level location (if present on the resource) and maxNodeCount
                np_location = np.get('location') or np.get('properties', {}).get('location') or location
                max_node_count = properties.get('maxNodeCount', properties.get('max_node_count', None))

                nodepool_info = {
                    'name': np_name,
                    'id': np_id,
                    'location': np_location,
                    'pool_type': properties.get('poolType', 'static'),
                    'max_node_count': max_node_count,
                    'compute': {
                        'vm_size': vm_size,
                    },
                    'vm_specifications': vm_specs,
                }
                nodepool_list.append(nodepool_info)
            
            # Sort by name for consistency
            nodepool_list.sort(key=lambda x: x['name'])
            
            return {
                "success": True,
                "nodepools": nodepool_list,
                "count": len(nodepool_list),
                "supercomputer": supercomputer_name,
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "location": location,
                "guidance": {
                    "description": "Use nodepool characteristics to select the best nodepool for your tool requirements",
                    "how_to_use": "Compare the VM size, pool type, and compute resources with your tool's requirements, then pass the nodepool name to submit_job's nodepool_name parameter",
                    "default_behavior": "If nodepool_name is not specified in submit_job, the server will use the first available nodepool"
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to list nodepools: {e}")
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "error": f"Failed to list nodepools: {str(e)}"
            }
    
    async def _fetch_vm_sku_details(self, access_token: str, subscription_id: str, location: str) -> Dict[str, Dict[str, Any]]:
        """Fetch detailed VM SKU specifications for all VM sizes in a location
        
        Args:
            access_token: Azure access token
            subscription_id: Azure subscription ID
            location: Azure region
            
        Returns:
            Dictionary mapping VM size names to their specifications
        """
        try:
            url = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.Compute/skus"
            headers = {
                'Authorization': f'Bearer {access_token}',
            }
            params = {
                'api-version': '2021-07-01',
                '$filter': f"location eq '{location}'"
            }
            
            logger.debug(f"Fetching VM SKU details from: {url} with filter location='{location}'")
            response = requests.get(url, headers=headers, params=params, timeout=30)
            logger.debug(f"VM SKU API response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch VM SKU details: {response.status_code} - {response.text[:500]}")
                return {}
            
            skus_data = response.json()
            logger.debug(f"Received {len(skus_data.get('value', []))} SKU records from API")
            vm_sku_map = {}
            
            for sku in skus_data.get('value', []):
                # Only process VM SKUs
                if sku.get('resourceType') != 'virtualMachines':
                    continue
                
                sku_name = sku.get('name', '')
                capabilities = {cap['name']: cap['value'] for cap in sku.get('capabilities', [])}
                
                try:
                    # Extract CPU and memory from capabilities
                    cpu_count = int(capabilities.get('vCPUs', capabilities.get('vCPu', 0)))
                    memory_gb = float(capabilities.get('MemoryGB', 0))
                    
                    if cpu_count > 0 and memory_gb > 0:
                        vm_sku_map[sku_name] = {
                            'cpu_cores': cpu_count,
                            'memory_gb': memory_gb,
                            'tier': sku.get('tier', 'Standard'),
                            'family': sku.get('family', 'Unknown'),
                            'size': sku.get('size', ''),
                            'restrictions': sku.get('restrictions', [])
                        }
                except (ValueError, TypeError, KeyError):
                    continue
            
            logger.info(f"Fetched specifications for {len(vm_sku_map)} VM SKU types")
            logger.debug(f"VM SKU map: {vm_sku_map}")
            return vm_sku_map
            
        except Exception as e:
            logger.warning(f"Failed to fetch VM SKU details: {e}")
            return {}
    
    async def _get_published_tool_details(self, tool_name: str) -> Dict[str, Any]:
        """Get detailed information for a specific Discovery tool
        
        Uses AzureDiscoveryClient to retrieve full tool definition including:
        - Tool configuration (ACR image, command, working directory)
        - Environment variables and mounts
        - Provisioning state and metadata
        
        Args:
            tool_name: Name of the tool to retrieve
            
        Returns:
            Dict with detailed tool information
        """
        try:
            # Get Azure configuration
            config = self.config_manager.load_config()
            if not config:
                return {"error": "Config manager not initialized"}
            
            azure_config = config.get('azure', {})
            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            tenant_id=azure_config.get('tenant_id', '').strip()
            
            if not subscription_id or not resource_group:
                return {
                    "error": "Azure subscription_id and resource_group must be configured",
                    "config_hint": "Please configure Azure settings in discovery_config.json"
                }
            
            # Import discovery publisher
            try:
                from discovery_publisher import AzureDiscoveryClient
            except ImportError:
                return {"error": "Discovery publisher module not available"}
            
            logger.info(f"Getting detailed information for tool '{tool_name}'...")
            
            # Initialize client
            azure_client = AzureDiscoveryClient()
            
            # First list to find the resource ID
            list_result = azure_client.list_discovery_tools(
                subscription_id,
                resource_group,
                acr_image=None,
                tool_name=tool_name,
                tenant_id=tenant_id
            )
            
            if not list_result.get('exists'):
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' not found in resource group '{resource_group}'",
                    "tool_name": tool_name,
                    "resource_group": resource_group
                }
            
            # Get the first matching tool
            tools_data = list_result.get('all_tools', list_result.get('tools', []))
            if not tools_data:
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' not found in resource group '{resource_group}'",
                    "tool_name": tool_name,
                    "resource_group": resource_group
                }
            
            # Extract the first matching tool
            tool_info = tools_data[0]
            if isinstance(tool_info, dict):
                if 'tool_data' in tool_info:
                    tool_data = tool_info.get('tool_data', {})
                else:
                    tool_data = tool_info
            else:
                return {
                    "success": False,
                    "error": "Invalid tool data format"
                }
            
            # Get resource ID for detailed lookup
            resource_id = tool_info.get('resource_id') or tool_data.get('id', '')
            
            # Get detailed tool information using resource ID
            detailed_tool = azure_client.get_discovery_tool_details(resource_id, tenant_id=tenant_id)
            
            if not detailed_tool:
                # Fall back to list data if detailed lookup fails
                logger.warning(f"Could not get detailed tool info, using list data")
                detailed_tool = tool_data
            
            # Extract key information
            properties = detailed_tool.get('properties') or {}
            definition_content = properties.get('definitionContent') or {}
            
            # Extract environment variables
            environment = {}
            env_vars = definition_content.get('environmentVariables', [])
            for env_var in env_vars:
                if isinstance(env_var, dict):
                    name = env_var.get('name', '')
                    value = env_var.get('value', '')
                    if name:
                        environment[name] = value
            
            # Extract mounts
            mounts = definition_content.get('mounts', [])
            mounts_list = []
            for mount in mounts:
                if isinstance(mount, dict):
                    mounts_list.append({
                        'name': mount.get('name', ''),
                        'type': mount.get('type', ''),
                        'path': mount.get('path', '')
                    })
            
            # Build response with detailed information
            tool_details = {
                'name': detailed_tool.get('name', tool_name),
                'resource_id': resource_id,
                'location': detailed_tool.get('location', 'unknown'),
                'provisioning_state': properties.get('provisioningState', 'unknown'),
                'version': properties.get('version', ''),
                'description': definition_content.get('description') or definition_content.get('Description', ''),
                
                # Tool definition
                'tool_definition': {
                    'acr_image': definition_content.get('acrImage', ''),
                    'command': definition_content.get('command', ''),
                    'working_directory': definition_content.get('workingDirectory', ''),
                    'environment_variables': environment,
                    'mounts': mounts_list
                },
                
                # Extension info
                'extension': definition_content.get('extension', {}),
                
                # System metadata
                'system_data': detailed_tool.get('systemData', {}),
                'tags': detailed_tool.get('tags', {}),
                
                # Include raw data for debugging
                'raw_properties': properties,
                'raw_definition_content': definition_content,
                'raw_detailed_tool': detailed_tool
            }
            
            return {
                "success": True,
                "tool": tool_details,
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "message": f"Retrieved detailed information for tool '{tool_name}'",
                "note": "Check raw_properties, raw_definition_content, and raw_detailed_tool for all available fields from the API"
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Request timed out while retrieving tool details"
            }
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Failed to parse tool data: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Failed to get tool details: {e}")
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "error": f"Failed to get tool details: {str(e)}"
            }
    
    async def _publish_tool(self, tool_yaml_path: str, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Publish a Discovery tool to Azure
        
        Args:
            tool_yaml_path: Absolute path to the tool definition YAML file
            tool_name: Optional override for the tool name
            
        Returns:
            Dict with success status and tool information
        """
        try:
            import yaml
            import os
            
            # Validate file exists
            if not os.path.exists(tool_yaml_path):
                return {
                    "success": False,
                    "error": f"Tool YAML file not found: {tool_yaml_path}"
                }
            
            # Read and parse the YAML file
            with open(tool_yaml_path, 'r', encoding='utf-8') as f:
                tool_definition = yaml.safe_load(f)
            
            if not tool_definition:
                return {
                    "success": False,
                    "error": "Tool YAML file is empty or invalid"
                }
            
            # Process ACR placeholders in tool definition
            tool_definition = self.config_manager.process_tool_definition_acr(tool_definition)
            
            # Extract tool name
            yaml_tool_name = tool_definition.get('name', '')
            final_tool_name = tool_name or yaml_tool_name
            
            if not final_tool_name:
                return {
                    "success": False,
                    "error": "Tool name not found in YAML and not provided as parameter"
                }
            
            # Get Azure configuration
            config = self.config_manager.load_config()
            if not config:
                return {"error": "Config manager not initialized"}
            
            azure_config = config.get('azure', {})
            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            location = azure_config.get('location', '').strip()
            tenant_id = azure_config.get('tenant_id', '').strip()
            
            if not subscription_id or not resource_group or not location:
                return {
                    "success": False,
                    "error": "Azure subscription_id, resource_group, and location must be configured",
                    "config_hint": "Please configure Azure settings in discovery_config.json"
                }
            
            if not tenant_id:
                return {
                    "success": False,
                    "error": "Azure tenant_id must be configured for tool publishing",
                    "config_hint": "Please configure tenant_id in discovery_config.json under azure section"
                }
            
            # Import REST publisher
            try:
                from discovery_rest_publisher import DiscoveryRestPublisher
            except ImportError:
                return {
                    "success": False,
                    "error": "Discovery REST publisher module not available"
                }
            
            # Initialize publisher with tenant_id
            publisher = DiscoveryRestPublisher(
                subscription_id=subscription_id,
                resource_group=resource_group,
                location=location,
                tenant_id=tenant_id
            )
            
            logger.info(f"Publishing tool '{final_tool_name}' to Azure...")
            
            # Publish the tool (create or update)
            result = publisher.create_or_update_discovery_tool(
                tool_name=final_tool_name,
                tool_definition=tool_definition,
                location=location
            )
            
            if result.get('success'):
                action = result.get('action', 'published')
                return {
                    "success": True,
                    "tool_name": result.get('tool_name', final_tool_name),
                    "tool_id": result.get('tool_id', ''),
                    "resource_name": result.get('resource_name', ''),
                    "action": action,
                    "subscription_id": subscription_id,
                    "resource_group": resource_group,
                    "location": location,
                    "message": f"Tool '{final_tool_name}' {action} successfully"
                }
            else:
                return {
                    "success": False,
                    "error": result.get('error', 'Unknown error during tool publishing'),
                    "tool_name": final_tool_name
                }
            
        except Exception as e:
            logger.exception("Failed to publish tool")
            error_tracker.record_error("ToolPublishError", str(e), {
                "tool_yaml_path": tool_yaml_path,
                "tool_name": tool_name
            })
            return {
                "success": False,
                "error": f"Failed to publish tool: {str(e)}"
            }
    
    async def _publish_tool_agent(self, agent_yaml_path: str, tool_yaml_path: str, 
                                  agent_name: Optional[str] = None, tool_name: Optional[str] = None,
                                  model_name: Optional[str] = None) -> Dict[str, Any]:
        """Publish a Discovery tool agent to Azure
        
        IMPORTANT: When multiple agents share the same tool/container (e.g., RDKit chemistry
        toolkit agents like moleculeAgent, fingerPrintAgent, descriptorAgent), they should ALL
        reference the SAME tool name from the tool definition YAML. Do NOT create separate
        tool instances (moleculeService, fingerPrintService, etc.) - instead, use the shared tool
        name (e.g., 'rdkit') so all agents reference one tool deployment.
        
        Args:
            agent_yaml_path: Absolute path to the agent definition YAML file
            tool_yaml_path: Absolute path to the tool definition YAML file
            agent_name: Optional override for the agent name
            tool_name: Optional override for the tool name (use the SAME name for shared tools)
            model_name: Optional override for the model name
            
        Returns:
            Dict with success status and agent/tool information
        """
        try:
            import yaml
            import os
            
            # Validate files exist
            if not os.path.exists(agent_yaml_path):
                return {
                    "success": False,
                    "error": f"Agent YAML file not found: {agent_yaml_path}"
                }
            
            if not os.path.exists(tool_yaml_path):
                return {
                    "success": False,
                    "error": f"Tool YAML file not found: {tool_yaml_path}"
                }
            
            # Read and parse the YAML files
            with open(agent_yaml_path, 'r', encoding='utf-8') as f:
                agent_definition = yaml.safe_load(f)
            
            with open(tool_yaml_path, 'r', encoding='utf-8') as f:
                tool_definition = yaml.safe_load(f)
            
            if not agent_definition:
                return {
                    "success": False,
                    "error": "Agent YAML file is empty or invalid"
                }
            
            if not tool_definition:
                return {
                    "success": False,
                    "error": "Tool YAML file is empty or invalid"
                }
            
            # Process ACR placeholders in tool definition
            tool_definition = self.config_manager.process_tool_definition_acr(tool_definition)
            
            # Extract names
            # Agent name might be nested under 'agent.name' or at top level
            if 'agent' in agent_definition and isinstance(agent_definition['agent'], dict):
                yaml_agent_name = agent_definition['agent'].get('name', '')
            else:
                yaml_agent_name = agent_definition.get('name', '')
            
            yaml_tool_name = tool_definition.get('name', '')
            final_agent_name = agent_name or yaml_agent_name
            final_tool_name = tool_name or yaml_tool_name
            
            if not final_agent_name:
                return {
                    "success": False,
                    "error": "Agent name not found in YAML and not provided as parameter"
                }
            
            if not final_tool_name:
                return {
                    "success": False,
                    "error": "Tool name not found in YAML and not provided as parameter"
                }
            
            # Get Azure configuration
            config = self.config_manager.load_config()
            if not config:
                return {"error": "Config manager not initialized"}
            
            azure_config = config.get('azure', {})
            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            location = azure_config.get('location', '').strip()
            tenant_id = azure_config.get('tenant_id', '').strip()
            
            if not subscription_id or not resource_group or not location:
                return {
                    "success": False,
                    "error": "Azure subscription_id, resource_group, and location must be configured",
                    "config_hint": "Please configure Azure settings in discovery_config.json"
                }
            
            if not tenant_id:
                return {
                    "success": False,
                    "error": "Azure tenant_id must be configured for tool publishing",
                    "config_hint": "Please configure tenant_id in discovery_config.json under azure section"
                }
            
            # Import REST publisher
            try:
                from discovery_rest_publisher import DiscoveryRestPublisher
            except ImportError:
                return {
                    "success": False,
                    "error": "Discovery REST publisher module not available"
                }
            
            # Initialize publisher with tenant_id
            publisher = DiscoveryRestPublisher(
                subscription_id=subscription_id,
                resource_group=resource_group,
                location=location,
                tenant_id=tenant_id
            )
            
            logger.info(f"Publishing tool '{final_tool_name}' to Azure...")
            
            # Step 1: Publish the tool (create or update)
            tool_result = publisher.create_or_update_discovery_tool(
                tool_name=final_tool_name,
                tool_definition=tool_definition,
                location=location
            )
            
            if not tool_result.get('success'):
                return {
                    "success": False,
                    "error": f"Failed to publish tool: {tool_result.get('error', 'Unknown error')}",
                    "tool_name": final_tool_name
                }
            
            tool_id = tool_result.get('tool_id', '')
            tool_action = tool_result.get('action', 'published')
            
            logger.info(f"Tool '{final_tool_name}' {tool_action} successfully, ID: {tool_id}")
            logger.info(f"Publishing agent '{final_agent_name}' to Azure...")
            
            # Step 2: Publish the agent (create or update)
            agent_result = publisher.create_or_update_discovery_agent(
                agent_name=final_agent_name,
                agent_definition=agent_definition,
                tool_id=tool_id,
                location=location,
                model_name=model_name
            )
            
            if agent_result.get('success'):
                agent_action = agent_result.get('action', 'published')
                return {
                    "success": True,
                    "agent_name": agent_result.get('agent_name', final_agent_name),
                    "agent_id": agent_result.get('agent_id', ''),
                    "agent_action": agent_action,
                    "tool_name": tool_result.get('tool_name', final_tool_name),
                    "tool_id": tool_id,
                    "tool_action": tool_action,
                    "subscription_id": subscription_id,
                    "resource_group": resource_group,
                    "location": location,
                    "message": f"Tool agent '{final_agent_name}' {agent_action} successfully (tool: '{final_tool_name}' {tool_action})"
                }
            else:
                return {
                    "success": False,
                    "error": f"Tool published but agent failed: {agent_result.get('error', 'Unknown error')}",
                    "agent_name": final_agent_name,
                    "tool_name": final_tool_name,
                    "tool_id": tool_id,
                    "tool_action": tool_action
                }
            
        except Exception as e:
            logger.exception("Failed to publish tool agent")
            error_tracker.record_error("ToolAgentPublishError", str(e), {
                "agent_yaml_path": agent_yaml_path,
                "tool_yaml_path": tool_yaml_path,
                "agent_name": agent_name,
                "tool_name": tool_name
            })
            return {
                "success": False,
                "error": f"Failed to publish tool agent: {str(e)}"
            }
    
    async def _publish_tool_from_catalog(self, agent_key: str, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """Publish a Discovery tool to Azure by looking it up in the agent catalog
        
        Args:
            agent_key: The key/name of the agent in the catalog
            tool_name: Optional override for the tool name
            
        Returns:
            Dict with success status and tool information
        """
        try:
            # Check if agent manager is initialized
            if not self.agent_manager:
                return {
                    "success": False,
                    "error": "Agent manager not initialized. Please load an agent catalog first."
                }
            
            # Look up the agent in the catalog
            if agent_key not in self.agent_manager.agents:
                return {
                    "success": False,
                    "error": f"Agent '{agent_key}' not found in catalog. Available agents: {list(self.agent_manager.agents.keys())}"
                }
            
            agent_entry = self.agent_manager.agents[agent_key]
            
            # Get the tool definition path (try both singular and plural fields)
            tool_yaml_path = agent_entry.tool_definition or agent_entry.tools_definition
            if not tool_yaml_path:
                return {
                    "success": False,
                    "error": f"Agent '{agent_key}' does not have a tool_definition or tools_definition specified in the catalog"
                }
            
            # Resolve relative path if needed
            import os
            if not os.path.isabs(tool_yaml_path):
                # Resolve relative to the catalog file location
                catalog_dir = os.path.dirname(os.path.abspath(self.agent_manager.catalog_path))
                tool_yaml_path = os.path.normpath(os.path.join(catalog_dir, tool_yaml_path))
            
            # Check if file exists
            if not os.path.exists(tool_yaml_path):
                return {
                    "success": False,
                    "error": f"Tool definition file not found: {tool_yaml_path}"
                }
            
            logger.info(f"Publishing tool from catalog for agent '{agent_key}' using tool definition: {tool_yaml_path}")
            
            # Use the existing _publish_tool method
            result = await self._publish_tool(tool_yaml_path, tool_name)
            
            # Add catalog info to result
            if result.get("success"):
                result["catalog_agent_key"] = agent_key
                result["tool_yaml_path"] = tool_yaml_path
            
            return result
            
        except Exception as e:
            logger.exception("Failed to publish tool from catalog")
            error_tracker.record_error("CatalogToolPublishError", str(e), {
                "agent_key": agent_key,
                "tool_name": tool_name
            })
            return {
                "success": False,
                "error": f"Failed to publish tool from catalog: {str(e)}"
            }
    
    async def _publish_agent_from_catalog(self, agent_key: str, agent_name: Optional[str] = None, 
                                          tool_name: Optional[str] = None, model_name: Optional[str] = None) -> Dict[str, Any]:
        """Publish a Discovery tool agent to Azure by looking it up in the agent catalog
        
        Args:
            agent_key: The key/name of the agent in the catalog
            agent_name: Optional override for the agent name
            tool_name: Optional override for the tool name
            model_name: Optional override for the model name
            
        Returns:
            Dict with success status and agent/tool information
        """
        try:
            # Check if agent manager is initialized
            if not self.agent_manager:
                return {
                    "success": False,
                    "error": "Agent manager not initialized. Please load an agent catalog first."
                }
            
            # Look up the agent in the catalog
            if agent_key not in self.agent_manager.agents:
                return {
                    "success": False,
                    "error": f"Agent '{agent_key}' not found in catalog. Available agents: {list(self.agent_manager.agents.keys())}"
                }
            
            agent_entry = self.agent_manager.agents[agent_key]
            
            # Get the agent config path
            agent_yaml_path = agent_entry.agent_config
            if not agent_yaml_path:
                return {
                    "success": False,
                    "error": f"Agent '{agent_key}' does not have an agent_config specified in the catalog"
                }
            
            # Get the tool definition path (try both singular and plural fields)
            tool_yaml_path = agent_entry.tool_definition or agent_entry.tools_definition
            if not tool_yaml_path:
                return {
                    "success": False,
                    "error": f"Agent '{agent_key}' does not have a tool_definition or tools_definition specified in the catalog"
                }
            
            # Resolve relative paths if needed
            import os
            catalog_dir = os.path.dirname(os.path.abspath(self.agent_manager.catalog_path))
            
            if not os.path.isabs(agent_yaml_path):
                agent_yaml_path = os.path.normpath(os.path.join(catalog_dir, agent_yaml_path))
            
            if not os.path.isabs(tool_yaml_path):
                tool_yaml_path = os.path.normpath(os.path.join(catalog_dir, tool_yaml_path))
            
            # Check if files exist
            if not os.path.exists(agent_yaml_path):
                return {
                    "success": False,
                    "error": f"Agent definition file not found: {agent_yaml_path}"
                }
            
            if not os.path.exists(tool_yaml_path):
                return {
                    "success": False,
                    "error": f"Tool definition file not found: {tool_yaml_path}"
                }
            
            logger.info(f"Publishing agent from catalog '{agent_key}'")
            logger.info(f"  Agent definition: {agent_yaml_path}")
            logger.info(f"  Tool definition: {tool_yaml_path}")
            
            # Use the existing _publish_tool_agent method
            result = await self._publish_tool_agent(agent_yaml_path, tool_yaml_path, agent_name, tool_name, model_name)
            
            # Add catalog info to result
            if result.get("success"):
                result["catalog_agent_key"] = agent_key
                result["agent_yaml_path"] = agent_yaml_path
                result["tool_yaml_path"] = tool_yaml_path
            
            return result
            
        except Exception as e:
            logger.exception("Failed to publish agent from catalog")
            error_tracker.record_error("CatalogAgentPublishError", str(e), {
                "agent_key": agent_key,
                "agent_name": agent_name,
                "tool_name": tool_name
            })
            return {
                "success": False,
                "error": f"Failed to publish agent from catalog: {str(e)}"
            }

    async def _upload_input_files(self, local_path: str, remote_prefix: Optional[str] = None) -> Dict[str, Any]:
        """Upload local files to Azure Storage for use as job inputs
        
        Args:
            local_path: Absolute path to local directory or file to upload
            remote_prefix: Optional remote path prefix/folder name. If not provided, auto-generated.
            
        Returns:
            Dictionary with upload results including the remote prefix to use in submit_job
        """
        server_traces = []
        
        try:
            import uuid
            from datetime import datetime, timezone
            from azure.storage.blob import BlobServiceClient
            from azure_auth_helpers import get_credential_for_tenant
            import requests
            
            # Validate local path
            if not os.path.exists(local_path):
                return {
                    "success": False,
                    "error": f"Local path does not exist: {local_path}",
                    "traces": server_traces
                }
            
            # Load configuration
            config = self.config_manager.load_config()
            azure_config = config.get('azure', {})
            azure_compute_config = config.get('azure_compute', {})
            
            tenant_id = azure_config.get('tenant_id', '')
            subscription_id = azure_config.get('subscription_id', '')
            resource_group = azure_config.get('resource_group', '')
            storage_account = azure_compute_config.get('storage_account', '')
            inputs_asset = azure_compute_config.get('inputs_asset', '').strip()
            
            if not storage_account:
                return {
                    "success": False,
                    "error": "Storage account not configured",
                    "traces": server_traces
                }
            
            # Parse storage account name
            if '/providers/Microsoft.Storage/storageAccounts/' in storage_account:
                account_name = storage_account.split('/')[-1]
            elif storage_account.startswith('https://'):
                host = storage_account.split('://', 1)[1]
                account_name = host.split('.')[0]
            else:
                account_name = storage_account
            
            account_url = f"https://{account_name}.blob.core.windows.net"
            
            # Get credential
            cred = get_credential_for_tenant(tenant_id, purpose='blob-upload')
            if not cred:
                return {
                    "success": False,
                    "error": "Could not obtain Azure credential",
                    "traces": server_traces
                }
            
            # Query Management API to get the inputs asset's blob container and path
            if not inputs_asset:
                return {
                    "success": False,
                    "error": "inputs_asset not configured in discovery_config.json",
                    "traces": server_traces
                }
            
            # Get management token
            mgmt_token = self._get_azure_management_token(tenant_id, server_traces)
            
            # Query asset properties
            mgmt_api = f"https://management.azure.com{inputs_asset}?api-version=2025-07-01-preview"
            mgmt_headers = {'Authorization': f'Bearer {mgmt_token}'}
            mgmt_resp = requests.get(mgmt_api, headers=mgmt_headers, timeout=15)
            
            if mgmt_resp.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to query inputs asset: {mgmt_resp.status_code} - {mgmt_resp.text}",
                    "traces": server_traces
                }
            
            mgmt_body = mgmt_resp.json()
            asset_path = mgmt_body.get('properties', {}).get('path', '')
            
            if not asset_path:
                return {
                    "success": False,
                    "error": "Inputs asset has no path property",
                    "traces": server_traces
                }
            
            # Parse container and base path from asset path
            path_parts = str(asset_path).strip('/').split('/', 1)
            container_name = path_parts[0] if len(path_parts) > 0 else ''
            asset_base_path = path_parts[1] if len(path_parts) > 1 else ''
            
            if not container_name:
                return {
                    "success": False,
                    "error": "Could not determine container name from asset path",
                    "traces": server_traces
                }
            
            # Generate remote prefix if not provided, and always append a unique GUID
            if not remote_prefix:
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
                remote_prefix = f"upload-{timestamp}"
            
            # Append unique GUID to avoid conflicts
            unique_id = str(uuid.uuid4())
            remote_prefix_with_guid = f"{remote_prefix}/{unique_id}"
            
            # Combine asset base path with remote prefix
            if asset_base_path:
                blob_prefix = f"{asset_base_path}/{remote_prefix_with_guid}"
            else:
                blob_prefix = remote_prefix_with_guid
            
            server_traces.append(f"Uploading to {account_name}/{container_name}/{blob_prefix}")
            
            # Create blob service client
            blob_service = BlobServiceClient(account_url=account_url, credential=cred)
            container_client = blob_service.get_container_client(container_name)
            
            # Collect files to upload
            files_to_upload = []
            if os.path.isfile(local_path):
                files_to_upload.append((local_path, os.path.basename(local_path)))
            else:
                for root, _, files in os.walk(local_path):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        rel_path = os.path.relpath(fpath, local_path).replace('\\', '/')
                        files_to_upload.append((fpath, rel_path))
            
            if not files_to_upload:
                return {
                    "success": False,
                    "error": f"No files found at {local_path}",
                    "traces": server_traces
                }
            
            server_traces.append(f"Found {len(files_to_upload)} file(s) to upload")
            
            # Upload files
            uploaded_count = 0
            for idx, (fpath, rel_path) in enumerate(files_to_upload, 1):
                blob_name = f"{blob_prefix}/{rel_path}"
                
                try:
                    file_size = os.path.getsize(fpath)
                    size_kb = file_size / 1024
                    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
                    
                    with open(fpath, 'rb') as data_fp:
                        blob_client = container_client.get_blob_client(blob_name)
                        blob_client.upload_blob(data_fp, overwrite=True)
                        uploaded_count += 1
                        server_traces.append(f"[{idx}/{len(files_to_upload)}] Uploaded {rel_path} ({size_str})")
                
                except Exception as upload_e:
                    server_traces.append(f"✗ Failed to upload {rel_path}: {str(upload_e)}")
                    return {
                        "success": False,
                        "error": f"Upload failed for {rel_path}: {str(upload_e)}",
                        "traces": server_traces,
                        "files_uploaded": uploaded_count,
                        "files_total": len(files_to_upload)
                    }
            
            server_traces.append(f"Upload complete: {uploaded_count} file(s) uploaded")
            
            return {
                "success": True,
                "message": f"Successfully uploaded {uploaded_count} file(s) to {remote_prefix_with_guid}",
                "remote_prefix": remote_prefix_with_guid,
                "container": container_name,
                "files_uploaded": uploaded_count,
                "traces": server_traces
            }
        
        except Exception as e:
            logger.exception("Failed to upload input files")
            error_tracker.record_error("UploadInputFilesError", str(e), {"local_path": local_path})
            return {
                "success": False,
                "error": str(e),
                "traces": server_traces
            }

    async def _submit_job(self, agent_name: str, script_path: str, 
                          nodepool_name: str, input_files_prefix: Optional[str] = None,
                          depends_on_job_id: Optional[str] = None, wait_for_parent: bool = True,
                          wait_for_completion: bool = True, timeout_seconds: int = 3600,
                          interactive_mode: str = "none", interactive_timeout_minutes: int = 30) -> Dict[str, Any]:
        """Submit a job to execute code on the Azure Discovery Supercomputer
        
        Supports automatic job chaining - when depends_on_job_id is provided, this job will
        automatically mount outputs from the parent job as inputs at /input/, enabling
        seamless multi-stage workflows.
        
        Args:
            agent_name: Name of the agent/tool to use for execution
            script_path: Path to Python script file to execute (required)
            nodepool_name: Name of the specific nodepool to use (required)
            input_files_prefix: Optional remote prefix from upload_input_files for input mount
                               (ignored if depends_on_job_id is specified)
            depends_on_job_id: Optional job ID whose outputs should be mounted as inputs
            wait_for_parent: Only used with depends_on_job_id. If true (default), waits for
                           parent job to complete before submitting
            wait_for_completion: If true (default), waits for job to complete before returning.
                               AUTOMATICALLY OVERRIDDEN TO FALSE when interactive_mode is enabled.
            timeout_seconds: Maximum time to wait for job completion in seconds (default: 3600)
            interactive_mode: 'none', 'vscode', or 'novnc'. Enables interactive remote access
                            via Azure Dev Tunnels. Default: 'none'.
            interactive_timeout_minutes: How long to keep interactive tunnel alive (default: 30).
            
        Returns:
            Dictionary with job submission results including discovery_job_id, status, and traces.
            If wait_for_completion=True (and interactive_mode='none'), includes final job status.
            In interactive mode, returns immediately with session info.
        """
        try:
            logger.info(f"=== _submit_job called ===")
            logger.info(f"Parameters: agent_name={agent_name}, interactive_mode={interactive_mode}, wait_for_completion={wait_for_completion}")
            logger.info(f"Script path: {script_path}")
            logger.info(f"Nodepool: {nodepool_name}")
            import requests
            import base64
            import uuid
            from datetime import datetime, timezone
            
            server_traces = []
            interactive_session = None
            
            # Handle interactive mode
            if interactive_mode != "none":
                if not HAS_DEVTUNNEL:
                    return {
                        "success": False,
                        "error": "Dev Tunnel module not available. Check agent-workbench installation.",
                        "traces": server_traces
                    }
                
                # Check prerequisites (with VS Code CLI approach, this always succeeds)
                session_manager = InteractiveSessionManager(logger=lambda msg: server_traces.append(f"  [tunnel] {msg}"))
                prereq = session_manager.check_prerequisites()
                
                if not prereq["ready"]:
                    return {
                        "success": False,
                        "error": f"Interactive mode not available: {prereq['error']}",
                        "instructions": prereq["instructions"],
                        "traces": server_traces
                    }
                
                # Create interactive session (just generates session ID, no CLI calls)
                try:
                    config = InteractiveSessionConfig(
                        mode=interactive_mode,
                        timeout_minutes=interactive_timeout_minutes
                    )
                    interactive_session = session_manager.create_session(config)
                    server_traces.append(f"✓ Created interactive session: {interactive_session.session_id}")
                    server_traces.append(f"  Mode: {interactive_mode}")
                    server_traces.append(f"  Tunnel name: {interactive_session.tunnel.tunnel_id}")
                    server_traces.append(f"  Note: Tunnel will be created by VS Code CLI in container")
                    server_traces.append(f"  Check job logs for authentication instructions")
                    
                    # Store session manager for later retrieval
                    if not hasattr(self, '_interactive_session_manager'):
                        self._interactive_session_manager = session_manager
                    
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to create interactive session: {str(e)}",
                        "traces": server_traces
                    }
                
                # For interactive mode, we'll poll for tunnel auth info instead of normal completion
                # Don't override wait_for_completion - we handle it specially below
                logger.info("INTERACTIVE MODE: Will poll for tunnel auth info after job submission")
                server_traces.append("✓ Interactive mode: Will wait for tunnel auth info after submission")
            
            # Handle job dependencies if specified
            if depends_on_job_id:
                logger.info(f"Job depends on: {depends_on_job_id}")
                server_traces.append(f"Job depends on: {depends_on_job_id}")
                
                # Wait for parent job if requested
                if wait_for_parent:
                    server_traces.append(f"Checking parent job status...")
                    parent_status = await self._get_job_status(depends_on_job_id, include_logs=False)
                    
                    if not parent_status.get('success'):
                        return {
                            "success": False,
                            "error": f"Could not retrieve parent job status: {parent_status.get('error')}",
                            "parent_job_id": depends_on_job_id,
                            "traces": server_traces
                        }
                    
                    status = parent_status.get('status')
                    if status not in ['Succeeded', 'Running', 'Canceled', 'Failed']:
                        server_traces.append(f"Parent job not yet complete (status: {status}), waiting...")
                        wait_result = await self._wait_for_job(depends_on_job_id, timeout_seconds=3600)
                        if not wait_result.get('success'):
                            return {
                                "success": False,
                                "error": f"Parent job did not complete successfully: {wait_result.get('error')}",
                                "parent_job_id": depends_on_job_id,
                                "traces": server_traces
                            }
                        status = wait_result.get('status')
                    
                    if status != 'Succeeded':
                        return {
                            "success": False,
                            "error": f"Parent job must be in Succeeded status, current status: {status}",
                            "parent_job_id": depends_on_job_id,
                            "parent_status": status,
                            "traces": server_traces
                        }
                    
                    server_traces.append(f"Parent job completed successfully")
                
                # Get parent job details to extract output path
                required_fields = ['tenant_id', 'workspace_name', 'project_name']
                _, _, config_vals = self._get_azure_config_with_validation(required_fields)
                
                workspace_name = config_vals['workspace_name']
                tenant_id = config_vals['tenant_id']
                project_name = config_vals['project_name']
                
                # Get parent job details
                discovery_token = self._get_discovery_token(workspace_name, tenant_id, server_traces, purpose='get_parent_outputs')
                
                job_url = f"https://{workspace_name}.workspace.discovery.azure.com/tools/projects/{project_name}/operations/{depends_on_job_id}"
                headers = {
                    'Authorization': f'Bearer {discovery_token}',
                }
                
                response = requests.get(job_url, headers=headers, timeout=30)
                if response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Could not retrieve parent job details: {response.status_code}",
                        "parent_job_id": depends_on_job_id,
                        "traces": server_traces
                    }
                
                parent_job = response.json()
                output_data = parent_job.get('result', {}).get('outputData', [])
                
                if not output_data:
                    return {
                        "success": False,
                        "error": "Parent job has no output data to mount",
                        "parent_job_id": depends_on_job_id,
                        "traces": server_traces
                    }
                
                # Extract the output URI (typically discovery://dataassets/...)
                output_uri = output_data[0].get('uri', '')
                if not output_uri:
                    return {
                        "success": False,
                        "error": "Parent job output has no URI",
                        "parent_job_id": depends_on_job_id,
                        "traces": server_traces
                    }
                
                # Extract the path from the URI for input_files_prefix
                # URI format: discovery://dataassets/.../paths/run-20251108-123456-abc123/output
                # We need: run-20251108-123456-abc123/output
                import re
                match = re.search(r'/paths/([^/]+/output)$', output_uri)
                if match:
                    input_files_prefix = match.group(1)
                else:
                    # Fallback: try to extract last two path components
                    parts = output_uri.rstrip('/').split('/')
                    input_files_prefix = '/'.join(parts[-2:]) if len(parts) >= 2 else parts[-1]
                
                server_traces.append(f" Mounting parent outputs as inputs: {input_files_prefix}")
                # Note: input_files_prefix now overrides any user-provided value
            
            # Read script file - now always required
            if not os.path.isabs(script_path):
                # Make relative paths absolute from workspace root
                workbench_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                script_path = os.path.abspath(os.path.join(workbench_dir, script_path))
            
            if not os.path.exists(script_path):
                raise ValueError(f"Script file not found: {script_path}")
            
            logger.info(f"Reading script file: {script_path}")
            with open(script_path, 'r', encoding='utf-8') as f:
                code = f.read()
            
            logger.info(f"Original script size: {len(code)} characters")
            logger.info(f"Interactive mode: {interactive_mode}")
            
            # Interactive mode: use language-independent shell wrapper
            # Instead of injecting Python code, we upload a shell wrapper and modify the command
            shell_wrapper_content = None
            if interactive_mode != "none" and interactive_session is not None:
                logger.info(f"*** INTERACTIVE MODE ACTIVE - USING SHELL WRAPPER ***")
                from devtunnel import generate_shell_tunnel_wrapper
                shell_wrapper_content = generate_shell_tunnel_wrapper()
                logger.info(f"INTERACTIVE: Shell wrapper generated: {len(shell_wrapper_content)} chars")
                server_traces.append(f"  Interactive mode enabled: Using language-independent shell wrapper")
                server_traces.append(f"    Mode: {interactive_mode}")
                server_traces.append(f"    Wrapper size: {len(shell_wrapper_content)} chars")
                server_traces.append(f"    Tunnel name: {interactive_session.tunnel.tunnel_id}")
                # Note: Command will be modified later to use the wrapper
            else:
                logger.info("INFO: Interactive mode OFF - using original script without modification")
            
            # Check script size when base64 encoded
            encoded_code = base64.b64encode(code.encode('utf-8')).decode('ascii')
            encoded_size = len(encoded_code)
            
            # Get and validate configuration using helper
            required_fields = ['subscription_id', 'resource_group', 'tenant_id', 
                             'supercomputer_name', 'workspace_name', 'project_name',
                             'storage_account', 'discovery_storage']
            azure_config, azure_compute_config, config_vals = self._get_azure_config_with_validation(required_fields)
            
            # Always upload scripts to storage
            logger.info(f"Submitting job for agent: {agent_name} (script: {encoded_size} encoded chars, upload mode)")
            server_traces.append(f"Script size {encoded_size} chars, using upload mode")
            
            # Extract configuration values
            subscription_id = config_vals['subscription_id']
            resource_group = config_vals['resource_group']
            tenant_id = config_vals['tenant_id']
            supercomputer_name = config_vals['supercomputer_name']
            workspace_name = config_vals['workspace_name']
            project_name = config_vals['project_name']
            storage_account = config_vals['storage_account']
            discovery_storage = config_vals['discovery_storage']
            
            # Create run prefix for this job
            run_prefix = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"
            server_traces.append(f"Starting job submission: {run_prefix} (agent: {agent_name})")
            
            # Import the azure_auth_helpers module
            try:
                from azure_auth_helpers import get_token_for_tenant
            except ImportError:
                raise ValueError("azure_auth_helpers module not found. Make sure it's available in the workbench directory.")
            
            # Get management API token
            scope = 'https://management.azure.com/.default'
            access_token = get_token_for_tenant(scope, tenant_id, server_traces, purpose='supercomputer-execute')
            if not access_token:
                raise ValueError("Failed to obtain Azure access token for the specified tenant")
            
            # Resolve tool name and command template from published agents (not local catalog)
            try:
                # Get published agents list (uses cache if available)
                published_agents_result = await self._list_published_agents_and_tools()
                
                if not published_agents_result.get('success'):
                    raise ValueError(f"Could not retrieve published agents: {published_agents_result.get('error')}")
                
                agents_list = published_agents_result.get('agents', [])
                
                # Find the requested agent
                agent_info = None
                for agent in agents_list:
                    if agent.get('name') == agent_name:
                        agent_info = agent
                        break
                
                if not agent_info:
                    available_agents = ', '.join([a.get('name', 'unknown') for a in agents_list])
                    raise ValueError(f"Agent '{agent_name}' not found in catalog. Available agents: {available_agents}")
                
                # Get the first attached tool (agents typically have one primary tool)
                attached_tools = agent_info.get('attached_tools', [])
                if not attached_tools:
                    raise ValueError(f"Agent '{agent_name}' has no attached tools")
                
                tool_info = attached_tools[0]
                tool_name = tool_info.get('name')
                tool_id = tool_info.get('tool_id')
                code_environments = tool_info.get('code_environments', [])
                
                if not tool_name or not tool_id:
                    raise ValueError(f"Tool information incomplete for agent '{agent_name}'")
                
                # Detect tool type: action-based vs code-environment
                # Code-environment tools have 'code_environments' array
                is_action_based = False
                command_template = 'python /input/{{scriptName}}'
                
                if code_environments and isinstance(code_environments, list) and len(code_environments) > 0:
                    # Code-environment tool
                    command_template = code_environments[0].get('command', command_template)
                    server_traces.append(f"Using code environment command template: {command_template}")
                else:
                    # Action-based tool (no code environments defined)
                    is_action_based = True
                    command_template = None
                    server_traces.append(f"Detected action-based tool (no code environments)")
                
                server_traces.append(f"Resolved tool: {tool_name} (ID: {tool_id})")
                
            except Exception as e:
                raise ValueError(f"Error resolving tool definition: {e}")
            
            # Get nodepools
            try:
                url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/supercomputers/{supercomputer_name}/nodepools"
                headers = {
                    'Authorization': f'Bearer {access_token}',
                }
                params = {
                    'api-version': '2025-07-01-preview'
                }
                
                server_traces.append(f"Fetching nodepools for '{supercomputer_name}'")
                response = requests.get(url, headers=headers, params=params, timeout=30)
                
                if response.status_code != 200:
                    raise ValueError(f"Failed to fetch nodepools: {response.status_code} - {response.text}")
                
                nodepool_data = response.json()
                nodepools = nodepool_data.get('value', [])
                nodepool_ids = [np.get('id', '') for np in nodepools if np.get('id')]
                
                # Filter by requested nodepool if provided
                if nodepool_name:
                    matched_id = None
                    for np in nodepools:
                        np_name = str(np.get('name', '')).lower()
                        if np_name == nodepool_name.lower():
                            matched_id = np.get('id')
                            break
                    
                    if matched_id:
                        nodepool_ids = [matched_id]
                        server_traces.append(f"Using requested nodepool: {nodepool_name}")
                    else:
                        raise ValueError(f"Requested nodepool '{nodepool_name}' not found")
                elif nodepool_ids:
                    # Use first nodepool
                    nodepool_ids = [nodepool_ids[0]]
                    server_traces.append(f"Using first available nodepool")
                else:
                    raise ValueError("No nodepools available")
                
            except Exception as e:
                raise ValueError(f"Error fetching nodepools: {e}")
            
            # Extract data_container early - needed for script uploads and output mounts
            full_config = self.config_manager.load_config()
            azure_compute_config = full_config.get('azure_compute', {})
            data_container = azure_compute_config.get('data_container', '').strip()
            
            # Validate data_container is configured
            if not data_container:
                error_msg = (
                    "Missing required configuration: 'data_container' is not configured in Azure Compute settings. "
                    "Please configure a data container to specify where input/output data will be stored."
                )
                server_traces.append(f" X {error_msg}")
                error_tracker.record_error("ConfigurationError", error_msg, {"agent_name": agent_name})
                return {
                    "success": False,
                    "error": error_msg,
                    "agent_name": agent_name,
                    "traces": server_traces
                }
            
            # Detect if the LLM produced a script or an action command
            # Check the actual content of the 'code' parameter to determine handling:
            # - Script: Python code (starts with # comment, import, def, class, or has newlines with indentation)
            # - Action: Command to execute (single line or shell command format)
            code_lines = code.strip().split('\n') if code else []
            first_line = code_lines[0].strip() if code_lines else ''
            
            # It's a script if:
            # 1. Starts with # comment (Python script header)
            # 2. Starts with import statement
            # 3. Starts with def or class (function/class definition)
            # 4. Has multiple lines with Python-like indentation patterns
            # 5. Starts with docstring (triple quotes)
            # 6. Contains print statements or function calls
            looks_like_script = (
                first_line.startswith('#') or
                first_line.startswith('import ') or
                first_line.startswith('from ') or
                first_line.startswith('def ') or
                first_line.startswith('class ') or
                first_line.startswith('"""') or
                first_line.startswith("'''") or
                'print(' in code or
                (len(code_lines) > 3 and any(line.startswith('    ') or line.startswith('\t') for line in code_lines[1:]))
            )
            
            is_action_based = not looks_like_script
            
            # Prepare script and command based on what the LLM produced
            script_name = f"script_{run_prefix}.py"
            
            # For action commands: use the code parameter directly as the command
            # For scripts: format the command template with script name
            if is_action_based:
                # Action command: The 'code' parameter contains the command to execute directly
                formatted_command = code
            else:
                # Script: Format command template with script name
                # If command_template is None (tool defined as action-based but LLM produced a script),
                # use default Python execution command
                if command_template is None:
                    command_template = "python /input/{{scriptName}}"
                
                # Don't include 'input/' prefix - the command template already has /input/ path
                formatted_command = command_template.replace("{{scriptName}}", script_name).replace("{scriptName}", script_name)
                server_traces.append(f"Initial command: {formatted_command}")
            
            # Build request body
            storage_id = discovery_storage or storage_account
            
            # Base64 encode the script for submission (only needed for code-environment tools)
            encoded_script = base64.b64encode(code.encode('utf-8')).decode('utf-8') if not is_action_based else None
            
            # Upload script to storage (only for code-environment tools)
            script_discovery_uri = None
            if not is_action_based:
                try:
                    from azure_auth_helpers import get_token_for_tenant
                    import requests
                    
                    # Get storage account details from config
                    inputs_asset = azure_compute_config.get('inputs_asset', '').strip()
                    
                    server_traces.append(f" Storage config: account={storage_account[:50] if storage_account else 'None'}..., inputs_asset={inputs_asset[:50] if inputs_asset else 'None'}...")
                    
                    # Parse storage account from configuration
                    storage_account_name = None
                    container_name = None
                    asset_base_path = ''
                    
                    if storage_account:
                        # Extract storage account name from resource ID
                        if '/storageAccounts/' in storage_account:
                            storage_account_name = storage_account.split('/storageAccounts/')[-1].split('/')[0]
                    
                    # Get container name from inputs_asset path via Management API
                    if inputs_asset and storage_account_name:
                        try:
                            mgmt_token = self._get_azure_management_token(tenant_id, server_traces)
                            mgmt_api = f"https://management.azure.com{inputs_asset}?api-version=2025-07-01-preview"
                            mgmt_headers = {'Authorization': f'Bearer {mgmt_token}'}
                            mgmt_resp = requests.get(mgmt_api, headers=mgmt_headers, timeout=15)
                            
                            if mgmt_resp.status_code == 200:
                                mgmt_body = mgmt_resp.json()
                                asset_path = mgmt_body.get('properties', {}).get('path', '')
                                if asset_path:
                                    path_parts = str(asset_path).strip('/').split('/', 1)
                                    container_name = path_parts[0] if len(path_parts) > 0 else ''
                                    asset_base_path = path_parts[1] if len(path_parts) > 1 else ''
                                    server_traces.append(f"Queried asset path: container={container_name}, base_path={asset_base_path}")
                        except Exception as query_err:
                            server_traces.append(f" Could not query asset path: {query_err}")
                    
                    # Fallback if container name not determined
                    if not container_name:
                        container_name = data_container
                        server_traces.append(f" Using default container: {container_name}")
                    
                    server_traces.append(f" Final: storage_account_name={storage_account_name}, container_name={container_name}")
                    
                    if not storage_account_name or not container_name:
                        raise ValueError(f"Storage account configuration incomplete: account_name={storage_account_name}, container={container_name}")
                    
                    # Get storage token
                    storage_scope = 'https://storage.azure.com/.default'
                    storage_token = get_token_for_tenant(storage_scope, tenant_id, server_traces, purpose='storage-upload')
                    
                    if not storage_token:
                        raise ValueError("Could not obtain storage access token")
                    
                    # Build blob path for script (include asset base path if present)
                    if asset_base_path:
                        scripts_blob_path = f"{asset_base_path}/{run_prefix}/scripts/{script_name}"
                    else:
                        scripts_blob_path = f"{run_prefix}/scripts/{script_name}"
                    
                    server_traces.append(f"Blob path: {scripts_blob_path}")
                    
                    # Upload script to blob storage using REST API (more reliable than SDK)
                    import requests
                    upload_url = f"https://{storage_account_name}.blob.core.windows.net/{container_name}/{scripts_blob_path}"
                    upload_headers = {
                        'Authorization': f'Bearer {storage_token}',
                        'x-ms-blob-type': 'BlockBlob',
                        'x-ms-version': '2021-08-06',
                        'Content-Type': 'text/x-python'
                    }
                    upload_response = requests.put(upload_url, headers=upload_headers, data=code.encode('utf-8'))
                    
                    if upload_response.status_code not in (200, 201):
                        raise ValueError(f"Upload failed with status {upload_response.status_code}: {upload_response.text}")
                    
                    server_traces.append(f"Script uploaded to {storage_account_name}/{container_name}/{scripts_blob_path}")
                    
                    # Build Discovery URI for the scripts directory (not the specific file)
                    # Mount the directory so the script is accessible at /mnt/scripts/{script_name}
                    scripts_directory = f"{asset_base_path}/{run_prefix}/scripts" if asset_base_path else f"{run_prefix}/scripts"
                    
                    if inputs_asset:
                        asset_name = inputs_asset.split('/')[-1]
                        base_asset_rid = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/datacontainers/{data_container}/DataAssets/{asset_name}"
                    else:
                        base_asset_rid = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/datacontainers/{data_container}/DataAssets/{run_prefix}"
                    
                    # Strip duplicate asset name from path if present (asset name appears in both base_asset_rid and scripts_directory)
                    scripts_path_suffix = scripts_directory
                    try:
                        asset_name_check = base_asset_rid.split('/')[-1]
                        if scripts_path_suffix.startswith(asset_name_check + '/'):
                            scripts_path_suffix = scripts_path_suffix[len(asset_name_check) + 1:]
                        elif scripts_path_suffix == asset_name_check:
                            scripts_path_suffix = 'scripts'
                    except Exception:
                        pass
                    
                    script_discovery_uri = f"discovery://dataassets{base_asset_rid}/paths/{scripts_path_suffix}"
                    server_traces.append(f"Script Discovery URI: {script_discovery_uri}")
                    
                    # Upload shell wrapper for interactive mode (language-independent)
                    if shell_wrapper_content is not None:
                        wrapper_name = "tunnel-wrapper.sh"
                        if asset_base_path:
                            wrapper_blob_path = f"{asset_base_path}/{run_prefix}/scripts/{wrapper_name}"
                        else:
                            wrapper_blob_path = f"{run_prefix}/scripts/{wrapper_name}"
                        
                        wrapper_upload_url = f"https://{storage_account_name}.blob.core.windows.net/{container_name}/{wrapper_blob_path}"
                        wrapper_upload_headers = {
                            'Authorization': f'Bearer {storage_token}',
                            'x-ms-blob-type': 'BlockBlob',
                            'x-ms-version': '2021-08-06',
                            'Content-Type': 'application/x-sh'
                        }
                        wrapper_response = requests.put(
                            wrapper_upload_url, 
                            headers=wrapper_upload_headers, 
                            data=shell_wrapper_content.encode('utf-8')
                        )
                        
                        if wrapper_response.status_code in (200, 201):
                            server_traces.append(f"Shell wrapper uploaded to {wrapper_blob_path}")
                            logger.info(f"INTERACTIVE: Shell wrapper uploaded successfully")
                        else:
                            logger.warning(f"Shell wrapper upload failed: {wrapper_response.status_code}")
                            server_traces.append(f"  Warning: Shell wrapper upload failed, falling back to inline")
                    
                except Exception as upload_err:
                    logger.warning(f"Script upload failed: {upload_err}")
                    server_traces.append(f" X Script upload failed: {str(upload_err)}")
                    # If script is too large for inline, return error instead of falling back
                    if encoded_size > 12000:
                        error_msg = f"Script size ({encoded_size} chars encoded) exceeds 12KB limit and upload to Azure Blob Storage failed: {str(upload_err)}"
                        server_traces.append(f" X {error_msg}")
                        return {
                            "success": False,
                            "error": error_msg,
                            "agent_name": agent_name,
                            "traces": server_traces
                        }
            
            # Build output asset URI for mounting outputs
            # Note: data_container and azure_compute_config were already extracted at the top of this function
            outputs_asset = azure_compute_config.get('outputs_asset', '').strip()
            
            # Helper to build discovery:// URI from asset resource ID
            def build_discovery_asset_uri(asset_val: str) -> str:
                if not asset_val:
                    return None
                v = str(asset_val).strip()
                # If looks like a full resource id (starts with /subscriptions or contains providers/Microsoft.Discovery)
                if v.startswith('/'):
                    rid = v
                elif v.lower().startswith('subscriptions/'):
                    rid = '/' + v
                elif 'providers/microsoft.discovery' in v.lower():
                    rid = v if v.startswith('/') else '/' + v
                else:
                    # treat as simple asset name under the configured data container
                    rid = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/datacontainers/{data_container}/DataAssets/{v}"
                return f"discovery://dataassets{rid}"
            
            # Build base output URI
            output_uri_base = build_discovery_asset_uri(outputs_asset) if outputs_asset else None
            
            if not output_uri_base:
                # Fallback to per-run asset
                synthetic_rid = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/datacontainers/{data_container}/DataAssets/{run_prefix}-output"
                output_uri_base = f"discovery://dataassets{synthetic_rid}"
                server_traces.append(f" No outputs_asset configured, using per-run asset")
            
            # Append path suffix for this run
            output_suffix = f"{run_prefix}/output"
            output_uri = f"{output_uri_base}/paths/{output_suffix}"
            
            server_traces.append(f" Output mount: /output/ -> {output_uri}")
            
            # Build input mount if input_files_prefix provided
            input_data_mounts = []
            if input_files_prefix:
                inputs_asset = azure_compute_config.get('inputs_asset', '').strip()
                input_uri_base = build_discovery_asset_uri(inputs_asset) if inputs_asset else None
                
                if input_uri_base:
                    # Append the user-provided prefix to the inputs asset
                    # Note: input_files_prefix should be the remote_prefix returned from upload_input_files
                    # It represents the folder name where files were uploaded, relative to the asset's base path
                    input_uri = f"{input_uri_base}/paths/{input_files_prefix}"
                    input_data_mounts.append({
                        "mountPath": "/input/",
                        "uri": input_uri
                    })
                    server_traces.append(f" Input mount: /input/ -> {input_uri}")
                    server_traces.append(f"Input mount requires files to exist at blob path. If job fails with input errors, verify upload_input_files was called first.")
                else:
                    server_traces.append(f" No inputs_asset configured, skipping input mount. Configure inputs_asset in discovery_config.json to enable input file mounting.")
            else:
                server_traces.append(f"! No input_files_prefix provided - job will run without input file mounts. Use upload_input_files first if input files are needed.")
            
            # Add script mount (only for code-environment tools)
            if not is_action_based and script_discovery_uri:
                input_data_mounts.append({
                    "mountPath": "/mnt/scripts/",
                    "uri": script_discovery_uri
                })
                server_traces.append(f" Script mount: /mnt/scripts/ -> {script_discovery_uri}")
                # Update command to use uploaded script path
                # The command may have /input/script_name or just /script_name in template
                # Replace with /mnt/scripts/script_name
                if f"/input/{script_name}" in formatted_command:
                    formatted_command = formatted_command.replace(f"/input/{script_name}", f"/mnt/scripts/{script_name}")
                elif f"/{script_name}" in formatted_command:
                    formatted_command = formatted_command.replace(f"/{script_name}", f"/mnt/scripts/{script_name}")
                server_traces.append(f"Updated command: {formatted_command}")
                    
            elif is_action_based:
                # For action-based tools with interactive mode, we need to upload scripts too
                if shell_wrapper_content is not None and interactive_session is not None:
                    # Need to upload the script AND wrapper for interactive mode
                    # Upload script to blob storage
                    server_traces.append(f"Action-based tool with interactive mode: Uploading script and wrapper")
                    
                    # Upload the script file
                    blob_prefix_scripts = f"{run_prefix}/scripts"
                    script_blob_name = f"{blob_prefix_scripts}/{script_name}"
                    
                    blob_client = self._get_blob_client(
                        storage_account=storage_id,
                        container_name=data_container,
                        blob_name=script_blob_name
                    )
                    
                    # Upload script content
                    blob_client.upload_blob(code.encode('utf-8'), overwrite=True)
                    server_traces.append(f"  Script uploaded to: {script_blob_name}")
                    
                    # Upload shell wrapper
                    wrapper_blob_name = f"{blob_prefix_scripts}/tunnel-wrapper.sh"
                    wrapper_client = self._get_blob_client(
                        storage_account=storage_id,
                        container_name=data_container,
                        blob_name=wrapper_blob_name
                    )
                    wrapper_client.upload_blob(shell_wrapper_content.encode('utf-8'), overwrite=True)
                    server_traces.append(f"  Shell wrapper uploaded to: {wrapper_blob_name}")
                    
                    # Build script mount URI
                    inputs_asset = azure_compute_config.get('inputs_asset', '').strip()
                    script_uri_base = build_discovery_asset_uri(inputs_asset) if inputs_asset else None
                    if script_uri_base:
                        script_discovery_uri = f"{script_uri_base}/paths/{blob_prefix_scripts}"
                        input_data_mounts.append({
                            "mountPath": "/mnt/scripts/",
                            "uri": script_discovery_uri
                        })
                        server_traces.append(f" Script mount: /mnt/scripts/ -> {script_discovery_uri}")
                        
                        # Build proper command to run the script
                        formatted_command = f"python /mnt/scripts/{script_name}"
                        server_traces.append(f"Updated command: {formatted_command}")
                    else:
                        server_traces.append(f"! No inputs_asset configured for script mount")
                else:
                    server_traces.append(f"Action-based tool: No script upload needed")
                    server_traces.append(f"Final command: {formatted_command}")
            
            # Apply interactive mode wrapper AFTER script handling (for both action-based and code-environment)
            if shell_wrapper_content is not None and interactive_session is not None:
                tunnel_name = interactive_session.tunnel.tunnel_id
                original_command = formatted_command
                # The shell wrapper is uploaded to /mnt/scripts/tunnel-wrapper.sh
                # It takes the user command as arguments and handles tunnel setup
                # NOTE: Must use sh -c to handle env vars since container uses tini as init
                wrapper_path = "/mnt/scripts/tunnel-wrapper.sh"
                # Escape any single quotes in the original command
                escaped_original = original_command.replace("'", "'\\''")
                formatted_command = (
                    f"sh -c '"
                    f"TUNNEL_SESSION_ID={tunnel_name} "
                    f"TUNNEL_TIMEOUT_MINUTES={interactive_timeout_minutes} "
                    f"TUNNEL_MODE={interactive_mode} "
                    f"bash {wrapper_path} {escaped_original}'"
                )
                server_traces.append(f"Interactive: Wrapped command with shell tunnel")
                server_traces.append(f"  Original: {original_command}")
                server_traces.append(f"  Wrapped: {formatted_command}")
                logger.info(f"INTERACTIVE: Command wrapped: {formatted_command}")
            
            # Build request body
            request_body = {
                "toolId": tool_id,
                "command": formatted_command,
                "inputData": input_data_mounts,
                "outputData": [
                    {
                        "mountPath": "/output/",
                        "uri": output_uri
                    }
                ],
                "nodePoolIds": nodepool_ids,
                "storageId": storage_id
            }
            
            # Get Discovery API token using helper
            discovery_access_token = self._get_discovery_token(workspace_name, tenant_id, server_traces, purpose='discovery')
            
            # Submit job
            api_url = f"https://{workspace_name}.workspace.discovery.azure.com/tools/projects/{project_name}:run"
            discovery_headers = {
                'Authorization': f'Bearer {discovery_access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            server_traces.append(f"Submitting job to Discovery workspace: {workspace_name}/{project_name}")
            
            logger.info(f"Discovery job request body: {json.dumps(request_body, indent=2)}")
            discovery_response = requests.post(api_url, headers=discovery_headers, json=request_body, timeout=60)
            
            if discovery_response.status_code not in [200, 201, 202]:
                error_text = discovery_response.text
                server_traces.append(f" X Job submission failed: {discovery_response.status_code}")
                raise ValueError(f"Discovery API returned {discovery_response.status_code}: {error_text}")
            
            discovery_data = discovery_response.json()
            discovery_job_id = discovery_data.get('id', discovery_data.get('operationId', 'unknown'))
            status = discovery_data.get('status', 'submitted')
            
            server_traces.append(f"Job submitted successfully. Job ID: {discovery_job_id}")
            
            logger.info(f"Job submitted successfully: {discovery_job_id}")
            
            result = {
                "success": True,
                "discovery_job_id": discovery_job_id,
                "status": status,
                "agent_name": agent_name,
                "tool_name": tool_name,
                "nodepool_ids": nodepool_ids,
                "traces": server_traces,
                "submission_time": datetime.now(timezone.utc).isoformat()
            }
            
            # Add interactive session information if interactive mode enabled
            if interactive_mode != "none" and interactive_session is not None:
                # Update session with job ID
                interactive_session.job_id = discovery_job_id
                
                result["interactive_info"] = {
                    "enabled": True,
                    "mode": interactive_mode,
                    "session_id": interactive_session.session_id,
                    "tunnel_id": interactive_session.tunnel.tunnel_id,
                    "timeout_minutes": interactive_timeout_minutes,
                    "instructions": interactive_session.get_connection_instructions()
                }
                
                # Add access URL if available
                access_url = interactive_session.get_access_url()
                if access_url:
                    result["interactive_info"]["access_url"] = access_url
                
                server_traces.append(f"✅ Interactive session ready!")
                server_traces.append(f"   Mode: {interactive_mode}")
                server_traces.append(f"   Tunnel ID: {interactive_session.tunnel.tunnel_id}")
                for instruction in interactive_session.get_connection_instructions()[:3]:
                    server_traces.append(f"   {instruction}")
            
            # Add dependency information if this was a dependent job
            if depends_on_job_id:
                result['parent_job_id'] = depends_on_job_id
                if input_files_prefix:
                    # Reconstruct the output URI from input prefix - reuse already validated data_container
                    inputs_asset = azure_compute_config.get('inputs_asset', '').strip()
                    
                    # Build discovery:// URI
                    def build_discovery_asset_uri(asset_val: str) -> str:
                        if not asset_val:
                            return None
                        v = str(asset_val).strip()
                        if v.startswith('/'):
                            rid = v
                        elif v.lower().startswith('subscriptions/'):
                            rid = '/' + v
                        elif 'providers/microsoft.discovery' in v.lower():
                            rid = v if v.startswith('/') else '/' + v
                        else:
                            rid = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/datacontainers/{data_container}/DataAssets/{v}"
                        return f"discovery://dataassets{rid}"
                    
                    if inputs_asset:
                        input_uri_base = build_discovery_asset_uri(inputs_asset)
                        result['input_mounted_from'] = f"{input_uri_base}/paths/{input_files_prefix}"
            
            # For interactive mode, poll for tunnel auth info instead of waiting for job completion
            if interactive_mode != "none" and interactive_session is not None:
                server_traces.append(f"Waiting for tunnel auth info (polling job logs)...")
                logger.info(f"Interactive mode: polling for tunnel auth info for job {discovery_job_id}")
                
                # Poll logs until we find the auth code or timeout
                max_wait_seconds = 300  # 5 minutes max wait for tunnel to start
                poll_interval = 10  # Poll every 10 seconds
                start_time = datetime.now(timezone.utc)
                auth_url = None
                auth_code = None
                tunnel_ready = False
                
                while (datetime.now(timezone.utc) - start_time).total_seconds() < max_wait_seconds:
                    await asyncio.sleep(poll_interval)
                    
                    # Get current job logs
                    log_result = await self._get_job_logs(discovery_job_id, tail=200)
                    if not log_result.get('success'):
                        logger.warning(f"Failed to get logs: {log_result.get('error')}")
                        continue
                    
                    logs = log_result.get('logs', '')
                    
                    # Check job status first
                    status_result = await self._get_job_status(discovery_job_id, include_logs=False)
                    job_status = status_result.get('status', '')
                    
                    # Job failed or completed unexpectedly - stop polling
                    if job_status in ['Failed', 'Canceled']:
                        server_traces.append(f"❌ Job {job_status} before tunnel started")
                        result['tunnel_error'] = f"Job {job_status} before tunnel could start"
                        break
                    
                    # Look for auth info in logs
                    # Pattern: "[tunnel] Auth required: https://github.com/login/device" and "[tunnel] Auth code: XXXX-XXXX"
                    import re
                    auth_url_match = re.search(r'\[tunnel\] Auth required: (https://[^\s]+)', logs)
                    auth_code_match = re.search(r'\[tunnel\] Auth code: ([A-Z0-9]{4}-[A-Z0-9]{4})', logs)
                    
                    # Extract workspace directory from logs - multiple patterns to handle different log formats
                    workspace_dir = None
                    # Pattern 1: "Workspace directory:" or "Workspace path:" or "workspace path:"
                    workspace_match = re.search(r'(?:workspace\s+(?:directory|path)\s*:\s*)(/[^\s]+)', logs, re.IGNORECASE)
                    if workspace_match:
                        workspace_dir = workspace_match.group(1)
                    
                    # Pattern 2: Extract from "code --remote tunnel+{tunnel_name} /path" commands
                    if not workspace_dir:
                        code_cmd_match = re.search(r'code\s+--remote\s+tunnel\+\w+\s+(/[^\s]+)', logs)
                        if code_cmd_match:
                            workspace_dir = code_cmd_match.group(1)
                    
                    # Pattern 3: Extract from "select: /path" patterns
                    if not workspace_dir:
                        select_match = re.search(r'select:\s+(/[^\s]+)', logs)
                        if select_match:
                            workspace_dir = select_match.group(1)
                    
                    if auth_url_match:
                        auth_url = auth_url_match.group(1)
                    if auth_code_match:
                        auth_code = auth_code_match.group(1)
                    
                    # Check if tunnel is fully ready
                    if 'Tunnel ready' in logs or 'Open this link in your browser' in logs:
                        tunnel_ready = True
                    
                    # If we have auth info, we're done waiting
                    if auth_url and auth_code:
                        wait_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
                        server_traces.append(f"✅ Tunnel auth info found after {wait_seconds:.0f}s")
                        
                        result['interactive_info']['auth_required'] = True
                        result['interactive_info']['auth_url'] = auth_url
                        result['interactive_info']['auth_code'] = auth_code
                        result['interactive_info']['tunnel_status'] = 'awaiting_auth' if not tunnel_ready else 'ready'
                        result['interactive_info']['workspace_dir'] = workspace_dir or '/workspace'
                        
                        # Update instructions with actual auth info and workspace directory
                        tunnel_id = result['interactive_info'].get('tunnel_id', 'unknown')
                        ws_dir = workspace_dir or '/workspace'
                        result['interactive_info']['instructions'] = [
                            f"🔐 AUTHENTICATE: Go to {auth_url}",
                            f"📝 Enter code: {auth_code}",
                            "",
                            "OPTION 1 - Browser:",
                            f"  {result['interactive_info'].get('access_url', 'https://vscode.dev')}",
                            "",
                            "OPTION 2 - VS Code Desktop:",
                            f"  Install 'Remote - Tunnels' extension, then run:",
                            f"  code --remote tunnel+{tunnel_id} {ws_dir}",
                            "",
                            f"📁 Scripts in: {ws_dir}/scripts/ folder",
                            "▶️ Press F5 to attach debugger"
                        ]
                        result['interactive_info']['vscode_command'] = f"code --remote tunnel+{tunnel_id} {ws_dir}"
                        
                        logger.info(f"Tunnel auth info obtained: url={auth_url}, code={auth_code}")
                        break
                    
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    server_traces.append(f"  Polling... ({elapsed:.0f}s elapsed, status: {job_status})")
                
                else:
                    # Timeout reached
                    server_traces.append(f"⚠️ Timeout waiting for tunnel auth info ({max_wait_seconds}s)")
                    result['interactive_info']['tunnel_status'] = 'timeout'
                    result['interactive_info']['instructions'] = [
                        "Tunnel may still be starting. Use get_job_logs to check status.",
                        "Look for '[tunnel] Auth required:' and '[tunnel] Auth code:' in logs"
                    ]
                
                # Return now for interactive mode - don't wait for job completion
                return result
            
            # Wait for completion if requested
            if wait_for_completion:
                server_traces.append(f"Waiting for job completion (timeout: {timeout_seconds}s)...")
                logger.info(f"Waiting for job {discovery_job_id} to complete")
                
                wait_result = await self._wait_for_job(discovery_job_id, timeout_seconds)
                
                if wait_result.get('success'):
                    # Merge wait results into the submission result
                    result['final_status'] = wait_result.get('status')
                    result['wait_time_seconds'] = wait_result.get('wait_time_seconds')
                    
                    # Add timeout flag if present
                    if wait_result.get('timeout'):
                        result['timeout'] = True
                        result['timeout_message'] = wait_result.get('timeout_message')
                    
                    # Add completion timestamps
                    if 'last_action_at' in wait_result:
                        result['completed_at'] = wait_result['last_action_at']
                    
                    # Include error details if job failed
                    if wait_result.get('error_details'):
                        result['error_details'] = wait_result['error_details']
                    
                    # Include log samples from wait result
                    if 'log_head' in wait_result:
                        result['log_head'] = wait_result['log_head']
                    if 'log_tail' in wait_result:
                        result['log_tail'] = wait_result['log_tail']
                    
                    server_traces.append(f"Job completed with status: {result['final_status']}")
                else:
                    # Wait failed - include error but still return success for submission
                    result['wait_error'] = wait_result.get('error')
                    server_traces.append(f" Job submitted but wait failed: {wait_result.get('error')}")
            
            return result
            
        except Exception as e:
            logger.exception(f"Failed to submit job for agent {agent_name}")
            error_tracker.record_error("SubmitJobError", str(e), {"agent_name": agent_name})
            return {
                "success": False,
                "error": str(e),
                "agent_name": agent_name
            }

    async def _get_job_status(self, job_id: str, include_logs: bool = True, log_lines: int = 20) -> Dict[str, Any]:
        """Get the status of a Discovery job
        
        Args:
            job_id: The Discovery job/operation ID
            include_logs: Whether to retrieve recent logs (default: True). Set to False to avoid circular dependency.
            log_lines: Number of lines to include from beginning and end of logs (default: 20). 
                      If 0, logs are excluded. The method returns first N and last N lines.
            
        Returns:
            Dictionary with job status information including current state, details, and timestamps
        """
        try:
            import requests
            from datetime import datetime, timezone
            
            logger.info(f"Checking status for job: {job_id}")
            
            # Get and validate configuration using helper
            required_fields = ['tenant_id', 'workspace_name', 'project_name']
            _, _, config_vals = self._get_azure_config_with_validation(required_fields)
            
            tenant_id = config_vals['tenant_id']
            workspace_name = config_vals['workspace_name']
            project_name = config_vals['project_name']
            
            server_traces = []
            server_traces.append(f" Checking status for job: {job_id}")
            
            # Get Discovery API token using helper
            discovery_access_token = self._get_discovery_token(workspace_name, tenant_id, server_traces, purpose='discovery_status')
            
            # Build status URL
            status_url = f"https://{workspace_name}.workspace.discovery.azure.com/tools/projects/{project_name}/operations/{job_id}"
            headers = {
                'Authorization': f'Bearer {discovery_access_token}',
                'Accept': 'application/json'
            }
            
            server_traces.append(f" Querying job status from Discovery API...")
            
            # Query the status
            response = requests.get(status_url, headers=headers, timeout=30)
            
            if response.status_code == 404:
                server_traces.append(f" X Job not found: {job_id}")
                raise ValueError(f"Job with ID '{job_id}' not found")
            
            if response.status_code != 200:
                error_text = response.text
                server_traces.append(f" X Failed to get job status: {response.status_code}")
                raise ValueError(f"Discovery API returned {response.status_code}: {error_text}")
            
            job_data = response.json()
            status = job_data.get('status', 'unknown')
            
            server_traces.append(f"Job status retrieved: {status}")
            
            # Extract key information
            result = {
                "success": True,
                "job_id": job_id,
                "status": status,
                "workspace": workspace_name,
                "project": project_name,
                "traces": server_traces,
                "query_time": datetime.now(timezone.utc).isoformat()
            }
            
            # Add optional fields if present
            if 'createdDateTime' in job_data:
                result['created_at'] = job_data['createdDateTime']
            
            if 'lastActionDateTime' in job_data:
                result['last_action_at'] = job_data['lastActionDateTime']
            
            if 'resourceLocation' in job_data:
                result['resource_location'] = job_data['resourceLocation']
            
            # Include error information if job failed
            if status in ['Failed', 'Canceled']:
                if 'error' in job_data:
                    result['error_details'] = job_data['error']
                    server_traces.append(f" Job {status.lower()}: {job_data.get('error', {}).get('message', 'No error message')}")
                
                # Extract toolReport logs if available (provides actual execution errors)
                result_data = job_data.get('result', {})
                tool_report = result_data.get('toolReport', {})
                if tool_report:
                    tool_logs = tool_report.get('logs', '')
                    if tool_logs:
                        result['tool_error_logs'] = tool_logs
                        server_traces.append(f"Tool execution logs available")
                        # Add first line of error to traces for visibility
                        error_lines = tool_logs.strip().split('\n')
                        if error_lines:
                            first_error = error_lines[0]
                            if len(error_lines) > 1:
                                # Find actual error message (skip "worker:" prefix)
                                for line in error_lines:
                                    if line.strip() and not line.strip().endswith(':'):
                                        first_error = line.strip()
                                        break
                            server_traces.append(f" X Tool error: {first_error}")
                    
                    # Also include other toolReport fields
                    if 'statusInformation' in tool_report and tool_report['statusInformation']:
                        result['tool_status_info'] = tool_report['statusInformation']
                    if 'percentageComplete' in tool_report:
                        result['tool_percentage_complete'] = tool_report['percentageComplete']
            
            # Try to retrieve head and tail of logs for quick troubleshooting (if not disabled to avoid circular dependency)
            if include_logs and log_lines > 0:
                try:
                    # Get full logs to extract head and tail (use large tail value to get all logs)
                    log_result = await self._get_job_logs(job_id, tail=1000000)
                    if log_result.get('success') and log_result.get('logs'):
                        logs = log_result['logs']
                        total_lines = log_result.get('line_count', 0)
                        
                        # Split logs into lines
                        log_lines_list = logs.split('\n') if logs else []
                        
                        if len(log_lines_list) <= log_lines * 2:
                            # Logs are short enough to include entirely
                            result['log_sample'] = logs
                            result['log_truncated'] = False
                        else:
                            # Extract head and tail
                            head = '\n'.join(log_lines_list[:log_lines])
                            tail_lines = '\n'.join(log_lines_list[-log_lines:])
                            truncated_count = len(log_lines_list) - (log_lines * 2)
                            
                            result['log_sample'] = (
                                f"{head}\n"
                                f"\n... [{truncated_count} lines truncated] ...\n\n"
                                f"{tail_lines}"
                            )
                            result['log_truncated'] = True
                            result['log_truncated_lines'] = truncated_count
                        
                        result['log_total_lines'] = total_lines
                        server_traces.append(f"Retrieved log sample ({log_lines} head + {log_lines} tail lines, {total_lines} total)")
                except Exception as log_e:
                    logger.debug(f"Could not retrieve logs for job {job_id}: {log_e}")
                    result['log_retrieval_note'] = "Logs not available or job hasn't started yet"
            
            # Include full details for debugging
            result['full_details'] = job_data
            
            logger.info(f"Job {job_id} status: {status}")
            
            return result
            
        except Exception as e:
            logger.exception(f"Failed to get status for job {job_id}")
            error_tracker.record_error("GetJobStatusError", str(e), {"job_id": job_id})
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }

    async def _wait_for_job(self, job_id: str, timeout_seconds: int = 3600) -> Dict[str, Any]:
        """Wait for a job to complete by polling until it reaches a terminal state
        
        Args:
            job_id: The Discovery job/operation ID to wait for
            timeout_seconds: Maximum time to wait in seconds (default: 3600 = 1 hour)
            
        Returns:
            Dictionary with final job status (same format as _get_job_status)
        """
        try:
            import asyncio
            from datetime import datetime, timezone
            
            logger.info(f"Waiting for job {job_id} to complete (timeout: {timeout_seconds}s)")
            
            start_time = datetime.now(timezone.utc)
            poll_interval = 1  # Poll every second
            terminal_states = {'Succeeded', 'Failed', 'Canceled'}
            
            iterations = 0
            max_iterations = timeout_seconds // poll_interval
            
            while iterations < max_iterations:
                # Get current job status (without logs for faster polling)
                status_result = await self._get_job_status(job_id, include_logs=False)
                
                if not status_result.get('success'):
                    # If we can't get status, return the error
                    return status_result
                
                current_status = status_result.get('status', 'unknown')
                
                # Check if job has reached a terminal state
                if current_status in terminal_states:
                    # Job completed - get final status with logs
                    final_result = await self._get_job_status(job_id, include_logs=True)
                    
                    elapsed_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
                    final_result['wait_time_seconds'] = round(elapsed_seconds, 2)
                    final_result['poll_iterations'] = iterations + 1
                    
                    logger.info(f"Job {job_id} completed with status '{current_status}' after {elapsed_seconds:.1f}s")
                    return final_result
                
                # Job still running - wait before next poll
                if iterations % 10 == 0:  # Log every 10 seconds
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    logger.debug(f"Job {job_id} still {current_status} after {elapsed:.0f}s")
                
                await asyncio.sleep(poll_interval)
                iterations += 1
            
            # Timeout reached
            elapsed_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
            logger.warning(f"Job {job_id} did not complete within {timeout_seconds}s")
            
            # Get final status even though we timed out
            final_result = await self._get_job_status(job_id, include_logs=True)
            final_result['timeout'] = True
            final_result['wait_time_seconds'] = round(elapsed_seconds, 2)
            final_result['timeout_message'] = f"Job did not complete within {timeout_seconds} seconds"
            
            return final_result
            
        except Exception as e:
            logger.exception(f"Error waiting for job {job_id}")
            error_tracker.record_error("WaitForJobError", str(e), {"job_id": job_id})
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }

    async def _cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a running or queued Discovery job
        
        Args:
            job_id: The Discovery job/operation ID to cancel
            
        Returns:
            Dictionary with cancellation status and result
        """
        try:
            import requests
            from datetime import datetime, timezone
            
            logger.info(f"Canceling job: {job_id}")
            
            # Get and validate configuration
            required_fields = ['tenant_id', 'workspace_name', 'project_name']
            _, _, config_vals = self._get_azure_config_with_validation(required_fields)
            
            tenant_id = config_vals['tenant_id']
            workspace_name = config_vals['workspace_name']
            project_name = config_vals['project_name']
            
            server_traces = []
            server_traces.append(f"🛑 Canceling job: {job_id}")
            
            # Get Discovery API token
            discovery_access_token = self._get_discovery_token(workspace_name, tenant_id, server_traces, purpose='discovery_cancel')

            # Build URLs:
            # - Cancel action endpoint: POST .../operations/{operationId}:cancel
            # - Operation endpoint (for status): GET .../operations/{operationId}
            cancel_action_url = f"https://{workspace_name}.workspace.discovery.azure.com/tools/projects/{project_name}/operations/{job_id}:cancel"
            operation_url = f"https://{workspace_name}.workspace.discovery.azure.com/tools/projects/{project_name}/operations/{job_id}"
            post_headers = {
                'Authorization': f'Bearer {discovery_access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            get_headers = {
                'Authorization': f'Bearer {discovery_access_token}',
                'Accept': 'application/json'
            }
            
            server_traces.append(f" Sending cancellation request...")

            # Send POST request to the cancel action endpoint
            response = requests.post(cancel_action_url, headers=post_headers, json={}, timeout=30)
            
            if response.status_code == 404:
                server_traces.append(f" X Job not found: {job_id}")
                return {
                    "success": False,
                    "error": f"Job with ID '{job_id}' not found",
                    "job_id": job_id,
                    "traces": server_traces
                }
            
            if response.status_code not in [200, 202, 204]:
                error_text = response.text
                server_traces.append(f" X Failed to cancel job: {response.status_code}")
                return {
                    "success": False,
                    "error": f"Discovery API returned {response.status_code}: {error_text}",
                    "job_id": job_id,
                    "traces": server_traces
                }
            
            server_traces.append(f"Job cancellation request accepted")
            
            # Get updated status to confirm cancellation
            status_response = requests.get(operation_url, headers=get_headers, timeout=30)
            current_status = "Unknown"
            if status_response.status_code == 200:
                job_data = status_response.json()
                current_status = job_data.get('status', 'Unknown')
                server_traces.append(f" Current job status: {current_status}")
            elif status_response.status_code == 404:
                server_traces.append(" Current job status: NotFound")
            
            logger.info(f"Job {job_id} cancellation requested, status: {current_status}")
            
            return {
                "success": True,
                "job_id": job_id,
                "message": "Job cancellation requested successfully",
                "current_status": current_status,
                "workspace": workspace_name,
                "project": project_name,
                "traces": server_traces,
                "canceled_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.exception(f"Failed to cancel job {job_id}")
            error_tracker.record_error("CancelJobError", str(e), {"job_id": job_id})
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }

    async def _check_interactive_prerequisites(self) -> Dict[str, Any]:
        """Check if Dev Tunnels CLI is installed and ready for interactive mode.
        
        Returns:
            Dictionary with ready status, installation status, and instructions.
        """
        try:
            if not HAS_DEVTUNNEL:
                return {
                    "success": True,
                    "ready": False,
                    "error": "Dev Tunnel module not available",
                    "instructions": "The devtunnel module is not installed. Check agent-workbench installation."
                }
            
            session_manager = InteractiveSessionManager(logger=lambda msg: logger.info(f"[tunnel] {msg}"))
            prereq = session_manager.check_prerequisites()
            
            return {
                "success": True,
                "ready": prereq["ready"],
                "status": prereq["status"],
                "error": prereq.get("error"),
                "instructions": prereq["instructions"]
            }
            
        except Exception as e:
            logger.exception("Failed to check interactive prerequisites")
            return {
                "success": False,
                "ready": False,
                "error": str(e),
                "instructions": "An unexpected error occurred while checking Dev Tunnel status."
            }

    async def _get_interactive_session(self, job_id: str) -> Dict[str, Any]:
        """Get connection information for an interactive session associated with a job.
        
        Args:
            job_id: The job ID to get session info for.
            
        Returns:
            Dictionary with session info and connection instructions.
        """
        try:
            if not HAS_DEVTUNNEL:
                return {
                    "success": False,
                    "error": "Dev Tunnel module not available",
                    "job_id": job_id
                }
            
            # Check if we have a session manager with active sessions
            if not hasattr(self, '_interactive_session_manager'):
                return {
                    "success": False,
                    "error": "No interactive sessions found. Submit a job with interactive_mode enabled first.",
                    "job_id": job_id
                }
            
            session = self._interactive_session_manager.get_session_by_job(job_id)
            
            if not session:
                return {
                    "success": False,
                    "error": f"No interactive session found for job {job_id}",
                    "job_id": job_id,
                    "hint": "Make sure the job was submitted with interactive_mode='vscode' or 'novnc'"
                }
            
            return {
                "success": True,
                "job_id": job_id,
                "session": session.to_dict()
            }
            
        except Exception as e:
            logger.exception(f"Failed to get interactive session for job {job_id}")
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }

    async def _close_interactive_session(self, job_id: str) -> Dict[str, Any]:
        """Close an interactive session, cleanup the Dev Tunnel, and CANCEL the job.
        
        This is the proper way to end a debugging session - it:
        1. Closes the local session tracking
        2. Cancels the running job to free the container
        
        Args:
            job_id: The job ID whose session should be closed.
            
        Returns:
            Dictionary with closure status.
        """
        try:
            traces = []
            
            # Step 1: Clean up local session tracking (optional, may not exist)
            if HAS_DEVTUNNEL and hasattr(self, '_interactive_session_manager'):
                closed = self._interactive_session_manager.close_session_by_job(job_id)
                if closed:
                    traces.append("✓ Local session tracking cleaned up")
                else:
                    traces.append("ℹ No local session found (may have been created in different server instance)")
            
            # Step 2: Cancel the job to free the container
            traces.append(f"Canceling job {job_id} to free container resources...")
            cancel_result = await self._cancel_job(job_id)
            
            if cancel_result.get('success'):
                traces.append(f"✓ Job canceled successfully")
                return {
                    "success": True,
                    "message": f"Interactive session closed and job {job_id} canceled",
                    "job_id": job_id,
                    "job_status": cancel_result.get('status', 'Canceled'),
                    "traces": traces
                }
            else:
                # Job might already be completed or canceled
                job_status = await self._get_job_status(job_id, include_logs=False)
                current_status = job_status.get('status', 'Unknown')
                
                if current_status in ['Succeeded', 'Failed', 'Canceled']:
                    traces.append(f"ℹ Job already in terminal state: {current_status}")
                    return {
                        "success": True,
                        "message": f"Interactive session closed (job was already {current_status})",
                        "job_id": job_id,
                        "job_status": current_status,
                        "traces": traces
                    }
                else:
                    traces.append(f"⚠ Could not cancel job: {cancel_result.get('error')}")
                    return {
                        "success": False,
                        "error": f"Failed to cancel job: {cancel_result.get('error')}",
                        "job_id": job_id,
                        "job_status": current_status,
                        "traces": traces
                    }
            
        except Exception as e:
            logger.exception(f"Failed to close interactive session for job {job_id}")
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }

    async def _cleanup_files(self, path: str, location: str, recursive: bool = False, confirm: bool = False) -> Dict[str, Any]:
        """Delete files or directories from local filesystem or Azure Storage
        
        Args:
            path: Path to file or directory to delete
            location: 'local' or 'remote'
            recursive: Whether to recursively delete directories
            confirm: Safety check - must be true to proceed
            
        Returns:
            Dictionary with cleanup results
        """
        try:
            import shutil
            from pathlib import Path
            
            logger.info(f"Cleanup requested: path={path}, location={location}, recursive={recursive}")
            
            # Safety check
            if not confirm:
                return {
                    "success": False,
                    "error": "Cleanup not confirmed. Set confirm=true to proceed with deletion.",
                    "path": path,
                    "location": location,
                    "warning": "Deletions are permanent and cannot be undone."
                }
            
            server_traces = []
            server_traces.append(f"🗑️ Cleanup request: {location} path '{path}'")
            
            if location == "local":
                # Local filesystem cleanup
                # Get MCP server directory for resolving relative paths
                mcp_server_dir = Path(os.path.dirname(os.path.abspath(__file__)))

                # Resolve relative paths against MCP server directory (cross-platform)
                target_path = Path(path)
                if not target_path.is_absolute():
                    target_path = mcp_server_dir / target_path
                target_path = target_path.resolve()

                if not target_path.exists():
                    return {
                        "success": False,
                        "error": f"Path does not exist: {path}",
                        "path": str(target_path),
                        "traces": server_traces
                    }

                # Safety check - don't delete critical system directories
                # Works on Windows, Linux, and macOS
                abs_path = str(target_path)
                abs_path_lower = abs_path.lower()

                # Define critical system paths that should never be deleted
                # Check exact matches for root paths
                root_paths = ['/', 'c:\\', 'd:\\', 'e:\\']
                if abs_path_lower.rstrip('\\').rstrip('/') in root_paths:
                    return {
                        "success": False,
                        "error": f"Refusing to delete root path: {abs_path}",
                        "path": abs_path,
                        "traces": server_traces
                    }

                # Check if path is within protected system directories
                protected_prefixes = [
                    # Windows system directories
                    'c:\\windows', 'c:\\program files', 'c:\\program files (x86)',
                    'c:\\programdata', 'c:\\users\\default', 'c:\\users\\public',
                    # Linux/macOS system directories
                    '/usr', '/etc', '/var', '/bin', '/sbin', '/lib', '/lib64',
                    '/boot', '/dev', '/proc', '/sys', '/opt',
                    # macOS specific
                    '/system', '/library', '/applications',
                ]
                for prefix in protected_prefixes:
                    # Normalize path separators for comparison
                    norm_prefix = prefix.replace('/', os.sep).replace('\\', os.sep)
                    if abs_path_lower.startswith(norm_prefix.lower() + os.sep) or abs_path_lower == norm_prefix.lower():
                        return {
                            "success": False,
                            "error": f"Refusing to delete system path: {abs_path}",
                            "path": abs_path,
                            "traces": server_traces
                        }
                
                try:
                    if target_path.is_file():
                        target_path.unlink()
                        server_traces.append(f"Deleted file: {path}")
                        return {
                            "success": True,
                            "message": f"File deleted: {path}",
                            "path": str(target_path),
                            "type": "file",
                            "traces": server_traces
                        }
                    elif target_path.is_dir():
                        if recursive:
                            shutil.rmtree(target_path)
                            server_traces.append(f"Deleted directory (recursive): {path}")
                            return {
                                "success": True,
                                "message": f"Directory deleted recursively: {path}",
                                "path": str(target_path),
                                "type": "directory",
                                "traces": server_traces
                            }
                        else:
                            # Try to delete if empty
                            target_path.rmdir()
                            server_traces.append(f"Deleted empty directory: {path}")
                            return {
                                "success": True,
                                "message": f"Empty directory deleted: {path}",
                                "path": str(target_path),
                                "type": "directory",
                                "traces": server_traces
                            }
                    else:
                        return {
                            "success": False,
                            "error": f"Path is neither a file nor directory: {path}",
                            "path": str(target_path),
                            "traces": server_traces
                        }
                
                except OSError as e:
                    if "not empty" in str(e).lower():
                        return {
                            "success": False,
                            "error": f"Directory not empty. Use recursive=true to delete contents: {e}",
                            "path": str(target_path),
                            "traces": server_traces
                        }
                    raise
            
            elif location == "remote":
                # Azure Storage cleanup
                required_fields = ['tenant_id', 'subscription_id', 'resource_group', 'storage_account', 'discovery_storage']
                _, _, config_vals = self._get_azure_config_with_validation(required_fields)
                
                tenant_id = config_vals['tenant_id']
                storage_account = config_vals['storage_account']
                
                # Parse the path - could be discovery:// URI or blob path
                if path.startswith('discovery://dataassets/'):
                    # Extract blob path from discovery URI
                    # Format: discovery://dataassets/.../DataAssets/workbench/paths/run-xxx/output
                    match = re.search(r'DataAssets/(.+)$', path)
                    if match:
                        blob_path = match.group(1)
                    else:
                        return {
                            "success": False,
                            "error": f"Could not parse discovery URI: {path}",
                            "path": path,
                            "traces": server_traces
                        }
                else:
                    blob_path = path.lstrip('/')
                
                # Get storage token
                from azure_auth_helpers import get_token_for_tenant
                storage_scope = 'https://storage.azure.com/.default'
                storage_token = get_token_for_tenant(storage_scope, tenant_id, server_traces, purpose='storage_cleanup')
                
                if not storage_token:
                    return {
                        "success": False,
                        "error": "Could not obtain storage access token",
                        "path": path,
                        "traces": server_traces
                    }
                
                # Use Azure Storage Blob API to delete
                import requests
                container_name = "workbench"  # Assuming workbench container
                
                if recursive and not blob_path.endswith('/'):
                    # List and delete all blobs with this prefix
                    list_url = f"https://{storage_account}.blob.core.windows.net/{container_name}"
                    list_params = {
                        'restype': 'container',
                        'comp': 'list',
                        'prefix': blob_path
                    }
                    list_headers = {
                        'Authorization': f'Bearer {storage_token}',
                        'x-ms-version': '2021-08-06'
                    }
                    
                    list_response = requests.get(list_url, params=list_params, headers=list_headers, timeout=30)
                    if list_response.status_code != 200:
                        return {
                            "success": False,
                            "error": f"Could not list blobs: {list_response.status_code}",
                            "path": path,
                            "traces": server_traces
                        }
                    
                    # Parse XML response to get blob names
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(list_response.content)
                    blobs = root.findall('.//{http://schemas.microsoft.com/2003/10/Serialization/Arrays}Name')
                    
                    deleted_count = 0
                    for blob in blobs:
                        blob_name = blob.text
                        delete_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/{blob_name}"
                        delete_headers = {
                            'Authorization': f'Bearer {storage_token}',
                            'x-ms-version': '2021-08-06'
                        }
                        delete_response = requests.delete(delete_url, headers=delete_headers, timeout=30)
                        if delete_response.status_code in [200, 202, 204]:
                            deleted_count += 1
                    
                    server_traces.append(f"Deleted {deleted_count} blob(s) with prefix: {blob_path}")
                    return {
                        "success": True,
                        "message": f"Deleted {deleted_count} blob(s) from Azure Storage",
                        "path": path,
                        "blob_path": blob_path,
                        "deleted_count": deleted_count,
                        "traces": server_traces
                    }
                else:
                    # Delete single blob
                    delete_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/{blob_path}"
                    delete_headers = {
                        'Authorization': f'Bearer {storage_token}',
                        'x-ms-version': '2021-08-06'
                    }
                    
                    delete_response = requests.delete(delete_url, headers=delete_headers, timeout=30)
                    if delete_response.status_code in [200, 202, 204]:
                        server_traces.append(f"Deleted blob: {blob_path}")
                        return {
                            "success": True,
                            "message": f"Blob deleted from Azure Storage: {blob_path}",
                            "path": path,
                            "blob_path": blob_path,
                            "traces": server_traces
                        }
                    elif delete_response.status_code == 404:
                        return {
                            "success": False,
                            "error": f"Blob not found: {blob_path}",
                            "path": path,
                            "traces": server_traces
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"Failed to delete blob: {delete_response.status_code}",
                            "path": path,
                            "traces": server_traces
                        }
            else:
                return {
                    "success": False,
                    "error": f"Invalid location: {location}. Must be 'local' or 'remote'.",
                    "path": path,
                    "traces": server_traces
                }
        
        except Exception as e:
            logger.exception(f"Failed to cleanup files: {path}")
            error_tracker.record_error("CleanupFilesError", str(e), {"path": path, "location": location})
            return {
                "success": False,
                "error": str(e),
                "path": path,
                "location": location
            }

    async def _cleanup_folder(self, folder_path: str, location: str, confirm: bool = False) -> Dict[str, Any]:
        """Delete an entire folder and all its contents
        
        Args:
            folder_path: Path to folder to delete
            location: 'local' or 'remote'
            confirm: Safety check - must be true to proceed
            
        Returns:
            Dictionary with cleanup results
        """
        try:
            import shutil
            from pathlib import Path
            
            logger.info(f"Cleanup folder requested: folder_path={folder_path}, location={location}")
            
            # Safety check
            if not confirm:
                return {
                    "success": False,
                    "error": "Cleanup not confirmed. Set confirm=true to proceed with deletion.",
                    "folder_path": folder_path,
                    "location": location,
                    "warning": " This will permanently delete the entire folder and all its contents. Cannot be undone."
                }
            
            server_traces = []
            server_traces.append(f"🗑️ Folder cleanup request: {location} folder '{folder_path}'")
            
            if location == "local":
                # Local filesystem cleanup
                # Get MCP server directory for resolving relative paths
                mcp_server_dir = Path(os.path.dirname(os.path.abspath(__file__)))

                # Resolve relative paths against MCP server directory (cross-platform)
                target_path = Path(folder_path)
                if not target_path.is_absolute():
                    target_path = mcp_server_dir / target_path
                target_path = target_path.resolve()

                if not target_path.exists():
                    return {
                        "success": False,
                        "error": f"Folder does not exist: {folder_path}",
                        "folder_path": str(target_path),
                        "traces": server_traces
                    }

                if not target_path.is_dir():
                    return {
                        "success": False,
                        "error": f"Path is not a directory: {folder_path}",
                        "folder_path": str(target_path),
                        "traces": server_traces
                    }

                # Safety check - don't delete critical system directories
                # Works on Windows, Linux, and macOS
                abs_path = str(target_path)
                abs_path_lower = abs_path.lower()

                # Define critical system paths that should never be deleted
                # Check exact matches for root paths
                root_paths = ['/', 'c:\\', 'd:\\', 'e:\\']
                if abs_path_lower.rstrip('\\').rstrip('/') in root_paths:
                    return {
                        "success": False,
                        "error": f"Refusing to delete root path: {abs_path}",
                        "folder_path": abs_path,
                        "traces": server_traces
                    }

                # Check if path is within protected system directories
                protected_prefixes = [
                    # Windows system directories
                    'c:\\windows', 'c:\\program files', 'c:\\program files (x86)',
                    'c:\\programdata', 'c:\\users\\default', 'c:\\users\\public',
                    # Linux/macOS system directories
                    '/usr', '/etc', '/var', '/bin', '/sbin', '/lib', '/lib64',
                    '/boot', '/dev', '/proc', '/sys', '/opt',
                    # macOS specific
                    '/system', '/library', '/applications',
                ]
                for prefix in protected_prefixes:
                    # Normalize path separators for comparison
                    norm_prefix = prefix.replace('/', os.sep).replace('\\', os.sep)
                    if abs_path_lower.startswith(norm_prefix.lower() + os.sep) or abs_path_lower == norm_prefix.lower():
                        return {
                            "success": False,
                            "error": f"Refusing to delete system directory: {abs_path}",
                            "folder_path": abs_path,
                            "traces": server_traces
                        }
                
                # Count files before deletion
                file_count = sum(1 for _ in target_path.rglob('*') if _.is_file())
                dir_count = sum(1 for _ in target_path.rglob('*') if _.is_dir())
                
                try:
                    shutil.rmtree(target_path)
                    server_traces.append(f"Deleted folder: {folder_path} ({file_count} files, {dir_count} subdirs)")
                    
                    return {
                        "success": True,
                        "message": f"Folder deleted successfully: {folder_path}",
                        "folder_path": str(target_path),
                        "files_deleted": file_count,
                        "subdirs_deleted": dir_count,
                        "total_items_deleted": file_count + dir_count,
                        "traces": server_traces
                    }
                
                except OSError as e:
                    return {
                        "success": False,
                        "error": f"Failed to delete folder: {e}",
                        "folder_path": str(target_path),
                        "traces": server_traces
                    }
            
            elif location == "remote":
                # Azure Storage cleanup - delete folder (all blobs with prefix)
                required_fields = ['tenant_id', 'subscription_id', 'resource_group', 'storage_account', 'discovery_storage']
                _, _, config_vals = self._get_azure_config_with_validation(required_fields)
                
                tenant_id = config_vals['tenant_id']
                storage_account = config_vals['storage_account']
                
                # Parse the path - could be discovery:// URI or blob path
                if folder_path.startswith('discovery://dataassets/'):
                    # Extract blob path from discovery URI
                    match = re.search(r'DataAssets/(.+)$', folder_path)
                    if match:
                        blob_prefix = match.group(1)
                    else:
                        return {
                            "success": False,
                            "error": f"Could not parse discovery URI: {folder_path}",
                            "folder_path": folder_path,
                            "traces": server_traces
                        }
                else:
                    blob_prefix = folder_path.lstrip('/')
                
                # Ensure prefix ends with / to represent a folder
                if not blob_prefix.endswith('/'):
                    blob_prefix += '/'
                
                # Get storage token
                from azure_auth_helpers import get_token_for_tenant
                storage_scope = 'https://storage.azure.com/.default'
                storage_token = get_token_for_tenant(storage_scope, tenant_id, server_traces, purpose='storage_folder_cleanup')
                
                if not storage_token:
                    return {
                        "success": False,
                        "error": "Could not obtain storage access token",
                        "folder_path": folder_path,
                        "traces": server_traces
                    }
                
                # List and delete all blobs with this prefix
                import requests
                container_name = "workbench"  # Assuming workbench container
                
                list_url = f"https://{storage_account}.blob.core.windows.net/{container_name}"
                list_params = {
                    'restype': 'container',
                    'comp': 'list',
                    'prefix': blob_prefix
                }
                list_headers = {
                    'Authorization': f'Bearer {storage_token}',
                    'x-ms-version': '2021-08-06'
                }
                
                list_response = requests.get(list_url, params=list_params, headers=list_headers, timeout=30)
                if list_response.status_code != 200:
                    return {
                        "success": False,
                        "error": f"Could not list blobs in folder: {list_response.status_code}",
                        "folder_path": folder_path,
                        "traces": server_traces
                    }
                
                # Parse blob names from XML response
                import xml.etree.ElementTree as ET
                root = ET.fromstring(list_response.content)
                blobs = root.findall('.//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}Name')
                
                if not blobs:
                    return {
                        "success": False,
                        "error": f"No blobs found with prefix: {blob_prefix}",
                        "folder_path": folder_path,
                        "traces": server_traces
                    }
                
                # Delete each blob
                deleted_count = 0
                failed_deletions = []
                
                for blob_elem in blobs:
                    blob_name = blob_elem.text
                    delete_url = f"https://{storage_account}.blob.core.windows.net/{container_name}/{blob_name}"
                    delete_headers = {
                        'Authorization': f'Bearer {storage_token}',
                        'x-ms-version': '2021-08-06'
                    }
                    
                    delete_response = requests.delete(delete_url, headers=delete_headers, timeout=30)
                    if delete_response.status_code in [200, 202, 204]:
                        deleted_count += 1
                    else:
                        failed_deletions.append(blob_name)
                
                server_traces.append(f"Deleted folder from Azure Storage: {blob_prefix} ({deleted_count} blobs)")
                
                result = {
                    "success": True,
                    "message": f"Deleted folder from Azure Storage: {deleted_count} blob(s)",
                    "folder_path": folder_path,
                    "blob_prefix": blob_prefix,
                    "blobs_deleted": deleted_count,
                    "traces": server_traces
                }
                
                if failed_deletions:
                    result["warning"] = f"Failed to delete {len(failed_deletions)} blob(s)"
                    result["failed_deletions"] = failed_deletions
                
                return result
            
            else:
                return {
                    "success": False,
                    "error": f"Invalid location: {location}. Must be 'local' or 'remote'.",
                    "folder_path": folder_path,
                    "traces": server_traces
                }
        
        except Exception as e:
            logger.exception(f"Failed to cleanup folder: {folder_path}")
            error_tracker.record_error("CleanupFolderError", str(e), {"folder_path": folder_path, "location": location})
            return {
                "success": False,
                "error": str(e),
                "folder_path": folder_path,
                "location": location
            }

    async def _create_investigation(self, description: Optional[str] = None) -> Dict[str, Any]:
        """Create a new investigation ID for organizing work
        
        Args:
            description: Optional description of the investigation
            
        Returns:
            Dictionary with investigation_id and metadata
        """
        try:
            from datetime import datetime, timezone
            from pathlib import Path
            import os
            import re
            
            # Get investigations directory (inside mcp-server folder)
            mcp_server_dir = os.path.dirname(os.path.abspath(__file__))
            investigations_dir = Path(mcp_server_dir) / "investigations"

            # Ensure investigations directory exists
            investigations_dir.mkdir(parents=True, exist_ok=True)
            
            # Scan existing investigation folders to find the highest number
            max_num = 0
            if investigations_dir.exists():
                for item in investigations_dir.iterdir():
                    if item.is_dir():
                        match = re.match(r'^inv_(\d+)$', item.name)
                        if match:
                            num = int(match.group(1))
                            max_num = max(max_num, num)
            
            # Set counter to max + 1
            self._investigation_counter = max_num + 1
            investigation_id = f"inv_{self._investigation_counter:03d}"
            
            # Set as current investigation
            self._current_investigation_id = investigation_id
            
            # Build investigation directory structure
            investigation_base = investigations_dir / investigation_id
            folder_paths = {
                "base": str(investigation_base),
                "scripts": str(investigation_base / "scripts"),
                "inputs": str(investigation_base / "inputs"),
                "outputs": str(investigation_base / "outputs"),
                "tests": str(investigation_base / "tests"),
                "docs": str(investigation_base / "docs"),
                "config": str(investigation_base / "config")
            }

            # Create directory structure on disk
            for path_str in folder_paths.values():
                Path(path_str).mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now(timezone.utc).isoformat()
            
            logger.info(f"Created investigation: {investigation_id}")
            
            return {
                "success": True,
                "investigation_id": investigation_id,
                "description": description or "No description provided",
                "created_at": timestamp,
                "paths": folder_paths,
                "message": f"Investigation created: {investigation_id}. Use this ID in all subsequent tool calls to keep work organized. Files will be organized under {folder_paths['base']}"
            }
            
        except Exception as e:
            logger.exception("Failed to create investigation")
            return {
                "success": False,
                "error": str(e)
            }

    async def _write_organized_file(self, investigation_id: str, content: str, filename: str, category: str, 
                                   subdirectory: Optional[str] = None, overwrite: bool = False) -> Dict[str, Any]:
        """Write content to a file in organized directory structure with automatic sequence numbering
        
        Args:
            investigation_id: Investigation ID from create_investigation
            content: Content to write
            filename: Name of file (just filename, not path)
            category: Category for organization (script, input, output, test, doc, config)
            subdirectory: Optional subdirectory within category (will be auto-numbered if not exists)
            overwrite: Whether to overwrite existing files
            
        Returns:
            Dictionary with write results
        """
        try:
            from pathlib import Path
            import os
            import re
            
            logger.info(f"Writing organized file: {filename} (category: {category})")

            # Get investigations directory (inside mcp-server folder)
            mcp_server_dir = os.path.dirname(os.path.abspath(__file__))

            # Map categories to directories
            category_dirs = {
                "script": "scripts",
                "input": "inputs",
                "output": "outputs",
                "test": "tests",
                "doc": "docs",
                "config": "config"
            }

            if category not in category_dirs:
                return {
                    "success": False,
                    "error": f"Invalid category: {category}. Must be one of: {', '.join(category_dirs.keys())}",
                    "filename": filename
                }

            # Build target directory with sequence numbering under investigation folder
            base_dir = category_dirs[category]
            investigation_base = Path(mcp_server_dir) / "investigations" / investigation_id
            base_path = investigation_base / base_dir
            
            if subdirectory:
                # Check if subdirectory already has a number prefix
                if not re.match(r'^\d+[-_]', subdirectory):
                    # Auto-number the subdirectory
                    base_path.mkdir(parents=True, exist_ok=True)
                    
                    # Find existing numbered directories
                    existing_dirs = [d for d in base_path.iterdir() if d.is_dir()]
                    max_num = 0
                    
                    for existing_dir in existing_dirs:
                        match = re.match(r'^(\d+)[-_]', existing_dir.name)
                        if match:
                            num = int(match.group(1))
                            max_num = max(max_num, num)
                    
                    # Create numbered subdirectory
                    next_num = max_num + 1
                    numbered_subdir = f"{next_num:02d}_{subdirectory}"
                    target_dir = base_path / numbered_subdir
                else:
                    # Use subdirectory as-is if it already has a number
                    target_dir = base_path / subdirectory
            else:
                target_dir = base_path
            
            # Create directory if it doesn't exist
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # Full file path
            file_path = target_dir / filename
            
            # Check if file exists
            if file_path.exists() and not overwrite:
                return {
                    "success": False,
                    "error": f"File already exists: {file_path}. Set overwrite=true to replace it.",
                    "filename": filename,
                    "path": str(file_path)
                }
            
            # Write the file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            file_size = file_path.stat().st_size
            relative_path = file_path.relative_to(mcp_server_dir)
            
            # Get the actual subdirectory name (with numbering if applicable)
            actual_subdirectory = target_dir.name if subdirectory else None
            
            logger.info(f"File written successfully: {relative_path} ({file_size} bytes)")
            
            return {
                "success": True,
                "message": f"File written successfully: {relative_path}",
                "filename": filename,
                "path": str(file_path),
                "relative_path": str(relative_path),
                "investigation_id": investigation_id,
                "category": category,
                "subdirectory": actual_subdirectory,
                "size_bytes": file_size,
                "existed": file_path.exists() and overwrite
            }
            
        except Exception as e:
            logger.exception(f"Failed to write organized file: {filename}")
            error_tracker.record_error("WriteOrganizedFileError", str(e), {
                "filename": filename,
                "category": category,
                "investigation_id": investigation_id
            })
            return {
                "success": False,
                "error": str(e),
                "filename": filename,
                "category": category,
                "investigation_id": investigation_id
            }

    async def _lessons_learned(self, action: str, content: Optional[str] = None,
                              category: Optional[str] = None, tags: Optional[List[str]] = None,
                              query: Optional[str] = None, entry_id: Optional[str] = None,
                              investigation_id: Optional[str] = None, job_ids: Optional[List[str]] = None,
                              priority: str = "info", format: str = "json") -> Dict[str, Any]:
        """Manage structured lessons learned knowledge base

        Args:
            action: 'read', 'update', 'search', 'categories', or 'delete'
            content: Lesson content (required for update)
            category: Category/topic for the lesson
            tags: List of tags for the lesson
            query: Search term (required for search)
            entry_id: Entry ID (required for delete, optional for read)
            investigation_id: Link to investigation
            job_ids: Link to job IDs
            priority: Priority level (critical, warning, info)
            format: Output format (json, markdown)

        Returns:
            Dictionary with operation results
        """
        try:
            from pathlib import Path
            from datetime import datetime, timezone
            import os
            import uuid

            logger.info(f"Lessons learned action: {action}")

            # Get MCP server directory
            server_dir = os.path.dirname(os.path.abspath(__file__))

            # File paths
            json_file = Path(server_dir) / "lessons_learned.json"
            md_file = Path(server_dir) / "lessons_learned.md"

            def _load_lessons() -> Dict[str, Any]:
                """Load lessons from JSON file, migrating from MD if needed"""
                if json_file.exists():
                    with open(json_file, 'r', encoding='utf-8') as f:
                        return json.load(f)

                # Initialize new structure
                data = {
                    "version": "2.0",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "entries": []
                }

                # Migrate from existing MD file if it exists
                if md_file.exists():
                    md_content = md_file.read_text(encoding='utf-8')
                    migrated = _migrate_from_markdown(md_content)
                    data["entries"] = migrated
                    data["migrated_from"] = str(md_file)
                    data["migration_date"] = datetime.now(timezone.utc).isoformat()
                    logger.info(f"Migrated {len(migrated)} entries from lessons_learned.md")

                return data

            def _save_lessons(data: Dict[str, Any]) -> None:
                """Save lessons to JSON file"""
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

            def _migrate_from_markdown(md_content: str) -> List[Dict[str, Any]]:
                """Parse existing markdown file and extract entries"""
                import re
                entries = []

                # Pattern to match entries: ## timestamp - category or ## timestamp
                pattern = r'^##\s+(\d{4}-\d{2}-\d{2}[^\n]*?)(?:\s*-\s*([^\n]+))?\n(.*?)(?=^##\s+\d{4}|^---\s*$|\Z)'
                matches = re.findall(pattern, md_content, re.MULTILINE | re.DOTALL)

                for i, match in enumerate(matches):
                    timestamp_str, category_str, content_str = match
                    content_str = content_str.strip().rstrip('-').strip()

                    if not content_str:
                        continue

                    # Generate ID based on index
                    entry_id = f"legacy_{i+1:03d}"

                    # Parse timestamp
                    try:
                        # Try various formats
                        ts = timestamp_str.strip()
                        if ' UTC' in ts:
                            ts = ts.replace(' UTC', '+00:00').replace(' ', 'T')
                        timestamp = ts
                    except:
                        timestamp = timestamp_str.strip()

                    entries.append({
                        "id": entry_id,
                        "timestamp": timestamp,
                        "category": category_str.strip() if category_str else None,
                        "tags": [],
                        "content": content_str,
                        "priority": "info",
                        "investigation_id": None,
                        "job_ids": [],
                        "migrated": True
                    })

                return entries

            def _to_markdown(data: Dict[str, Any]) -> str:
                """Export lessons to markdown format"""
                lines = ["# Lessons Learned\n"]
                lines.append("This file is auto-generated from lessons_learned.json.\n")
                lines.append(f"Last updated: {data.get('updated_at', 'Unknown')}\n")
                lines.append(f"Total entries: {len(data.get('entries', []))}\n")
                lines.append("\n---\n")

                for entry in data.get("entries", []):
                    cat_str = f" - {entry['category']}" if entry.get('category') else ""
                    priority_badge = ""
                    if entry.get('priority') == 'critical':
                        priority_badge = " 🔴"
                    elif entry.get('priority') == 'warning':
                        priority_badge = " 🟡"

                    lines.append(f"\n## [{entry['id']}] {entry['timestamp']}{cat_str}{priority_badge}\n")

                    if entry.get('tags'):
                        lines.append(f"**Tags:** {', '.join(entry['tags'])}\n")
                    if entry.get('investigation_id'):
                        lines.append(f"**Investigation:** {entry['investigation_id']}\n")
                    if entry.get('job_ids'):
                        lines.append(f"**Jobs:** {', '.join(entry['job_ids'])}\n")

                    lines.append(f"\n{entry['content']}\n")
                    lines.append("\n---\n")

                return "\n".join(lines)

            def _generate_id() -> str:
                """Generate a unique entry ID"""
                return f"lesson_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

            # Load current data
            data = _load_lessons()

            # Handle actions
            if action == "read":
                if entry_id:
                    # Return specific entry
                    entry = next((e for e in data["entries"] if e["id"] == entry_id), None)
                    if not entry:
                        return {
                            "success": False,
                            "error": f"Entry not found: {entry_id}",
                            "action": "read"
                        }
                    return {
                        "success": True,
                        "action": "read",
                        "entry": entry,
                        "format": format
                    }

                # Return all entries
                if format == "markdown":
                    md_content = _to_markdown(data)
                    return {
                        "success": True,
                        "action": "read",
                        "content": md_content,
                        "entry_count": len(data["entries"]),
                        "format": "markdown",
                        "message": f"Retrieved {len(data['entries'])} entries in markdown format"
                    }

                return {
                    "success": True,
                    "action": "read",
                    "entries": data["entries"],
                    "entry_count": len(data["entries"]),
                    "categories": list(set(e.get("category") for e in data["entries"] if e.get("category"))),
                    "format": "json",
                    "path": str(json_file),
                    "message": f"Retrieved {len(data['entries'])} entries"
                }

            elif action == "update":
                if not content:
                    return {
                        "success": False,
                        "error": "content is required for update action",
                        "action": "update"
                    }

                new_entry = {
                    "id": _generate_id(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "category": category,
                    "tags": tags or [],
                    "content": content,
                    "priority": priority,
                    "investigation_id": investigation_id,
                    "job_ids": job_ids or [],
                    "migrated": False
                }

                data["entries"].append(new_entry)
                _save_lessons(data)

                logger.info(f"Added lesson: {new_entry['id']}")

                return {
                    "success": True,
                    "action": "update",
                    "entry_id": new_entry["id"],
                    "entry": new_entry,
                    "total_entries": len(data["entries"]),
                    "message": f"Successfully added lesson: {new_entry['id']}"
                }

            elif action == "search":
                if not query:
                    return {
                        "success": False,
                        "error": "query is required for search action",
                        "action": "search"
                    }

                query_lower = query.lower()
                results = []

                for entry in data["entries"]:
                    # Search in content
                    if query_lower in entry.get("content", "").lower():
                        results.append(entry)
                        continue
                    # Search in category
                    if entry.get("category") and query_lower in entry["category"].lower():
                        results.append(entry)
                        continue
                    # Search in tags
                    if entry.get("tags"):
                        if any(query_lower in tag.lower() for tag in entry["tags"]):
                            results.append(entry)
                            continue
                    # Search in ID
                    if query_lower in entry.get("id", "").lower():
                        results.append(entry)
                        continue

                # Filter by category if provided
                if category:
                    results = [r for r in results if r.get("category", "").lower() == category.lower()]

                return {
                    "success": True,
                    "action": "search",
                    "query": query,
                    "category_filter": category,
                    "results": results,
                    "result_count": len(results),
                    "message": f"Found {len(results)} entries matching '{query}'"
                }

            elif action == "categories":
                # Get all unique categories with counts
                category_counts = {}
                for entry in data["entries"]:
                    cat = entry.get("category") or "Uncategorized"
                    category_counts[cat] = category_counts.get(cat, 0) + 1

                # Get all unique tags
                all_tags = set()
                for entry in data["entries"]:
                    all_tags.update(entry.get("tags", []))

                return {
                    "success": True,
                    "action": "categories",
                    "categories": category_counts,
                    "category_count": len(category_counts),
                    "tags": sorted(list(all_tags)),
                    "tag_count": len(all_tags),
                    "total_entries": len(data["entries"]),
                    "message": f"Found {len(category_counts)} categories and {len(all_tags)} unique tags"
                }

            elif action == "delete":
                if not entry_id:
                    return {
                        "success": False,
                        "error": "entry_id is required for delete action",
                        "action": "delete"
                    }

                # Find and remove entry
                original_count = len(data["entries"])
                data["entries"] = [e for e in data["entries"] if e["id"] != entry_id]

                if len(data["entries"]) == original_count:
                    return {
                        "success": False,
                        "error": f"Entry not found: {entry_id}",
                        "action": "delete"
                    }

                _save_lessons(data)

                return {
                    "success": True,
                    "action": "delete",
                    "deleted_id": entry_id,
                    "remaining_entries": len(data["entries"]),
                    "message": f"Successfully deleted entry: {entry_id}"
                }

            else:
                return {
                    "success": False,
                    "error": f"Invalid action: {action}. Must be 'read', 'update', 'search', 'categories', or 'delete'",
                    "action": action
                }

        except Exception as e:
            logger.exception(f"Failed to execute lessons_learned action: {action}")
            error_tracker.record_error("LessonsLearnedError", str(e), {
                "action": action,
                "category": category
            })
            return {
                "success": False,
                "error": str(e),
                "action": action
            }

    async def _get_job_logs(self, job_id: str, tail: Optional[int] = None, 
                            wait_for_completion: bool = False, poll_interval: int = 30,
                            timeout_seconds: int = 3600) -> Dict[str, Any]:
        """Retrieve execution logs from a Discovery job
        
        Args:
            job_id: The Discovery job/operation ID
            tail: Optional number of last lines to retrieve (default: 100)
            wait_for_completion: If True, poll until job reaches terminal state
            poll_interval: Seconds between polls (default: 30, minimum: 10)
            timeout_seconds: Maximum wait time in seconds (default: 3600)
            
        Returns:
            Dictionary with log content and metadata
        """
        try:
            import asyncio
            from datetime import datetime, timezone
            
            if tail is None:
                tail = 100
            
            # Enforce minimum poll interval
            poll_interval = max(10, poll_interval)
            
            logger.info(f"Retrieving logs for job: {job_id} (tail={tail}, wait={wait_for_completion})")
            required_fields = ['tenant_id', 'workspace_name', 'project_name', 'subscription_id', 'resource_group']
            _, _, config_vals = self._get_azure_config_with_validation(required_fields)
            tenant_id = config_vals['tenant_id']
            workspace_name = config_vals['workspace_name']
            project_name = config_vals['project_name']
            subscription_id = config_vals['subscription_id']
            resource_group = config_vals['resource_group']
            
            server_traces = []
            server_traces.append(f"Retrieving logs for job: {job_id}")
            
            terminal_states = {'Succeeded', 'Failed', 'Canceled'}
            start_time = datetime.now(timezone.utc)
            poll_count = 0
            last_status = None
            
            while True:
                poll_count += 1
                
                # Get job status (includes full job data)
                status_result = await self._get_job_status(job_id, include_logs=False)
                if not status_result.get('success'):
                    # If not waiting for completion, fail immediately
                    if not wait_for_completion:
                        return {
                            "success": False,
                            "error": "Could not retrieve job status to locate logs",
                            "job_id": job_id,
                            "traces": server_traces
                        }
                    
                    # Otherwise, log the error and retry (transient API errors)
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    error_msg = status_result.get('error', 'Unknown error')
                    server_traces.append(f"[{elapsed:.0f}s] ⚠️ Status check failed: {error_msg}, retrying...")
                    logger.warning(f"Job {job_id} status check failed (poll #{poll_count}): {error_msg}")
                    
                    # Check timeout
                    if elapsed >= timeout_seconds:
                        server_traces.append(f"⏱️ Timeout after {elapsed:.0f}s ({poll_count} polls)")
                        return {
                            "success": False,
                            "job_id": job_id,
                            "error": f"Timeout waiting for job completion after {timeout_seconds}s. Last error: {error_msg}",
                            "poll_count": poll_count,
                            "elapsed_seconds": elapsed,
                            "traces": server_traces
                        }
                    
                    # Wait and retry
                    await asyncio.sleep(poll_interval)
                    continue
                
                current_status = status_result.get('status', 'unknown')
                job_data = status_result.get('full_details', {})
                
                # Log status changes
                if current_status != last_status:
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    server_traces.append(f"[{elapsed:.0f}s] Status: {current_status}")
                    logger.info(f"Job {job_id} status: {current_status} (poll #{poll_count})")
                    last_status = current_status
                
                # Check if job has reached terminal state
                is_terminal = current_status in terminal_states
                
                # If not waiting or job is terminal, extract logs and return
                if not wait_for_completion or is_terminal:
                    logs_content = None
                    
                    # Try result.logs
                    result = job_data.get('result', {})
                    logs_content = result.get('logs')
                    
                    # Try result.toolReport.logs
                    if not logs_content:
                        tool_report = result.get('toolReport', {})
                        if isinstance(tool_report, dict):
                            logs_content = tool_report.get('logs')
                    
                    # Try details.logs
                    if not logs_content:
                        details = job_data.get('details', {})
                        if isinstance(details, dict):
                            logs_content = details.get('logs')
                    
                    # Fallback to status_result.get('logs')
                    if not logs_content:
                        logs_content = status_result.get('logs')
                    
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    
                    if logs_content and isinstance(logs_content, str) and len(logs_content) > 0:
                        log_lines = logs_content.split('\n')
                        line_count = len([line for line in log_lines if line.strip()])
                        server_traces.append(f"Retrieved {line_count} lines of logs")
                        logger.info(f"Retrieved {line_count} lines of logs for job {job_id}")
                        
                        return {
                            "success": True,
                            "job_id": job_id,
                            "status": current_status,
                            "logs": logs_content,
                            "line_count": line_count,
                            "tail_requested": tail,
                            "poll_count": poll_count,
                            "elapsed_seconds": elapsed,
                            "traces": server_traces,
                            "retrieved_at": datetime.now(timezone.utc).isoformat()
                        }
                    else:
                        server_traces.append("ℹ️ No logs available in job status response")
                        return {
                            "success": False if not is_terminal else True,
                            "job_id": job_id,
                            "status": current_status,
                            "error": "No logs available in job status response" if not is_terminal else None,
                            "message": f"Job completed with status: {current_status}" if is_terminal else None,
                            "poll_count": poll_count,
                            "elapsed_seconds": elapsed,
                            "traces": server_traces
                        }
                
                # Check timeout
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                if elapsed >= timeout_seconds:
                    server_traces.append(f"⏱️ Timeout after {elapsed:.0f}s ({poll_count} polls)")
                    return {
                        "success": False,
                        "job_id": job_id,
                        "status": current_status,
                        "error": f"Timeout waiting for job completion after {timeout_seconds}s",
                        "poll_count": poll_count,
                        "elapsed_seconds": elapsed,
                        "traces": server_traces
                    }
                
                # Wait before next poll
                server_traces.append(f"[{elapsed:.0f}s] Waiting {poll_interval}s... (status: {current_status})")
                await asyncio.sleep(poll_interval)
                
        except Exception as e:
            logger.exception(f"Failed to retrieve logs for job {job_id}")
            error_tracker.record_error("GetJobLogsError", str(e), {"job_id": job_id})
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }

    async def _get_job_results(self, job_id: str, investigation_id: str) -> Dict[str, Any]:
        """Download results from a completed Discovery job
        
        Args:
            job_id: The Discovery job/operation ID
            investigation_id: Investigation ID from create_investigation. Results will be saved to investigations/inv_XXX/output/job_<id>/
            
        Returns:
            Dictionary with job results, output files, and status information
        """
        try:
            import requests
            from datetime import datetime, timezone
            import os
            from pathlib import Path
            
            logger.info(f"Retrieving results for job: {job_id}")

            # Get investigations directory (inside mcp-server folder)
            mcp_server_dir = os.path.dirname(os.path.abspath(__file__))
            investigations_dir = Path(mcp_server_dir) / "investigations"
            investigation_dir = investigations_dir / investigation_id
            
            # Verify investigation exists
            if not investigation_dir.exists():
                raise ValueError(f"Investigation '{investigation_id}' does not exist. Please create it first using create_investigation.")
            
            # Set output directory to investigation's outputs folder
            output_dir = str(investigation_dir / "outputs" / f"job_{job_id}")
            
            # Get and validate configuration using helper
            required_fields = ['tenant_id', 'workspace_name', 'project_name']
            _, _, config_vals = self._get_azure_config_with_validation(required_fields)
            
            tenant_id = config_vals['tenant_id']
            workspace_name = config_vals['workspace_name']
            project_name = config_vals['project_name']
            
            server_traces = []
            server_traces.append(f" Retrieving results for job: {job_id}")
            
            # Get Discovery API token using helper
            discovery_access_token = self._get_discovery_token(workspace_name, tenant_id, server_traces, purpose='discovery_results')
            
            # First get the job status to check if it's completed
            status_url = f"https://{workspace_name}.workspace.discovery.azure.com/tools/projects/{project_name}/operations/{job_id}"
            headers = {
                'Authorization': f'Bearer {discovery_access_token}',
                'Accept': 'application/json'
            }
            
            server_traces.append(f" Checking job status...")
            
            response = requests.get(status_url, headers=headers, timeout=30)
            
            if response.status_code == 404:
                server_traces.append(f" X Job not found: {job_id}")
                raise ValueError(f"Job with ID '{job_id}' not found")
            
            if response.status_code != 200:
                error_text = response.text
                server_traces.append(f" X Failed to get job status: {response.status_code}")
                raise ValueError(f"Discovery API returned {response.status_code}: {error_text}")
            
            job_data = response.json()
            status = job_data.get('status', 'unknown')
            
            server_traces.append(f" Job status: {status}")
            
            # Check if job is in a terminal state
            if status not in ['Succeeded', 'Failed', 'Canceled']:
                server_traces.append(f" Job is not yet complete (current status: {status})")
                return {
                    "success": False,
                    "error": f"Job is still running or pending. Current status: {status}",
                    "job_id": job_id,
                    "status": status,
                    "traces": server_traces
                }
            
            # Get the resource location which contains the job outputs
            resource_location = job_data.get('resourceLocation')
            
            # Also check for outputData in result
            result_data = job_data.get('result', {})
            output_data_array = result_data.get('outputData', [])
            
            if not resource_location and not output_data_array:
                server_traces.append(" No resource location or output data found in job data")
                server_traces.append(" Attempting direct Azure Storage download...")
                
                # Try to download directly from Azure Storage using the output path we configured
                # The output path should be: run-<timestamp>/output
                # We need to extract the run ID from the job submission or reconstruct it
                
                try:
                    from azure.identity import DefaultAzureCredential
                    from azure.storage.blob import BlobServiceClient
                    
                    # Get storage configuration - fail immediately if not configured
                    config = self.config_manager.load_config()
                    azure_config = config.get('azure', {})
                    azure_compute_config = config.get('azure_compute', {})
                    storage_account = azure_config.get('discovery_storage') or azure_config.get('storage_account', '')
                    data_container = azure_compute_config.get('data_container', '').strip()
                    
                    if not data_container:
                        raise ValueError("data_container not configured in Azure Compute settings")
                    
                    # Parse storage account name
                    if '/providers/Microsoft.Storage/storageAccounts/' in storage_account:
                        account_name = storage_account.split('/')[-1]
                    elif storage_account.startswith('https://'):
                        host = storage_account.split('://', 1)[1]
                        account_name = host.split('.')[0]
                    else:
                        account_name = storage_account
                    
                    if not account_name:
                        raise ValueError("Storage account not configured")
                    
                    account_url = f"https://{account_name}.blob.core.windows.net"
                    
                    # Get credential
                    from azure_auth_helpers import get_credential_for_tenant
                    cred = get_credential_for_tenant(tenant_id, purpose='download-results')
                    
                    if not cred:
                        raise ValueError("Could not obtain Azure credential")
                    
                    # Try to extract the run prefix from the job ID or search for output blobs
                    # Since we don't have the exact run prefix stored, we'll need to list blobs that might contain outputs
                    # The job was submitted with an output path, so outputs should be at: <data_container>/<outputs_asset>/run-*/output/
                    
                    blob_service = BlobServiceClient(account_url=account_url, credential=cred)
                    container_client = blob_service.get_container_client(data_container)
                    
                    # List all blobs under the container to find outputs
                    # Look for blobs that contain "outputs/" and were recently created
                    server_traces.append(f" Searching for output files in {account_name}/{data_container}...")
                    
                    outputs_data = {"files": []}
                    downloaded_files = []
                    
                    # List blobs with "outputs" in the path
                    blobs = list(container_client.list_blobs(name_starts_with="run-"))
                    
                    # Filter to find blobs that match our job's output pattern
                    # Since we don't have the exact run prefix, look for recent output blobs
                    import re
                    from datetime import datetime, timedelta
                    
                    job_created_time = datetime.fromisoformat(job_data.get('result', {}).get('createdAt', '').replace('Z', '+00:00'))
                    time_window = timedelta(minutes=30)  # Look for outputs created within 30 minutes of job
                    
                    for blob in blobs:
                        # Check if blob is in an output directory
                        if '/output/' in blob.name and not blob.name.endswith('.placeholder'):
                            # Check if blob was created around the same time as the job
                            blob_time = blob.last_modified
                            if abs((blob_time - job_created_time).total_seconds()) < time_window.total_seconds():
                                outputs_data["files"].append({
                                    "name": blob.name,
                                    "size": blob.size,
                                    "last_modified": blob.last_modified.isoformat()
                                })
                                
                                # Download if output_dir specified
                                if output_dir:
                                    output_dir_abs = os.path.abspath(output_dir)
                                    os.makedirs(output_dir_abs, exist_ok=True)
                                    
                                    # Extract just the filename from the blob path
                                    filename = blob.name.split('/output/')[-1]
                                    local_path = os.path.join(output_dir_abs, filename)
                                    
                                    # Download the blob
                                    blob_client = container_client.get_blob_client(blob.name)
                                    with open(local_path, 'wb') as f:
                                        download_stream = blob_client.download_blob()
                                        f.write(download_stream.readall())
                                    
                                    downloaded_files.append(local_path)
                                    server_traces.append(f" Downloaded: {filename}")
                    
                    if outputs_data["files"]:
                        server_traces.append(f"Found {len(outputs_data['files'])} output file(s) in Azure Storage")
                        
                        result = {
                            "success": True,
                            "job_id": job_id,
                            "status": status,
                            "workspace": workspace_name,
                            "project": project_name,
                            "traces": server_traces,
                            "query_time": datetime.now(timezone.utc).isoformat(),
                            "outputs": outputs_data,
                            "source": "azure_storage_direct"
                        }
                        
                        if output_dir:
                            result['saved_files'] = downloaded_files
                            result['output_directory'] = output_dir
                            server_traces.append(f"Downloaded {len(downloaded_files)} file(s) to {output_dir}")
                        
                        return result
                    else:
                        server_traces.append(" No output files found in Azure Storage")
                        
                except Exception as storage_e:
                    server_traces.append(f" Azure Storage download failed: {str(storage_e)}")
                    logger.error(f"Failed to download from Azure Storage: {storage_e}")
                
                return {
                    "success": True,
                    "job_id": job_id,
                    "status": status,
                    "message": "Job completed but no output location or data available",
                    "traces": server_traces,
                    "job_data": job_data
                }
            
            # If we have outputData directly, process it
            if output_data_array and not resource_location:
                server_traces.append(f" Found {len(output_data_array)} output mount(s) in outputData")
                
                # Build outputs structure from outputData
                outputs_data = {"files": output_data_array}
                
                # Build result dictionary
                result = {
                    "success": True,
                    "job_id": job_id,
                    "status": status,
                    "workspace": workspace_name,
                    "project": project_name,
                    "traces": server_traces,
                    "query_time": datetime.now(timezone.utc).isoformat(),
                    "outputs": outputs_data
                }
                
                # Create output directory in investigation folder
                server_traces.append(f" Saving results to investigation output directory: {output_dir}")
                
                # Download files from Azure Storage
                output_dir_abs = os.path.abspath(output_dir)
                os.makedirs(output_dir_abs, exist_ok=True)
                
                saved_files = []
                
                # Parse discovery:// URI and query Management API for actual blob path
                try:
                    from azure.identity import DefaultAzureCredential
                    from azure.storage.blob import BlobServiceClient
                    
                    # Get storage configuration
                    config = self.config_manager.load_config()
                    azure_config = config.get('azure', {})
                    azure_compute_config = config.get('azure_compute', {})
                    storage_account = azure_compute_config.get('storage_account', '')
                    subscription_id = azure_config.get('subscription_id', '')
                    tenant_id = azure_config.get('tenant_id', '')
                    
                    # Parse storage account name
                    if '/providers/Microsoft.Storage/storageAccounts/' in storage_account:
                        account_name = storage_account.split('/')[-1]
                    elif storage_account.startswith('https://'):
                        host = storage_account.split('://', 1)[1]
                        account_name = host.split('.')[0]
                    else:
                        account_name = storage_account
                    
                    if not account_name:
                        raise ValueError("Storage account not configured")
                    
                    account_url = f"https://{account_name}.blob.core.windows.net"
                    
                    # Get credential
                    from azure_auth_helpers import get_credential_for_tenant
                    cred = get_credential_for_tenant(tenant_id, purpose='download-results')
                    
                    if not cred:
                        raise ValueError("Could not obtain Azure credential")
                    
                    # Get management token for querying data asset properties
                    mgmt_token = self._get_azure_management_token(tenant_id, server_traces)
                    
                    server_traces.append(f" Downloading from Azure Storage: {account_name}")
                    
                    # Process each output mount
                    for output_item in output_data_array:
                        if not isinstance(output_item, dict):
                            continue
                        
                        output_uri = output_item.get('uri', '')
                        
                        # Parse discovery:// URI
                        # Format: discovery://dataassets/subscriptions/.../datacontainers/X/DataAssets/Y/paths/Z
                        if output_uri.startswith('discovery://dataassets'):
                            # Extract resource ID and path suffix
                            without_scheme = output_uri[len('discovery://dataassets'):]
                            parts = without_scheme.split('/paths/')
                            asset_rid = parts[0].rstrip('/')
                            path_suffix = parts[1] if len(parts) > 1 else ''
                            
                            # Query Management API to get the data asset's actual blob path
                            try:
                                mgmt_api = f"https://management.azure.com{asset_rid}?api-version=2025-07-01-preview"
                                mgmt_headers = {'Authorization': f'Bearer {mgmt_token}'}
                                mgmt_resp = requests.get(mgmt_api, headers=mgmt_headers, timeout=15)
                                
                                if mgmt_resp.status_code == 200:
                                    mgmt_body = mgmt_resp.json()
                                    asset_path = mgmt_body.get('properties', {}).get('path', '')
                                    
                                    if asset_path:
                                        # asset_path format: container/path/to/asset
                                        path_parts = str(asset_path).strip('/').split('/', 1)
                                        container_name = path_parts[0] if len(path_parts) > 0 else ''
                                        asset_base_path = path_parts[1] if len(path_parts) > 1 else ''
                                        
                                        # Combine asset base path with path suffix
                                        if asset_base_path and path_suffix:
                                            blob_prefix = f"{asset_base_path}/{path_suffix}"
                                        elif path_suffix:
                                            blob_prefix = path_suffix
                                        elif asset_base_path:
                                            blob_prefix = asset_base_path
                                        else:
                                            blob_prefix = ''
                                        
                                        server_traces.append(f" Container: {container_name}, Path: {blob_prefix}")
                                        
                                        if not container_name:
                                            server_traces.append(" Could not determine container name from asset path")
                                            continue
                                        
                                        # List blobs
                                        blob_service = BlobServiceClient(account_url=account_url, credential=cred)
                                        container_client = blob_service.get_container_client(container_name)
                                        
                                        blobs = list(container_client.list_blobs(name_starts_with=blob_prefix))
                                        
                                        # Count actual files (excluding placeholders)
                                        file_count = sum(1 for b in blobs if not b.name.endswith('.placeholder'))
                                        server_traces.append(f" Found {file_count} file(s) in output mount")
                                        
                                        for blob in blobs:
                                            if blob.name.endswith('.placeholder'):
                                                continue
                                            
                                            # Extract filename relative to the blob prefix
                                            rel_name = blob.name[len(blob_prefix):].lstrip('/')
                                            if not rel_name:
                                                continue
                                            
                                            local_path = os.path.join(output_dir_abs, rel_name)
                                            os.makedirs(os.path.dirname(local_path), exist_ok=True)
                                            
                                            # Download the blob
                                            blob_client = container_client.get_blob_client(blob.name)
                                            with open(local_path, 'wb') as f:
                                                download_stream = blob_client.download_blob()
                                                f.write(download_stream.readall())
                                            
                                            saved_files.append(local_path)
                                            server_traces.append(f" Downloaded: {rel_name}")
                                    else:
                                        server_traces.append(f" Management API returned no path for asset")
                                else:
                                    server_traces.append(f" Management API returned {mgmt_resp.status_code} for asset query")
                            
                            except Exception as mgmt_e:
                                server_traces.append(f" Failed to query asset properties: {str(mgmt_e)}")
                                logger.error(f"Asset query error: {mgmt_e}", exc_info=True)
                    
                    if saved_files:
                        result['saved_files'] = saved_files
                        result['output_directory'] = output_dir_abs
                        server_traces.append(f"Downloaded {len(saved_files)} file(s) to {output_dir_abs}")
                    else:
                        server_traces.append(" No files found to download from Azure Storage")
                
                except Exception as download_e:
                    server_traces.append(f" Failed to download from Azure Storage: {str(download_e)}")
                    logger.error(f"Download error: {download_e}", exc_info=True)
                
                return result
            
            # Legacy path: Download file content from URL if available
            if resource_location:
                file_url = resource_location
                if not file_url.startswith('http'):
                    file_url = f"https://{workspace_name}.workspace.discovery.azure.com{file_url}"
                
                server_traces.append(f" Found resource location: {resource_location}")
                server_traces.append(f" Fetching job outputs...")
                
                response = requests.get(file_url, headers=headers, timeout=60)
            
            if response.status_code != 200:
                error_text = response.text
                server_traces.append(f" X Failed to fetch job outputs: {response.status_code}")
                return {
                    "success": True,
                    "job_id": job_id,
                    "status": status,
                    "message": f"Could not fetch outputs (status {response.status_code})",
                    "traces": server_traces,
                    "job_data": job_data
                }
            
            # Parse output data
            try:
                outputs_data = response.json()
            except:
                # Might be a direct file download
                outputs_data = {"raw_content": response.text}
            
            server_traces.append(f"Retrieved job outputs")
            
            # Build result dictionary
            result = {
                "success": True,
                "job_id": job_id,
                "status": status,
                "workspace": workspace_name,
                "project": project_name,
                "traces": server_traces,
                "query_time": datetime.now(timezone.utc).isoformat(),
                "outputs": outputs_data
            }
            
            # Determine output directory
            # If not specified, automatically create workspace subdirectory for easy access
            if not output_dir:
                # Try to get workspace root from config manager
                try:
                    import pathlib
                    # Find workspace root by looking for .git directory
                    current_dir = pathlib.Path.cwd()
                    workspace_root = None
                    for parent in [current_dir] + list(current_dir.parents):
                        if (parent / '.git').exists():
                            workspace_root = parent
                            break
                    
                    if workspace_root:
                        # Create output directory in workspace
                        workspace_output_dir = workspace_root / 'utils' / 'agent-workbench' / 'output' / f'job_{job_id}'
                        output_dir = str(workspace_output_dir)
                        server_traces.append(f" Auto-creating workspace output directory: {output_dir}")
                    else:
                        # Fallback to current directory
                        output_dir = f'./output/job_{job_id}'
                        server_traces.append(f" Workspace root not found, using relative path: {output_dir}")
                except Exception as dir_e:
                    logger.warning(f"Could not determine workspace root: {dir_e}")
                    output_dir = f'./output/job_{job_id}'
                    server_traces.append(f" Using default output directory: {output_dir}")
            
            # Ensure output directory exists and get absolute path
            output_dir = os.path.abspath(output_dir)
            os.makedirs(output_dir, exist_ok=True)
            
            saved_files = []
            
            # If outputs_data has files, save them
            if isinstance(outputs_data, dict):
                if 'files' in outputs_data:
                    for file_info in outputs_data.get('files', []):
                        filename = file_info.get('name', f'output_{len(saved_files)}.txt')
                        filepath = os.path.join(output_dir, filename)
                        
                        # Download file content
                        file_url = file_info.get('url')
                        if file_url:
                            if not file_url.startswith('http'):
                                file_url = f"https://{workspace_name}.workspace.discovery.azure.com{file_url}"
                            
                            file_response = requests.get(file_url, headers=headers, timeout=60)
                            if file_response.status_code == 200:
                                with open(filepath, 'wb') as f:
                                    f.write(file_response.content)
                                saved_files.append(filepath)
                                server_traces.append(f" Saved: {filepath}")
                
                # Save raw content if available
                if 'raw_content' in outputs_data:
                    filepath = os.path.join(output_dir, f'job_{job_id}_output.txt')
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(outputs_data['raw_content'])
                    saved_files.append(filepath)
                    server_traces.append(f" Saved: {filepath}")
            
            # Save full output JSON
            json_path = os.path.join(output_dir, f'job_{job_id}_full_output.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(outputs_data, f, indent=2)
            saved_files.append(json_path)
            server_traces.append(f" Saved full output: {json_path}")
            
            # Always include saved files and output directory in result
            result['saved_files'] = saved_files
            result['output_directory'] = output_dir
            
            if saved_files:
                server_traces.append(f"Saved {len(saved_files)} file(s) to workspace: {output_dir}")
            
            # Add creation/completion timestamps if present
            if 'createdDateTime' in job_data:
                result['created_at'] = job_data['createdDateTime']
            
            if 'lastActionDateTime' in job_data:
                result['completed_at'] = job_data['lastActionDateTime']
            
            # Include error information if job failed
            if status in ['Failed', 'Canceled']:
                if 'error' in job_data:
                    result['error_details'] = job_data['error']
                    server_traces.append(f" Job {status.lower()}: {job_data.get('error', {}).get('message', 'No error message')}")
            
            logger.info(f"Retrieved results for job {job_id}")
            
            return result
            
        except Exception as e:
            logger.exception(f"Failed to get results for job {job_id}")
            error_tracker.record_error("GetJobResultsError", str(e), {"job_id": job_id})
            return {
                "success": False,
                "error": str(e),
                "job_id": job_id
            }


async def main():
    """Main server loop"""
    server = DiscoveryMCPServer()
    
    logger.info("Discovery MCP Server starting...")
    
    # Initialize server components at startup (load or create config files)
    try:
        await server._ensure_initialized()
        logger.info("Server initialization complete")
    except Exception as e:
        logger.error(f"Server initialization failed: {e}")
        # Continue anyway - initialization will be retried on first request
    
    try:
        # Read requests from stdin and write responses to stdout
        while True:
            line = sys.stdin.readline()
            if not line:
                break
                
            line = line.strip()
            if not line:
                continue
                
            try:
                request = json.loads(line)
                response = server.handle_request(request)
                
                # Handle async tool calls
                if (response and response.get("method") == "tools/call"):
                    tool_name = response["params"]["name"]
                    arguments = response["params"]["arguments"]
                    request_id = response["id"]
                    response = await server.handle_call_tool(request_id, tool_name, arguments)
                
                if response:  # Only send response for requests, not notifications
                    print(json.dumps(response), flush=True)
                    
            except json.JSONDecodeError as e:
                error_msg = f"Invalid JSON: {e}"
                logger.exception("JSON parse error")
                error_tracker.record_error("JSONDecodeError", error_msg, {"line": line})
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                }
                print(json.dumps(error_response), flush=True)
                
            except Exception as e:
                error_msg = f"Error handling request: {e}"
                logger.exception("Request handling error")
                error_tracker.record_error("RequestHandlingError", error_msg, {"request_line": SensitiveDataMasker.mask(line)})
                error_response = {
                    "jsonrpc": "2.0", 
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}"
                    }
                }
                print(json.dumps(error_response), flush=True)
                
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
        logger.info("Error statistics: %s", error_tracker.get_stats())
    except Exception as e:
        logger.exception("Fatal server error")
        error_tracker.record_error("FatalServerError", str(e))
        
if __name__ == "__main__":
    asyncio.run(main())