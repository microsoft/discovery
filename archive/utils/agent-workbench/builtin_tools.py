"""
Builtin tools for Discovery Agent Workbench.

These tools are automatically injected into agent conversations via dataHandlingContext.
The LLM can call these tools by returning function_call responses, which are intercepted
and executed by the web server before continuing the conversation.
"""

import os
import json
from typing import Dict, Any, List, Optional
from pathlib import Path

# Define the builtin tools available to all agents
BUILTIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Save simple text/markdown content you directly compose (jokes, notes, summaries). NEVER use for Python scripts or code - execute those via your normal code execution mechanism instead. This function is ONLY for plain text that requires no computation or execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to write (e.g., 'jokes.txt', 'notes.md'). Should not include directory paths."
                    },
                    "content": {
                        "type": "string",
                        "description": "Simple text content to write. For computational results, use scripts that save to final_results.json instead."
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Whether to overwrite the file if it already exists. Default is true.",
                        "default": True
                    }
                },
                "required": ["filename", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read simple text files from the output directory. For data processing, use your specialized tools/scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to read (e.g., 'notes.md'). Should not include directory paths."
                    }
                },
                "required": ["filename"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files in the output directory. Use alongside your primary tools when needed.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]


class BuiltinToolExecutor:
    """Executor for builtin tools that operate on the session's output directory."""

    def __init__(self, output_dir: str = None):
        """
        Initialize the tool executor.

        Args:
            output_dir: Base directory for file operations. Should be the session's output directory.
                       If not provided, will raise an error when trying to write files.
        """
        self.output_dir = output_dir
        
    def _get_safe_path(self, filename: str) -> Path:
        """
        Get a safe file path by sanitizing the filename.

        Args:
            filename: User-provided filename

        Returns:
            Safe Path object

        Raises:
            ValueError: If filename is invalid or output_dir not configured
        """
        if not self.output_dir:
            raise ValueError("Output directory not configured. BuiltinToolExecutor requires an output_dir.")

        # Security: Use only the basename to prevent directory traversal
        safe_name = os.path.basename(filename)

        if not safe_name or safe_name in ('.', '..'):
            raise ValueError(f"Invalid filename: {filename}")

        # Ensure output directory exists
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        return output_path / safe_name
    
    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a builtin tool.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            
        Returns:
            Dict with success status and result/error message
        """
        try:
            if tool_name == "write_file":
                return self._write_file(
                    filename=arguments.get("filename"),
                    content=arguments.get("content"),
                    overwrite=arguments.get("overwrite", True)
                )
            elif tool_name == "read_file":
                return self._read_file(filename=arguments.get("filename"))
            elif tool_name == "list_files":
                return self._list_files()
            else:
                return {
                    "success": False,
                    "error": f"Unknown tool: {tool_name}"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _write_file(self, filename: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
        """Write content to a file."""
        if not filename:
            raise ValueError("filename is required")
        if content is None:
            raise ValueError("content is required")
            
        file_path = self._get_safe_path(filename)
        
        # Check if file exists and overwrite is False
        if file_path.exists() and not overwrite:
            return {
                "success": False,
                "error": f"File '{filename}' already exists and overwrite is False"
            }
        
        # Write the file
        file_path.write_text(content, encoding='utf-8')
        
        return {
            "success": True,
            "message": f"File '{filename}' written successfully",
            "filename": filename,
            "size": len(content),
            "path": str(file_path)
        }
    
    def _read_file(self, filename: str) -> Dict[str, Any]:
        """Read content from a file."""
        if not filename:
            raise ValueError("filename is required")
            
        file_path = self._get_safe_path(filename)
        
        if not file_path.exists():
            return {
                "success": False,
                "error": f"File '{filename}' not found"
            }
        
        content = file_path.read_text(encoding='utf-8')
        
        return {
            "success": True,
            "filename": filename,
            "content": content,
            "size": len(content),
            "path": str(file_path)
        }
    
    def _list_files(self) -> Dict[str, Any]:
        """List all files in the output directory."""
        output_path = Path(self.output_dir)
        
        if not output_path.exists():
            return {
                "success": True,
                "files": [],
                "message": "Output directory is empty"
            }
        
        files = []
        for file_path in output_path.iterdir():
            if file_path.is_file():
                files.append({
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime
                })
        
        return {
            "success": True,
            "files": files,
            "count": len(files)
        }


def get_builtin_tools() -> List[Dict[str, Any]]:
    """
    Get the list of builtin tools to inject into agent conversations.
    
    Returns:
        List of tool definitions in Azure OpenAI format
    """
    return BUILTIN_TOOLS


def get_data_handling_context() -> str:
    """
    Get the dataHandlingContext text to inject into agent instructions.
    This tells agents about available file operations without modifying their YAML.
    
    Returns:
        Markdown-formatted context describing builtin tools
    """
    return """

## Supplementary File Operations

**File Storage Locations:**
- Files you save with write_file() will be stored in the **output directory**
- Use simple filenames (e.g., 'report.md', 'bom.xlsx') - no directory paths needed

Important: These supplementary file operations should not make you forget of your primary capabilities such as generating scripts.

**Available functions for content handling:**

**write_file(filename, content)** - Save content you directly compose
**read_file(filename)** - Read files from the output directory
**list_files()** - List all saved files in the output directory

**Usage Guidelines:**

- Unless explicitly requested, DO NOT use write_file() for saving executable code

** In the same answer you can both save files, using write_file()), and return scripts / code inline in your answer **
- Example: "Create and save a report about usage of ethanol and calculate its key properties"
    - 1. Create report and and save it using write_file()
    - 2. Generate and execute Python script inline (code block) to perform analysis

**⚠️ IMPORTANT - Response with Function Calls:**
When calling write_file or other functions, ALWAYS include your explanatory text, code blocks, and reasoning in the SAME response as the function call. Do not wait for function results to show your work - display everything upfront alongside the function calls.

**Key principle:** write_file() supplements your capabilities, but doesn't change how you generate and execute computational code. Follow your normal code execution workflow, and include all explanatory content when making function calls.

"""
