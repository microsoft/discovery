#!/usr/bin/env python3
"""
Discovery Management MCP Server

A specialized MCP server for managing Azure Discovery platform configurations, agent catalogs,
tool deployments, and workflow visualizations. This server handles administrative and development
tasks separate from computational job execution.

Management Capabilities:
- Agent Catalog Management: Browse and configure local agent definitions for development
- Configuration Management: Set up Azure subscriptions, resource groups, and Discovery settings
- Tool Publishing: Deploy agents and tools to Azure Discovery workspaces
- Workflow Visualization: Generate diagrams from workflow definitions
- Profile Management: Switch between different Discovery environment configurations

⚠️ NOTE: This server is for MANAGEMENT and DEVELOPMENT tasks only.
For scientific computations and job execution, use the main Discovery workbench server.
"""

import json
import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from typing import Dict, Any, Optional
import traceback

# Add the workbench directory to the path
workbench_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, workbench_dir)

try:
    from agent_manager import StaticAgentManager
    from discovery_config_manager import DiscoveryConfigManager
    HAS_WORKBENCH = True
except ImportError as e:
    print(f"Warning: Could not import workbench components: {e}")
    HAS_WORKBENCH = False

# Set up logging
def setup_logging():
    """Configure file-based logging with rotation"""
    workbench_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    log_dir = os.path.join(workbench_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "mcp_management_server.log")
    
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    
    return logging.getLogger(__name__)

logger = setup_logging()
logger.info("Discovery Management MCP Server logging initialized")

class DiscoveryManagementServer:
    """MCP Server for Discovery Management and Configuration"""
    
    def __init__(self):
        self.agent_manager: Optional[StaticAgentManager] = None
        self.config_manager: Optional[DiscoveryConfigManager] = None
        self._initialized = False
        
        # Define management tools
        self.tools = [
            {
                "name": "list_profiles",
                "description": "List all available configuration profiles for Azure Discovery environments. Profiles define different computational setups (e.g., production research environment, development testing, different Azure subscriptions, various supercomputer configurations). Shows profile names and indicates which is currently active. Use this to see available research environments and quickly identify your current working context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_supercomputer_info",
                "description": "Get comprehensive information about available Azure Discovery supercomputers and their compute nodepools. Returns hardware specifications, provisioning status, available CPU/GPU resources, and nodepool configurations. Use this to select appropriate computational resources for your scientific workloads (e.g., high-memory nodes for molecular dynamics, GPU nodes for quantum chemistry calculations).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "supercomputer_name": {
                            "type": "string",
                            "description": "Optional: Specific supercomputer name to get detailed info for"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "list_docker_containers",
                "description": "List Docker containers related to scientific computational agents running in the workbench environment. Shows container IDs, images, status, and associated agent tools. Use this for troubleshooting containerized scientific software, monitoring resource usage, or verifying that computational tools are properly deployed and operational.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "switch_profile",
                "description": "Switch between different Azure Discovery environment profiles to change your active computational infrastructure. Profiles contain complete Azure subscription settings, supercomputer connections, storage configurations, and resource group details. Use this to seamlessly move between research environments (e.g., from development to production, or between different project workspaces) without manual reconfiguration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "profile_name": {
                            "type": "string",
                            "description": "Name of the profile to switch to"
                        }
                    },
                    "required": ["profile_name"]
                }
            },
            {
                "name": "list_local_agents",
                "description": "List agents in local agents-catalog.yaml file. Shows local development catalog for catalog development and testing. Use this to browse available agent definitions, compare local vs published configurations, or debug YAML structure. For discovering actual deployed computational capabilities, use list_published_agents in the main workbench server instead.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_agent_config",
                "description": "Get configuration from local agent catalog YAML. Returns agent definition including tools, instructions, and metadata from the local development catalog. Use for catalog development, comparing local vs published definitions, or understanding agent structure before deployment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Name of the agent to get config for"
                        }
                    },
                    "required": ["agent_name"]
                }
            },
            {
                "name": "switch_agent",
                "description": "Switch active agent in local catalog context. Changes the currently selected agent for local development workflows. This affects local catalog operations only and does not impact Azure deployments.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": "Name of the agent to switch to"
                        }
                    },
                    "required": ["agent_name"]
                }
            },
            {
                "name": "get_discovery_config",
                "description": "Get the current Azure Discovery platform configuration including Azure subscription details, supercomputer settings, storage accounts, and computational resources. View infrastructure settings for your Discovery environment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "upload_agent_catalog",
                "description": "Upload and apply a complete agent catalog configuration in YAML format. The catalog defines available scientific tools, computational workflows, and research agents. Use this to deploy pre-configured tool collections or programmatically update the workbench.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "catalog_content": {
                            "type": "string",
                            "description": "YAML content of the agent catalog"
                        },
                        "catalog_name": {
                            "type": "string",
                            "description": "Optional name for the catalog (for reference)"
                        }
                    },
                    "required": ["catalog_content"]
                }
            },
            {
                "name": "add_discovery_profile",
                "description": "Create a new Discovery profile with Azure configuration settings. Profiles allow you to maintain multiple Azure Discovery environments (dev, test, production, different regions) and switch between them easily. The profile will be added to discovery_config.json and can be activated using switch_profile. Optionally copy settings from an existing profile.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "profile_name": {
                            "type": "string",
                            "description": "Required: Name for the new profile (e.g., 'Production', 'Dev-WestUS', 'Test-Sweden')"
                        },
                        "display_name": {
                            "type": "string",
                            "description": "Optional: Display name for the profile"
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional: Description of the profile's purpose"
                        },
                        "copy_from": {
                            "type": "string",
                            "description": "Optional: Name of existing profile to copy settings from"
                        },
                        "config_settings": {
                            "type": "object",
                            "description": "Optional: Configuration settings to apply to the new profile (azure, azure_openai, azure_compute sections)"
                        }
                    },
                    "required": ["profile_name"]
                }
            },
            {
                "name": "delete_discovery_profile",
                "description": "Delete a Discovery profile from discovery_config.json. Cannot delete the active profile (switch to another profile first) or the last remaining profile. Use this to clean up unused environment configurations.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "profile_name": {
                            "type": "string",
                            "description": "Required: Name of the profile to delete"
                        }
                    },
                    "required": ["profile_name"]
                }
            },
            {
                "name": "set_agent_catalog",
                "description": "Configure the agent catalog file path and reload the workbench with a new collection of tools and workflows. Use this to switch between different research environments or update tool definitions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "catalog_path": {
                            "type": "string",
                            "description": "Path to the agent catalog YAML file"
                        }
                    },
                    "required": ["catalog_path"]
                }
            },
            {
                "name": "set_discovery_config",
                "description": "Configure the Discovery platform settings file path and reload with new Azure infrastructure settings. Use this to switch between Azure Discovery deployments or reconfigure after infrastructure changes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "config_path": {
                            "type": "string",
                            "description": "Absolute path to the discovery config JSON file"
                        }
                    },
                    "required": ["config_path"]
                }
            },
            {
                "name": "reload_workbench",
                "description": "Refresh both agent catalog and Discovery platform configuration to apply pending changes. Reloads available tools, workflows, Azure settings, and supercomputer connections. Use after modifying configuration files or tool definitions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "catalog_path": {
                            "type": "string",
                            "description": "Optional: Path to agent catalog file"
                        },
                        "config_path": {
                            "type": "string",
                            "description": "Optional: Path to discovery config file"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "validate_agent_definition",
                "description": "Validate YAML agent or workflow definitions against Discovery platform schemas. Checks structure, required fields, valid tool references, and schema compliance. Use before deployment to prevent errors and ensure correct workflow definitions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_yaml": {
                            "type": "string",
                            "description": "YAML content of the agent definition to validate"
                        },
                        "agent_type": {
                            "type": "string",
                            "description": "Type of agent: 'tool', 'entry', or 'knowledge_base'",
                            "enum": ["tool", "entry", "knowledge_base"]
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Optional: Path to YAML file to validate"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "generate_mermaid_diagram",
                "description": "Generate a visual flowchart diagram from workflow YAML definitions. Converts research pipelines into Mermaid diagram syntax for visualization. Shows agent interactions, tool invocations, and workflow logic. Returns ONLY the Mermaid diagram text.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "yaml_content": {
                            "type": "string",
                            "description": "YAML content of the workflow definition"
                        },
                        "workflow_name": {
                            "type": "string",
                            "description": "Optional: Name of the workflow"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Optional: Path to workflow YAML file"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "generate_mermaid_svg",
                "description": "Render a Mermaid diagram specification into SVG image file. Creates publication-ready vector graphics from diagram text. Use for workflow documentation in papers, presentations, or team collaboration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "mermaid_text": {
                            "type": "string",
                            "description": "Mermaid diagram text to convert to SVG"
                        },
                        "output_file": {
                            "type": "string",
                            "description": "Optional: Output file path for the SVG"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Optional: Path to file containing Mermaid text"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "publish_tool",
                "description": "Deploy a containerized scientific software tool to Azure Discovery workspace. Reads YAML tool definition and publishes to Azure. Use to make custom scientific software available on the Discovery platform.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "tool_yaml_path": {
                            "type": "string",
                            "description": "Required: Absolute path to tool definition YAML file"
                        },
                        "tool_name": {
                            "type": "string",
                            "description": "Optional: Override tool name from YAML"
                        }
                    },
                    "required": ["tool_yaml_path"]
                }
            },
            {
                "name": "publish_tool_agent",
                "description": "Deploy AI-powered computational agent with its associated tool to Azure Discovery. Publishes both agent definition and containerized tool. Use to create intelligent research assistants for complex computations. IMPORTANT: When multiple agents share the same container/tool (e.g., RDKit chemistry toolkit), use the SAME tool_name for all agents to avoid creating duplicate tool instances.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_yaml_path": {
                            "type": "string",
                            "description": "Required: Absolute path to agent definition YAML"
                        },
                        "tool_yaml_path": {
                            "type": "string",
                            "description": "Required: Absolute path to tool definition YAML"
                        },
                        "agent_name": {
                            "type": "string",
                            "description": "Optional: Override agent name from YAML"
                        },
                        "tool_name": {
                            "type": "string",
                            "description": "Optional: Override tool name from YAML. CRITICAL: When publishing multiple agents that share the same container (e.g., moleculeAgent, fingerPrintAgent, descriptorAgent all use RDKit), use the SAME tool name (e.g., 'rdkit') for all of them. Do NOT create separate tool instances like 'moleculeService', 'fingerPrintService', etc."
                        },
                        "model_name": {
                            "type": "string",
                            "description": "Optional: Override model name for agent"
                        }
                    },
                    "required": ["agent_yaml_path", "tool_yaml_path"]
                }
            },
            {
                "name": "publish_tool_from_catalog",
                "description": "Deploy tool to Azure Discovery by referencing catalog entry. Automatically locates tool definition from catalog and publishes to Azure. Use for quick deployment of pre-configured tools.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_key": {
                            "type": "string",
                            "description": "Required: Agent/tool key in catalog"
                        },
                        "tool_name": {
                            "type": "string",
                            "description": "Optional: Override tool name from YAML"
                        }
                    },
                    "required": ["agent_key"]
                }
            },
            {
                "name": "publish_agent_from_catalog",
                "description": "Deploy AI-powered agent and its tool to Azure Discovery by catalog reference. Automatically locates definitions from catalog and publishes together. Use for rapid deployment of standardized scientific capabilities.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_key": {
                            "type": "string",
                            "description": "Required: Agent key in catalog"
                        },
                        "agent_name": {
                            "type": "string",
                            "description": "Optional: Override agent name from YAML"
                        },
                        "tool_name": {
                            "type": "string",
                            "description": "Optional: Override tool name from YAML"
                        },
                        "model_name": {
                            "type": "string",
                            "description": "Optional: Override model name for agent"
                        }
                    },
                    "required": ["agent_key"]
                }
            },
            {
                "name": "write_file",
                "description": "Write computational results, analysis reports, or data files to persistent storage in the workbench output directory. Use this to save processed molecular structures, calculated properties, simulation parameters, research summaries, CSV data tables, JSON datasets, visualization scripts, or markdown reports. Files are immediately accessible in the workbench Results tab for review, download, or further computational processing. Essential for preserving intermediate results in multi-step scientific workflows.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Required: Name of the file to create (e.g., 'results.txt', 'data.json', 'report.md'). Only the basename is used for security."
                        },
                        "content": {
                            "type": "string",
                            "description": "Required: Content to write to the file. Can be text, JSON, CSV, Markdown, etc."
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "Optional: Whether to overwrite the file if it already exists. Default is true. If false and file exists, an error is returned."
                        }
                    },
                    "required": ["filename", "content"]
                }
            }
        ]
        
        self._initialize_managers()
    
    def _initialize_managers(self):
        """Initialize agent and config managers"""
        if not HAS_WORKBENCH:
            logger.warning("Workbench components not available")
            return
        
        try:
            # Try to find config file
            workbench_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            config_path = os.path.join(workbench_dir, "discovery_config.json")
            
            if os.path.exists(config_path):
                self.config_manager = DiscoveryConfigManager(config_path)
                logger.info(f"Loaded config from: {config_path}")
            else:
                default_config_path = os.path.join(workbench_dir, "discovery_config_template.json")
                if os.path.exists(default_config_path):
                    self.config_manager = DiscoveryConfigManager(default_config_path)
                    logger.info(f"Loaded config from template: {default_config_path}")
            
            # Try to find catalog file
            catalog_path = os.path.join(workbench_dir, "agents-catalog.yaml")
            if os.path.exists(catalog_path):
                self.agent_manager = StaticAgentManager(catalog_path)
                logger.info(f"Loaded catalog from: {catalog_path}")
            else:
                default_catalog_path = os.path.join(workbench_dir, "agents-catalog-template.yaml")
                if os.path.exists(default_catalog_path):
                    self.agent_manager = StaticAgentManager(default_catalog_path)
                    logger.info(f"Loaded catalog from template: {default_catalog_path}")
            
            self._initialized = True
            
        except Exception as e:
            logger.warning(f"Failed to initialize managers: {e}")
    
    def handle_initialize(self, request_id: int) -> Dict[str, Any]:
        """Handle initialize request"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "discovery-management",
                    "version": "1.0.0",
                    "description": "Azure Discovery Management Server - Administrative tools for agent catalog management, configuration, tool publishing, and workflow visualization."
                },
                "instructions": "Discovery Management MCP Server - Administrative and development tools for Azure Discovery platform.\n\nThis server provides:\n- Agent Catalog Management: Browse, configure, and manage local agent definitions\n- Configuration Management: Set up and switch between Azure Discovery environments\n- Tool Publishing: Deploy agents and tools to Azure workspaces\n- Workflow Visualization: Generate diagrams from workflow definitions\n- Profile Management: Switch between different Discovery configurations\n\n⚠️ NOTE: This server is for MANAGEMENT tasks only. For computational job execution and scientific work, use the main Discovery workbench server."
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
                    ]
                }
            }
        except Exception as e:
            logger.exception(f"Error handling tool call: {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": {"traceback": traceback.format_exc()}
                }
            }
    
    async def _handle_tool_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Route tool calls to appropriate handlers - importing implementations from main server"""
        # Import the main server to access its implementation methods
        # This allows us to reuse the existing implementation without duplicating code
        from server import DiscoveryMCPServer
        
        # Create a temporary instance to access methods
        main_server = DiscoveryMCPServer()
        main_server.agent_manager = self.agent_manager
        main_server.config_manager = self.config_manager
        
        # Route to appropriate handler
        if name == "list_profiles":
            return await main_server._list_profiles()
        elif name == "get_supercomputer_info":
            supercomputer_name = arguments.get("supercomputer_name")
            return await main_server._get_supercomputer_info(supercomputer_name)
        elif name == "list_docker_containers":
            return await main_server._list_docker_containers()
        elif name == "switch_profile":
            profile_name = arguments.get("profile_name")
            if not profile_name:
                raise ValueError("profile_name is required")
            return await main_server._switch_profile(profile_name)
        elif name == "list_local_agents":
            return await main_server._list_local_agents()
        elif name == "get_agent_config":
            agent_name = arguments.get("agent_name")
            if not agent_name:
                raise ValueError("agent_name is required")
            return await main_server._get_agent_config(agent_name)
        elif name == "switch_agent":
            agent_name = arguments.get("agent_name")
            if not agent_name:
                raise ValueError("agent_name is required")
            return await main_server._switch_agent(agent_name)
        elif name == "get_discovery_config":
            return await main_server._get_discovery_config()
        elif name == "upload_agent_catalog":
            catalog_content = arguments.get("catalog_content")
            catalog_name = arguments.get("catalog_name")
            if not catalog_content:
                raise ValueError("catalog_content is required")
            return await main_server._upload_agent_catalog(catalog_content, catalog_name)
        elif name == "add_discovery_profile":
            profile_name = arguments.get("profile_name")
            display_name = arguments.get("display_name")
            description = arguments.get("description", "")
            copy_from = arguments.get("copy_from")
            config_settings = arguments.get("config_settings")
            if not profile_name:
                raise ValueError("profile_name is required")
            return await self._add_discovery_profile(profile_name, display_name, description, copy_from, config_settings)
        elif name == "delete_discovery_profile":
            profile_name = arguments.get("profile_name")
            if not profile_name:
                raise ValueError("profile_name is required")
            return await self._delete_discovery_profile(profile_name)
        elif name == "set_agent_catalog":
            catalog_path = arguments.get("catalog_path")
            if not catalog_path:
                raise ValueError("catalog_path is required")
            return await main_server._set_agent_catalog(catalog_path)
        elif name == "set_discovery_config":
            config_path = arguments.get("config_path")
            if not config_path:
                raise ValueError("config_path is required")
            return await main_server._set_discovery_config(config_path)
        elif name == "reload_workbench":
            catalog_path = arguments.get("catalog_path")
            config_path = arguments.get("config_path")
            return await main_server._reload_workbench(catalog_path, config_path)
        elif name == "validate_agent_definition":
            agent_yaml = arguments.get("agent_yaml")
            agent_type = arguments.get("agent_type")
            file_path = arguments.get("file_path")
            return await main_server._validate_agent_definition(agent_yaml, agent_type, file_path)
        elif name == "generate_mermaid_diagram":
            yaml_content = arguments.get("yaml_content")
            workflow_name = arguments.get("workflow_name")
            file_path = arguments.get("file_path")
            return await main_server._generate_mermaid_diagram(yaml_content, workflow_name, file_path)
        elif name == "generate_mermaid_svg":
            mermaid_text = arguments.get("mermaid_text")
            output_file = arguments.get("output_file")
            file_path = arguments.get("file_path")
            return await main_server._generate_mermaid_svg(mermaid_text, output_file, file_path)
        elif name == "publish_tool":
            tool_yaml_path = arguments.get("tool_yaml_path")
            tool_name = arguments.get("tool_name")
            if not tool_yaml_path:
                raise ValueError("tool_yaml_path is required")
            return await main_server._publish_tool(tool_yaml_path, tool_name)
        elif name == "publish_tool_agent":
            agent_yaml_path = arguments.get("agent_yaml_path")
            tool_yaml_path = arguments.get("tool_yaml_path")
            agent_name = arguments.get("agent_name")
            tool_name = arguments.get("tool_name")
            model_name = arguments.get("model_name")
            if not agent_yaml_path or not tool_yaml_path:
                raise ValueError("agent_yaml_path and tool_yaml_path are required")
            return await main_server._publish_tool_agent(agent_yaml_path, tool_yaml_path, agent_name, tool_name, model_name)
        elif name == "publish_tool_from_catalog":
            agent_key = arguments.get("agent_key")
            tool_name = arguments.get("tool_name")
            if not agent_key:
                raise ValueError("agent_key is required")
            return await main_server._publish_tool_from_catalog(agent_key, tool_name)
        elif name == "publish_agent_from_catalog":
            agent_key = arguments.get("agent_key")
            agent_name = arguments.get("agent_name")
            tool_name = arguments.get("tool_name")
            model_name = arguments.get("model_name")
            if not agent_key:
                raise ValueError("agent_key is required")
            return await main_server._publish_agent_from_catalog(agent_key, agent_name, tool_name, model_name)
        elif name == "write_file":
            filename = arguments.get("filename")
            content = arguments.get("content")
            overwrite = arguments.get("overwrite", True)
            if not filename:
                raise ValueError("filename is required")
            if content is None:
                raise ValueError("content is required")
            return await self._write_file(filename, content, overwrite)
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    async def handle_request(self, request_line: str) -> Optional[str]:
        """Handle incoming JSON-RPC request"""
        try:
            request = json.loads(request_line)
            method = request.get("method")
            request_id = request.get("id")
            
            if method == "initialize":
                response = self.handle_initialize(request_id)
            elif method == "initialized":
                self.handle_initialized()
                return None
            elif method == "tools/list":
                response = self.handle_list_tools(request_id)
            elif method == "tools/call":
                params = request.get("params", {})
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                response = await self.handle_call_tool(request_id, tool_name, arguments)
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }
            
            return json.dumps(response)
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                }
            }
            return json.dumps(error_response)
        except Exception as e:
            logger.exception("Error handling request")
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if 'request' in locals() else None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
            return json.dumps(error_response)
    
    async def run(self):
        """Main server loop"""
        logger.info("Discovery Management MCP Server started")
        
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                response = await self.handle_request(line)
                if response:
                    print(response, flush=True)
                    
            except Exception as e:
                logger.exception("Error in main loop")
                break
        
        logger.info("Discovery Management MCP Server stopped")

    async def _write_file(self, filename: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
        """Write content to a file in the current session's output directory

        Args:
            filename: Name of the file to create (basename only for security)
            content: Content to write to the file
            overwrite: Whether to overwrite if file exists (default: True)

        Returns:
            Dictionary with success status and file info
        """
        try:
            import urllib.request
            import urllib.error

            # Sanitize filename to prevent directory traversal
            filename = os.path.basename(filename)
            if not filename or filename in ['.', '..']:
                return {
                    "success": False,
                    "error": "Invalid filename"
                }

            # Query the web server for the current session's output directory
            mcp_server_dir = os.path.dirname(os.path.abspath(__file__))
            workbench_dir = os.path.dirname(mcp_server_dir)
            shared_output_dir = None

            try:
                # Try to get current session from the web server (default port 5000)
                req = urllib.request.Request('http://localhost:5000/api/sessions/current')
                with urllib.request.urlopen(req, timeout=2) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get('session'):
                        session_id = data['session'].get('session_id')
                        agent_name = data['session'].get('agent_name')
                        if session_id:
                            # Build the session output path
                            shared_output_dir = os.path.join(workbench_dir, "sessions", session_id)
                            if agent_name:
                                safe_agent_name = agent_name.replace('/', '_').replace('\\', '_')
                                shared_output_dir = os.path.join(shared_output_dir, safe_agent_name)
                            shared_output_dir = os.path.join(shared_output_dir, "output")
                            logger.info(f"Using session output directory: {shared_output_dir}")
            except (urllib.error.URLError, TimeoutError, Exception) as e:
                logger.warning(f"Could not get current session from web server: {e}")

            # If we couldn't get the session, return an error (no fallback to _default)
            if not shared_output_dir:
                return {
                    "success": False,
                    "error": "No active session. Please ensure the workbench web server is running and has an active session."
                }

            # Create output directory if it doesn't exist
            os.makedirs(shared_output_dir, exist_ok=True)

            file_path = os.path.join(shared_output_dir, filename)

            # Check if file exists and overwrite is False
            if os.path.exists(file_path) and not overwrite:
                return {
                    "success": False,
                    "error": f"File {filename} already exists and overwrite is disabled"
                }

            # Write the content to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Get file stats
            stat = os.stat(file_path)

            logger.info(f"Successfully wrote file: {filename} ({stat.st_size} bytes)")

            return {
                "success": True,
                "message": f"File {filename} written successfully",
                "filename": filename,
                "size": stat.st_size,
                "path": file_path
            }

        except Exception as e:
            logger.exception(f"Failed to write file {filename}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _add_discovery_profile(self, profile_name: str, display_name: Optional[str], 
                                     description: str, copy_from: Optional[str], 
                                     config_settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Add a new Discovery profile"""
        try:
            if not self.config_manager:
                return {"error": "Config manager not initialized"}
            
            # Create the profile using ProfileManager
            result = self.config_manager.profile_manager.create_profile(
                name=profile_name,
                display_name=display_name,
                description=description,
                copy_from=copy_from
            )
            
            if not result.get('success'):
                return result
            
            # If config_settings provided, update the newly created profile
            if config_settings:
                update_result = self.config_manager.profile_manager.update_profile(
                    profile_name, config_settings
                )
                if not update_result.get('success'):
                    return update_result
            
            return {
                "success": True,
                "message": f"Profile '{profile_name}' created successfully",
                "profile_name": profile_name,
                "copied_from": copy_from if copy_from else "default template"
            }
        except Exception as e:
            logger.exception(f"Failed to add profile {profile_name}")
            return {"error": f"Failed to add profile: {str(e)}"}
    
    async def _delete_discovery_profile(self, profile_name: str) -> Dict[str, Any]:
        """Delete a Discovery profile"""
        try:
            if not self.config_manager:
                return {"error": "Config manager not initialized"}
            
            # Delete the profile using ProfileManager
            result = self.config_manager.profile_manager.delete_profile(profile_name)
            
            if result.get('success'):
                return {
                    "success": True,
                    "message": f"Profile '{profile_name}' deleted successfully",
                    "profile_name": profile_name
                }
            else:
                return result
                
        except Exception as e:
            logger.exception(f"Failed to delete profile {profile_name}")
            return {"error": f"Failed to delete profile: {str(e)}"}

async def main():
    """Entry point"""
    server = DiscoveryManagementServer()
    await server.run()

if __name__ == "__main__":
    asyncio.run(main())
