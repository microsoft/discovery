"""
Agent Manager for Multi-Agent Test Framework

Provides static catalog-based agent management with minimal configuration.
Policy: As of Aug 2025 the catalog no longer supplies a 'name' field for agents; the
source of truth for display names is the YAML agent definition itself. Catalog now
only lists paths (agent_config, tools_definition, dockerfile) plus optional metadata
for workflow agents (description, components). Any legacy 'name'
key in the catalog should be ignored if present.
"""
import os
import yaml
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

# Import robust file loading utilities
from file_utils import load_yaml_robust, FileEncodingError

# Set up logging
logger = logging.getLogger(__name__)


@dataclass
class AgentCatalogEntry:
    """Minimal catalog entry for an agent"""
    key: str  # Derived key for this agent (from config path)
    agent_config: str
    tools_definition: str
    dockerfile: str
    env_vars: str = ""  # Optional environment variables file
    tool_definition: str = ""  # Optional tool definition file (YAML)
    agent_type: str = "regular"  # "regular" or "entry"


@dataclass
class WorkflowAgentCatalogEntry:
    """Represents a workflow agent in the catalog"""
    key: str
    name: str
    description: str
    agent_config: str
    components: List[Dict[str, str]]
    agent_type: str = "entry"
    # Draft metadata (present only while this workflow agent is a temporary draft)
    # Example structure:
    #   temp = {
    #       'created_ts': '2025-08-27T12:34:56Z',
    #       'auto_expire_minutes': 1440
    #   }
    temp: Optional[Dict[str, object]] = None


@dataclass
class KnowledgeBaseAgentCatalogEntry:
    """Represents a knowledge base agent in the catalog"""
    key: str
    name: str
    agent_config: str
    agent_type: str = "kb"


@dataclass
class AgentInfo:
    """Full agent information loaded from config files"""
    catalog_entry: AgentCatalogEntry
    display_name: str = ""
    description: str = ""
    _config_cache: Optional[Dict] = None


class StaticAgentManager:
    """Manages a static catalog of agents with lazy loading.

    Naming Rules:
    - Catalog entries no longer include 'name'. Key is derived from the first meaningful
      directory segment in the agent_config path (skipping relative markers and i-/ii- prefixes).
    - Display name is read from the agent_config YAML (agent.name) when available; otherwise
      the derived key is used.
    - This avoids drift between catalog and YAML definitions.
    """
    
    def __init__(self, catalog_path: str):
        self.catalog_path = catalog_path
        self.agents: Dict[str, AgentCatalogEntry] = {}
        self.workflow_agents: Dict[str, WorkflowAgentCatalogEntry] = {}
        self.kb_agents: Dict[str, KnowledgeBaseAgentCatalogEntry] = {}
        self.agent_info_cache: Dict[str, AgentInfo] = {}
        # Note: current_agent state has been removed - agent selection is now session-scoped
        # Each browser tab/session tracks its own agent via SessionManager
        self._load_catalog()
    
    def _load_catalog(self):
        """Load the agent catalog from YAML file.

        Ignores any legacy 'name' fields if they still exist.
        """
        if not os.path.exists(self.catalog_path):
            logger.info(f"Agent catalog not found: {self.catalog_path}")
            logger.info(f"Starting with empty catalog - agents can be created or loaded through the UI")
            # Initialize empty catalog structure
            catalog_data = {
                'tool_agents': [],
                'workflow_agents': [],
                'kb_agents': []
            }
        else:
            try:
                # Use robust YAML loading with encoding detection and normalization
                catalog_data = load_yaml_robust(self.catalog_path, normalize_chars=True)
                
                if not catalog_data:
                    logger.info(f"Empty catalog file found: {self.catalog_path}")
                    logger.info(f"Starting with empty catalog - agents can be created or loaded through the UI")
                    catalog_data = {
                        'tool_agents': [],
                        'workflow_agents': [],
                        'kb_agents': []
                    }
            except FileEncodingError as e:
                logger.error(f"Encoding error reading catalog file {self.catalog_path}: {e}")
                logger.info(f"Starting with empty catalog - agents can be created or loaded through the UI")
                catalog_data = {
                    'tool_agents': [],
                    'workflow_agents': [],
                    'kb_agents': []
                }
            except Exception as e:
                logger.info(f"Error reading catalog file {self.catalog_path}: {e}")
                logger.info(f"Starting with empty catalog - agents can be created or loaded through the UI")
                catalog_data = {
                    'tool_agents': [],
                    'workflow_agents': [],
                    'kb_agents': []
                }
        
        # Ensure all catalog sections are lists, not None
        if not isinstance(catalog_data.get('tool_agents'), list):
            catalog_data['tool_agents'] = []
        if not isinstance(catalog_data.get('workflow_agents'), list):
            catalog_data['workflow_agents'] = []
        if not isinstance(catalog_data.get('kb_agents'), list):
            catalog_data['kb_agents'] = []
        if not isinstance(catalog_data.get('agents'), list):
            catalog_data['agents'] = []
            
            # Load tool agents
            # Load tool agents (renamed from 'agents' for clarity)
            if 'tool_agents' in catalog_data:
                for i, agent_data in enumerate(catalog_data['tool_agents']):
                    agent_config_path = agent_data.get('agent_config', '')
                    if not agent_config_path:
                        logger.info(f"Skipping tool agent entry {i}: missing agent_config path")
                        continue
                    
                    # Use the explicit name if provided, otherwise derive from path
                    key = agent_data.get('name')
                    if not key:
                        # Fallback: derive a key from the agent config path (use the parent directory name)
                        # e.g., "../../Gromacs/2-Agent/a-core/i-GromacsAgent.yaml" -> "Gromacs"
                        path_parts = agent_config_path.replace('\\', '/').split('/')
                        for idx, part in enumerate(path_parts):
                            if part and part != '..' and not part.startswith('i-') and not part.startswith('ii-'):
                                # Skip generic container folder like generated-tool-agents
                                if part == 'generated-tool-agents' and idx + 1 < len(path_parts):
                                    continue
                                key = part
                                break
                        
                        if not key:
                            key = f"tool_agent_{i}"  # Fallback key
                    
                    entry = AgentCatalogEntry(
                        key=key,
                        agent_config=agent_config_path,
                        tools_definition=agent_data.get('tools_definition', ''),
                        dockerfile=agent_data.get('dockerfile', ''),
                        env_vars=agent_data.get('env_vars', ''),
                        tool_definition=agent_data.get('tool_definition', ''),
                        agent_type="regular"
                    )
                    self.agents[key] = entry
            
            # Support legacy 'agents' key for backward compatibility
            elif 'agents' in catalog_data:
                for i, agent_data in enumerate(catalog_data['agents']):
                    agent_config_path = agent_data.get('agent_config', '')
                    if not agent_config_path:
                        logger.info(f"Skipping agent entry {i}: missing agent_config path")
                        continue
                    
                    # Derive a key from the agent config path (use the parent directory name)
                    # e.g., "../../Gromacs/2-Agent/a-core/i-GromacsAgent.yaml" -> "Gromacs"
                    path_parts = agent_config_path.replace('\\', '/').split('/')
                    key = None
                    for idx, part in enumerate(path_parts):
                        if part and part != '..' and not part.startswith('i-') and not part.startswith('ii-'):
                            # Skip generic container folder like generated-tool-agents
                            if part == 'generated-tool-agents' and idx + 1 < len(path_parts):
                                continue
                            key = part
                            break
                    
                    if not key:
                        key = f"agent_{i}"  # Fallback key
                    
                    entry = AgentCatalogEntry(
                        key=key,
                        agent_config=agent_config_path,
                        tools_definition=agent_data.get('tools_definition', ''),
                        dockerfile=agent_data.get('dockerfile', ''),
                        env_vars=agent_data.get('env_vars', ''),
                        tool_definition=agent_data.get('tool_definition', ''),
                        agent_type="regular"
                    )
                    self.agents[key] = entry
            
            # Load workflow agents (treat catalog 'name' as optional; derive from agent_config path if absent)
            if 'workflow_agents' in catalog_data:
                for workflow_agent_data in catalog_data['workflow_agents']:
                    agent_config_path = workflow_agent_data.get('agent_config', '')
                    raw_name = workflow_agent_data.get('name', '').strip()

                    # Derive key from agent_config path (same approach as tool agents) if no name provided
                    derived_key = None
                    if agent_config_path:
                        path_parts = agent_config_path.replace('\\', '/').split('/')
                        for part in path_parts:
                            if part and part not in ('..', '.') and not part.startswith('i-') and not part.startswith('ii-') and not part.endswith('.yaml'):
                                derived_key = part
                                break

                    key = raw_name or derived_key
                    if not key:
                        logger.info(f"Skipping workflow agent: cannot derive key (missing name and agent_config path) -> {workflow_agent_data}")
                        continue

                    # Harmonize: we purposely ignore catalog 'name' beyond using it as optional override for key
                    # to reduce confusion—the true display name will later come from the agent_config YAML.
                    entry = WorkflowAgentCatalogEntry(
                        key=key,
                        name=key,
                        description=workflow_agent_data.get('description', ''),
                        agent_config=agent_config_path,
                        components=workflow_agent_data.get('components', [])
                    )
                    self.workflow_agents[key] = entry
            
            # Load knowledge base agents
            if 'kb_agents' in catalog_data:
                for kb_agent_data in catalog_data['kb_agents']:
                    agent_config_path = kb_agent_data.get('agent_config', '')
                    name = kb_agent_data.get('name', '').strip()
                    
                    if not agent_config_path:
                        logger.info(f"Skipping kb agent: missing agent_config path -> {kb_agent_data}")
                        continue
                        
                    # Use provided name or derive from config path
                    if not name:
                        path_parts = agent_config_path.replace('\\', '/').split('/')
                        for part in path_parts:
                            if part and part not in ('..', '.') and not part.startswith('i-') and not part.startswith('ii-') and part.endswith('.yaml'):
                                name = part[:-5]  # Remove .yaml extension
                                break
                        if not name:
                            name = f"kb_agent_{len(self.kb_agents)}"
                    
                    entry = KnowledgeBaseAgentCatalogEntry(
                        key=name,
                        name=name,
                        agent_config=agent_config_path
                    )
                    self.kb_agents[name] = entry
            
            logger.info(f"Loaded {len(self.agents)} tool agents, {len(self.workflow_agents)} workflow agents, and {len(self.kb_agents)} knowledge base agents from catalog")
    
    def _load_agent_info(self, agent_key: str, agent_type: Optional[str] = None) -> AgentInfo:
        """Load full agent information from config files (with caching)"""
        # Include agent_type in cache key to handle name conflicts between agent types
        cache_key = f"{agent_key}:{agent_type}" if agent_type else agent_key
        if cache_key in self.agent_info_cache:
            return self.agent_info_cache[cache_key]

        info = None
        entry = None

        # If agent_type is specified, check that type first to handle name conflicts
        if agent_type == 'entry' and agent_key in self.workflow_agents:
            entry_agent = self.workflow_agents[agent_key]
            temp_entry = AgentCatalogEntry(
                key=entry_agent.key,
                agent_config=entry_agent.agent_config,
                tools_definition='',
                dockerfile='',
                agent_type="entry"
            )
            info = AgentInfo(catalog_entry=temp_entry)
            info.display_name = entry_agent.name
            info.description = entry_agent.description
            self.agent_info_cache[cache_key] = info
            return info
        elif agent_type == 'kb' and agent_key in self.kb_agents:
            kb_agent = self.kb_agents[agent_key]
            temp_entry = AgentCatalogEntry(
                key=kb_agent.key,
                agent_config=kb_agent.agent_config,
                tools_definition='',
                dockerfile='',
                agent_type="kb"
            )
            info = AgentInfo(catalog_entry=temp_entry)
            info.display_name = kb_agent.name
            info.description = "Knowledge base agent"
            self.agent_info_cache[cache_key] = info
            return info
        elif agent_type == 'tool' and agent_key in self.agents:
            entry = self.agents[agent_key]
            info = AgentInfo(catalog_entry=entry)
            # Continue to load config below

        # Fallback (when no agent_type specified): Check tool agents, workflow agents, and kb_agents in order
        if info is None and agent_key in self.agents:
            entry = self.agents[agent_key]
            info = AgentInfo(catalog_entry=entry)
        if info is None and agent_key in self.workflow_agents:
            # For workflow agents, create a temporary AgentCatalogEntry-like structure
            entry_agent = self.workflow_agents[agent_key]
            # Create a mock AgentCatalogEntry for compatibility
            temp_entry = AgentCatalogEntry(
                key=entry_agent.key,
                agent_config=entry_agent.agent_config,
                tools_definition='',  # Entry agents don't have tools
                dockerfile='',       # Entry agents don't need Docker
                agent_type="entry"
            )
            info = AgentInfo(catalog_entry=temp_entry)
            # Use the workflow agent's metadata directly
            info.display_name = entry_agent.name
            info.description = entry_agent.description
            # Cache and return early for workflow agents
            self.agent_info_cache[cache_key] = info
            return info
        if info is None and agent_key in self.kb_agents:
            # For kb agents, create a temporary AgentCatalogEntry-like structure
            kb_agent = self.kb_agents[agent_key]
            # Create a mock AgentCatalogEntry for compatibility
            temp_entry = AgentCatalogEntry(
                key=kb_agent.key,
                agent_config=kb_agent.agent_config,
                tools_definition='',  # KB agents don't have tools
                dockerfile='',       # KB agents don't need Docker
                agent_type="kb"
            )
            info = AgentInfo(catalog_entry=temp_entry)
            # Use the kb agent's metadata directly
            info.display_name = kb_agent.name
            info.description = "Knowledge base agent"
            
            # Try to load display name and description from config
            config_path = os.path.join(os.path.dirname(self.catalog_path), kb_agent.agent_config)
            if os.path.exists(config_path):
                try:
                    # Use robust YAML loading with encoding detection
                    config = load_yaml_robust(config_path, normalize_chars=True)
                    if config and 'agent' in config:
                        info.display_name = config['agent'].get('name', kb_agent.name)
                        info.description = config['agent'].get('description', info.description)
                        info._config_cache = config
                except FileEncodingError as e:
                    logger.warning(f"Encoding error loading config for kb agent {agent_key}: {e}")
                    # Provide helpful guidance
                    logger.info(f"→ Try re-saving the file as UTF-8: {config_path}")
                except Exception as e:
                    logger.info(f"Error loading config for kb agent {agent_key}: {e}")
            
            # Cache and return for kb agents
            self.agent_info_cache[cache_key] = info
            return info

        if info is None:
            raise ValueError(f"Agent not found in catalog: {agent_key}")
        
        # Load display name and description from agent config (for tool agents)
        if entry.agent_config and os.path.exists(entry.agent_config):
            try:
                # Use robust YAML loading with encoding detection and normalization
                config = load_yaml_robust(entry.agent_config, normalize_chars=True)
                
                if config and 'agent' in config:
                    agent_config = config['agent']
                    info.display_name = agent_config.get('name', entry.key)
                    info.description = agent_config.get('description', '')
                    info._config_cache = config
                else:
                    info.display_name = entry.key
                
            except FileEncodingError as e:
                logger.error(f"Encoding error loading config for {agent_key}: {e}")
                logger.info(f"→ The file may contain special characters. Try re-saving as UTF-8: {entry.agent_config}")
                info.display_name = entry.key
            except Exception as e:
                logger.info(f"Failed to load config for {agent_key}: {e}")
                info.display_name = entry.key
        else:
            logger.info(f"Agent config file not found for {agent_key}: {entry.agent_config}")
            info.display_name = entry.key
        
        # Cache the loaded info
        self.agent_info_cache[cache_key] = info
        return info
    
    def list_agents(self) -> Dict[str, List[Dict[str, str]]]:
        """Get list of all agents organized by type"""
        tool_agents = []
        entry_agents = []
        kb_agents = []
        
        # Load tool agents - create snapshot to avoid "dictionary changed size during iteration"
        for key in list(self.agents.keys()):
            try:
                info = self._load_agent_info(key)
                tool_agents.append({
                    'name': key,  # This is the key used for API calls
                    'display_name': info.display_name,
                    'description': info.description,
                    'type': 'tool'
                })
            except Exception as e:
                logger.info(f"Error loading info for {key}: {e}")
                tool_agents.append({
                    'name': key,
                    'display_name': key,
                    'description': 'Error loading agent info',
                    'type': 'tool'
                })
        
        # Load workflow agents - create snapshot to avoid "dictionary changed size during iteration"
        for key, entry in list(self.workflow_agents.items()):
            entry_agents.append({
                'name': key,
                'display_name': entry.name,
                'description': entry.description,
                'type': 'entry',
                'components': len(entry.components),
                'is_temp': bool(getattr(entry, 'temp', None))
            })
        
        # Load knowledge base agents - create snapshot to avoid "dictionary changed size during iteration"
        for key, entry in list(self.kb_agents.items()):
            try:
                # Try to load display name from config file
                display_name = entry.name
                description = "Knowledge base agent"
                
                # Load config if available to get better display name and description
                if entry.agent_config:
                    config_path = os.path.join(os.path.dirname(self.catalog_path), entry.agent_config)
                    if os.path.exists(config_path):
                        try:
                            # Use robust YAML loading
                            config = load_yaml_robust(config_path, normalize_chars=True)
                            if config and 'agent' in config:
                                display_name = config['agent'].get('name', entry.name)
                                description = config['agent'].get('description', description)
                        except FileEncodingError as e:
                            logger.warning(f"Encoding error loading config for kb agent {key}: {e}")
                        except Exception as e:
                            logger.info(f"Error loading config for kb agent {key}: {e}")
                
                kb_agents.append({
                    'name': key,
                    'display_name': display_name,
                    'description': description,
                    'type': 'kb'
                })
            except Exception as e:
                logger.info(f"Error loading info for kb agent {key}: {e}")
                kb_agents.append({
                    'name': key,
                    'display_name': entry.name,
                    'description': 'Error loading agent info',
                    'type': 'kb'
                })
        
        return {
            'tool_agents': tool_agents,
            'workflow_agents': entry_agents,
            'kb_agents': kb_agents
        }
    
    def list_all_agents(self) -> List[Dict[str, str]]:
        """Get flat list of all agents (for backward compatibility)"""
        agents = []
        agent_data = self.list_agents()
        agents.extend(agent_data['tool_agents'])
        agents.extend(agent_data['workflow_agents'])
        agents.extend(agent_data['kb_agents'])
        return agents
    
    def get_agent_info(self, agent_key: str, agent_type: Optional[str] = None) -> AgentInfo:
        """Get detailed information for a specific agent"""
        return self._load_agent_info(agent_key, agent_type=agent_type)

    def agent_exists(self, agent_key: str, agent_type: Optional[str] = None) -> bool:
        """Check if an agent exists in the catalog.

        Args:
            agent_key: The agent key to check
            agent_type: Optional type to validate against ('tool', 'entry', 'kb')

        Returns:
            True if the agent exists (and matches type if specified), False otherwise
        """
        if agent_type:
            # Validate against specific type
            if agent_type == 'tool':
                return agent_key in self.agents
            elif agent_type == 'entry':
                return agent_key in self.workflow_agents
            elif agent_type == 'kb':
                return agent_key in self.kb_agents
            return False
        else:
            # Check any type
            return (agent_key in self.agents or
                    agent_key in self.workflow_agents or
                    agent_key in self.kb_agents)

    def get_agent_type(self, agent_key: str) -> Optional[str]:
        """Get the type of an agent.

        Returns:
            'tool', 'entry', 'kb', or None if agent not found
        """
        if agent_key in self.agents:
            return 'tool'
        elif agent_key in self.workflow_agents:
            return 'entry'
        elif agent_key in self.kb_agents:
            return 'kb'
        return None

    def get_agent_paths(self, agent_key: str, agent_type: Optional[str] = None) -> Dict[str, Any]:
        """Get file paths for an agent"""
        # If type not specified, determine from catalog
        if not agent_type:
            agent_type = self.get_agent_type(agent_key)

        # If type is specified, use type-specific lookup
        if agent_type == 'entry' and agent_key in self.workflow_agents:
            entry = self.workflow_agents[agent_key]
            return {
                'agent_config': entry.agent_config,
                'tools_definition': '',  # Workflow agents don't have tools
                'dockerfile': '',  # Workflow agents don't need Docker
                'type': 'entry',
                'components': entry.components
            }
        elif agent_type == 'kb' and agent_key in self.kb_agents:
            entry = self.kb_agents[agent_key]
            return {
                'agent_config': entry.agent_config,
                'tools_definition': '',  # KB agents don't have tools
                'dockerfile': '',  # KB agents don't need Docker
                'type': 'kb'
            }
        elif agent_type == 'tool' and agent_key in self.agents:
            entry = self.agents[agent_key]
            return {
                'agent_config': entry.agent_config,
                'tools_definition': entry.tools_definition,
                'dockerfile': entry.dockerfile,
                'env_vars': entry.env_vars,
                'tool_definition': entry.tool_definition,
                'type': 'tool'
            }
        
        # Fallback to original logic for backward compatibility
        if agent_key in self.agents:
            entry = self.agents[agent_key]
            return {
                'agent_config': entry.agent_config,
                'tools_definition': entry.tools_definition,
                'dockerfile': entry.dockerfile,
                'env_vars': entry.env_vars,
                'tool_definition': entry.tool_definition,
                'type': 'tool'
            }
        elif agent_key in self.workflow_agents:
            entry = self.workflow_agents[agent_key]
            return {
                'agent_config': entry.agent_config,
                'tools_definition': '',  # Workflow agents don't have tools
                'dockerfile': '',  # Workflow agents don't need Docker
                'type': 'entry',
                'components': entry.components
            }
        elif agent_key in self.kb_agents:
            entry = self.kb_agents[agent_key]
            return {
                'agent_config': entry.agent_config,
                'tools_definition': '',  # KB agents don't have tools
                'dockerfile': '',  # KB agents don't need Docker
                'type': 'kb'
            }
        else:
            raise ValueError(f"Agent not found: {agent_key}")
    
    def validate_agent_files(self, agent_key: str) -> Dict[str, Any]:
        """Validate that all required files exist for an agent"""
        if agent_key in self.agents:
            entry = self.agents[agent_key]
            return {
                'agent_config': os.path.exists(entry.agent_config) if entry.agent_config else False,
                'tools_definition': os.path.exists(entry.tools_definition) if entry.tools_definition else False,
                'dockerfile': os.path.exists(entry.dockerfile) if entry.dockerfile else False,
                'type': 'regular'
            }
        elif agent_key in self.workflow_agents:
            entry = self.workflow_agents[agent_key]
            validation = {
                'agent_config': os.path.exists(entry.agent_config) if entry.agent_config else False,
                'type': 'entry'
            }
            # Validate component files
            for i, component in enumerate(entry.components):
                component_config = component.get('agent_config', '')
                validation[f'component_{i}_config'] = os.path.exists(component_config) if component_config else False
            return validation
        elif agent_key in self.kb_agents:
            entry = self.kb_agents[agent_key]
            return {
                'agent_config': os.path.exists(entry.agent_config) if entry.agent_config else False,
                'type': 'kb'
            }
        else:
            return {}
    
    def validate_agent_files_by_type(self, agent_key: str, agent_type: str) -> Dict[str, Any]:
        """Validate that all required files exist for an agent of a specific type"""
        if agent_type == 'tool' or agent_type == 'regular':
            # Check tool agents
            if agent_key in self.agents:
                entry = self.agents[agent_key]
                return {
                    'agent_config': os.path.exists(entry.agent_config) if entry.agent_config else False,
                    'tools_definition': os.path.exists(entry.tools_definition) if entry.tools_definition else False,
                    'dockerfile': os.path.exists(entry.dockerfile) if entry.dockerfile else False,
                    'type': 'tool'
                }
            else:
                return {}
        elif agent_type == 'entry':
            # Check workflow agents
            if agent_key in self.workflow_agents:
                entry = self.workflow_agents[agent_key]
                validation = {
                    'agent_config': os.path.exists(entry.agent_config) if entry.agent_config else False,
                    'type': 'entry'
                }
                # Validate component files
                for i, component in enumerate(entry.components):
                    component_config = component.get('agent_config', '')
                    validation[f'component_{i}_config'] = os.path.exists(component_config) if component_config else False
                return validation
            else:
                return {}
        elif agent_type == 'kb':
            # Check knowledge base agents
            if agent_key in self.kb_agents:
                entry = self.kb_agents[agent_key]
                return {
                    'agent_config': os.path.exists(entry.agent_config) if entry.agent_config else False,
                    'type': 'kb'
                }
            else:
                return {}
        else:
            # Unknown type, fall back to original behavior
            return self.validate_agent_files(agent_key)
    
    def reload_catalog(self):
        """Reload the catalog from disk (clears cache)"""
        self.agents.clear()
        self.workflow_agents.clear()
        self.kb_agents.clear()
        self.agent_info_cache.clear()
        self._load_catalog()

    def get_coordinated_agents(self, workflow_agent_key: str) -> List[str]:
        """Infer coordinated agents from a workflow agent's workflow YAML definition.

        Parses the workflow YAML (agent_config) and extracts external agent names
        from state actors, filtering out internal workflow components (planner,
        router, summarizer, orchestrator).

        Args:
            workflow_agent_key: Key of the workflow agent in the catalog.

        Returns:
            List of external agent names referenced in the workflow, or empty list
            if the workflow cannot be loaded or parsed.
        """
        if workflow_agent_key not in self.workflow_agents:
            return []

        entry = self.workflow_agents[workflow_agent_key]
        if not entry.agent_config:
            return []

        # Resolve relative path from catalog directory
        catalog_dir = os.path.dirname(self.catalog_path)
        workflow_file = os.path.normpath(os.path.join(catalog_dir, entry.agent_config))

        if not os.path.exists(workflow_file):
            return []

        try:
            config = load_yaml_robust(workflow_file, normalize_chars=True)
        except Exception:
            return []

        if not config or not isinstance(config, dict):
            return []

        states = config.get('states', [])
        if not isinstance(states, list):
            return []

        # Also collect component agent names to exclude them
        internal_keywords = {'planner', 'router', 'summarizer', 'orchestrator', 'workflow'}
        component_names = set()
        for comp in entry.components:
            if isinstance(comp, dict):
                comp_name = comp.get('name', '')
                if comp_name:
                    component_names.add(comp_name.lower())

        coordinated = []
        for state in states:
            if not isinstance(state, dict):
                continue
            for actor in state.get('actors', []):
                if not isinstance(actor, dict):
                    continue
                agent_name = actor.get('agent', '')
                if not agent_name or agent_name in coordinated:
                    continue
                name_lower = agent_name.lower()
                # Skip internal workflow components
                if any(kw in name_lower for kw in internal_keywords):
                    continue
                if name_lower in component_names:
                    continue
                coordinated.append(agent_name)

        return coordinated

    # ------------------------------
    # Catalog Update Helpers
    # ------------------------------
    def update_tool_agent_env_vars(self, agent_key: str, env_vars_rel_path: str) -> bool:
        """Persist (add or replace) env_vars path for a tool agent in the catalog.

        Args:
            agent_key: Derived key of the tool agent (must exist in self.agents).
            env_vars_rel_path: Relative path (forward slashes) to the EnvVars JSON file.

        Returns:
            True on successful update and catalog reload, else False.
        """
        try:
            # Ensure agent exists in memory (and is a tool agent)
            if agent_key not in self.agents:
                logger.info(f"Tool agent '{agent_key}' not loaded in manager; cannot set env_vars")
                return False

            if not os.path.exists(self.catalog_path):
                logger.info(f" Cannot update catalog; file missing: {self.catalog_path}")
                return False

            # Use robust YAML loading
            catalog_data = load_yaml_robust(self.catalog_path, normalize_chars=True) or {}

            tool_agents = catalog_data.get('tool_agents', [])
            target_config_path = self.agents[agent_key].agent_config

            found = False
            for ta in tool_agents:
                if ta.get('agent_config') == target_config_path:
                    ta['env_vars'] = env_vars_rel_path
                    found = True
                    break

            if not found:
                logger.info(f" Catalog desync: no tool agent entry with agent_config '{target_config_path}' (key='{agent_key}')")
                return False

            catalog_data['tool_agents'] = tool_agents

            tmp_path = self.catalog_path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(catalog_data, f, sort_keys=False)
            os.replace(tmp_path, self.catalog_path)

            # Refresh in-memory structures so subsequent calls see the new env_vars
            self.reload_catalog()
            return True
        except Exception as e:
            logger.info(f" Failed to update env_vars for {agent_key}: {e}")
            return False

