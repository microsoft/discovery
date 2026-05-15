#!/usr/bin/env python3
"""
Common utilities shared between MCP server and web server

This module provides ONLY truly shared utility functions:
- Logging setup
- Docker helper functions
- Validation utilities
- Config file discovery

Both servers should directly import and instantiate their own
StaticAgentManager and DiscoveryConfigManager instances.
"""

import os
import sys
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

# Module logger
logger = logging.getLogger(__name__)

# Try to import Docker
try:
    import docker
    import docker.errors
    HAS_DOCKER = True
except ImportError:
    HAS_DOCKER = False
    docker = None

# Try to import validators
try:
    from pathlib import Path
    _this_file = Path(__file__).resolve()
    _agent_test_dir = _this_file.parent
    _utils_dir = _agent_test_dir.parent
    _repo_root = _utils_dir.parent
    _js_dir = _agent_test_dir / 'js'
    
    for _p in (_repo_root, _utils_dir, _js_dir):
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    
    from Utils.validators import validate_yaml, ValidationResult
    HAS_VALIDATORS = True
except ImportError:
    try:
        import runpy
        _validators_path = _js_dir / 'validators.py'
        if _validators_path.exists():
            _vd = runpy.run_path(str(_validators_path))
            validate_yaml = _vd.get('validate_yaml')
            ValidationResult = _vd.get('ValidationResult')
            HAS_VALIDATORS = validate_yaml is not None
        else:
            HAS_VALIDATORS = False
            validate_yaml = None
            ValidationResult = None
    except Exception:
        HAS_VALIDATORS = False
        validate_yaml = None
        ValidationResult = None


# ============================================================================
# LOGGING UTILITIES
# ============================================================================

def setup_logging(level: int = logging.INFO, reduce_azure_noise: bool = True):
    """
    Setup common logging configuration
    
    Args:
        level: Logging level (default: INFO)
        reduce_azure_noise: Whether to reduce Azure SDK logging (default: True)
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Reduce Azure SDK logging noise
    if reduce_azure_noise:
        try:
            logging.getLogger('azure.identity').setLevel(logging.WARNING)
            logging.getLogger('azure.core.pipeline').setLevel(logging.WARNING)
            logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.WARNING)
            logging.getLogger('azure.storage.blob').setLevel(logging.WARNING)
        except Exception:
            pass


# ============================================================================
# DOCKER UTILITIES
# ============================================================================

class DockerUtils:
    """Shared Docker utilities"""
    
    @staticmethod
    def get_docker_client():
        """
        Get a Docker client instance
        
        Returns:
            Docker client or None if not available
        """
        if not HAS_DOCKER:
            return None
        
        try:
            return docker.from_env()
        except Exception as e:
            logging.error(f"Failed to create Docker client: {e}")
            return None
    
    @staticmethod
    def list_containers(client=None, all_containers: bool = True) -> List[Dict[str, Any]]:
        """
        List Docker containers
        
        Args:
            client: Docker client (will create if None)
            all_containers: Include stopped containers
            
        Returns:
            List of container information
        """
        if client is None:
            client = DockerUtils.get_docker_client()
        
        if not client:
            return []
        
        try:
            containers = client.containers.list(all=all_containers)
            return [
                {
                    "id": container.short_id,
                    "name": container.name,
                    "status": container.status,
                    "image": container.image.tags[0] if container.image.tags else "unknown",
                    "created": container.attrs.get("Created", ""),
                    "state": container.attrs.get("State", {})
                }
                for container in containers
            ]
        except Exception as e:
            logging.error(f"Error listing containers: {e}")
            return []


class ValidationUtils:
    """Shared validation utilities"""
    
    @staticmethod
    def has_validators() -> bool:
        """Check if validator functions are available"""
        return HAS_VALIDATORS
    
    @staticmethod
    def validate_agent_yaml(yaml_content: str, schema_path: Optional[str] = None) -> Optional[Any]:
        """
        Validate agent YAML against schema
        
        Args:
            yaml_content: YAML content to validate
            schema_path: Optional path to schema file
            
        Returns:
            ValidationResult or None if validators not available
        """
        if not HAS_VALIDATORS or not validate_yaml:
            logging.warning("Validators not available")
            return None
        
        try:
            if schema_path:
                return validate_yaml(schema_path, yaml_content)
            else:
                # Use default schema path if available
                return validate_yaml(yaml_content)
        except Exception as e:
            logging.error(f"Validation error: {e}")
            return None
    
    @staticmethod
    def load_schema(schema_path: str) -> Optional[Dict[str, Any]]:
        """
        Load JSON schema from file
        
        Args:
            schema_path: Path to schema file
            
        Returns:
            Schema dictionary or None
        """
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading schema {schema_path}: {e}")
            return None


# ============================================================================
# FILE DISCOVERY UTILITIES
# ============================================================================

def find_config_file(filename: str = "discovery_config.json") -> Optional[str]:
    """
    Find configuration file in common locations
    
    Args:
        filename: Name of config file to find
        
    Returns:
        Path to config file or None
    """
    # Get the workbench directory
    workbench_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Common locations to check
    locations = [
        os.path.join(workbench_dir, filename),
        os.path.join(os.getcwd(), filename),
        os.path.join(workbench_dir, "..", filename),
    ]
    
    for location in locations:
        if os.path.exists(location):
            return location
    
    return None


def find_catalog_file(filename: str = "agents-catalog.yaml") -> Optional[str]:
    """
    Find agent catalog file in common locations
    
    Args:
        filename: Name of catalog file to find
        
    Returns:
        Path to catalog file or None
    """
    return find_config_file(filename)


def create_default_config(config_path: Optional[str] = None) -> str:
    """
    Create a default discovery_config.json file
    
    Args:
        config_path: Optional path for config file
        
    Returns:
        Path to created config file
    """
    default_config = {
        "azure": {
            "subscription_id": "your-subscription-id",
            "resource_group": "your-resource-group",
            "region": "East US"
        },
        "supercomputers": {},
        "directories": {
            "experiments": "./experiments",
            "results": "./results"
        }
    }
    
    if not config_path:
        workbench_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(workbench_dir, "discovery_config.json")
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2)
        logging.info(f"Created default discovery config at: {config_path}")
        return config_path
    except Exception as e:
        logging.error(f"Failed to create default config: {e}")
        return config_path


def create_default_catalog(catalog_path: Optional[str] = None) -> str:
    """
    Create a default agents-catalog.yaml file
    
    Args:
        catalog_path: Optional path for catalog file
        
    Returns:
        Path to created catalog file
    """
    default_catalog = """# Discovery Agent Catalog
# This file defines the available agents and their configurations

agents:
  sample-agent:
    name: "Sample Agent"
    description: "A sample agent for demonstration purposes"
    type: "general"
    docker_image: "discovery/sample-agent:latest"
    capabilities:
      - "text-processing"
      - "data-analysis"
    configuration:
      memory_limit: "2Gi"
      cpu_limit: "1000m"
"""
    
    if not catalog_path:
        workbench_dir = os.path.dirname(os.path.abspath(__file__))
        catalog_path = os.path.join(workbench_dir, "agents-catalog.yaml")
    
    try:
        with open(catalog_path, 'w', encoding='utf-8') as f:
            f.write(default_catalog)
        logging.info(f"Created default agent catalog at: {catalog_path}")
        return catalog_path
    except Exception as e:
        logging.error(f"Failed to create default catalog: {e}")
        return catalog_path


# ============================================================================
# INITIALIZATION HELPERS
# ============================================================================

def initialize_managers(catalog_path: Optional[str] = None, 
                       config_path: Optional[str] = None):
    """
    Helper function to initialize agent and config managers
    
    Args:
        catalog_path: Path to agent catalog file (will auto-discover if None)
        config_path: Path to discovery config file (will auto-discover if None)
        
    Returns:
        Tuple of (agent_manager, config_manager) or (None, None) on failure
    """
    try:
        from agent_manager import StaticAgentManager
        from discovery_config_manager import DiscoveryConfigManager
    except ImportError as e:
        logging.error(f"Failed to import workbench components: {e}")
        return None, None
    
    # Auto-discover config files if not provided
    if not catalog_path:
        catalog_path = find_catalog_file()
        if not catalog_path:
            logging.warning("No agent catalog found, creating default")
            catalog_path = create_default_catalog()
    
    if not config_path:
        config_path = find_config_file()
        if not config_path:
            logging.warning("No discovery config found, creating default")
            config_path = create_default_config()
    
    # Initialize managers
    agent_manager = None
    config_manager = None
    
    try:
        if catalog_path and os.path.exists(catalog_path):
            agent_manager = StaticAgentManager(catalog_path)
            logging.info(f"Agent manager initialized with catalog: {catalog_path}")
        else:
            logging.warning(f"Catalog path not found: {catalog_path}")
    except Exception as e:
        logging.error(f"Failed to initialize agent manager: {e}")
    
    try:
        if config_path and os.path.exists(config_path):
            config_manager = DiscoveryConfigManager(config_path)
            logging.info(f"Config manager initialized with config: {config_path}")
        else:
            logging.warning(f"Config path not found: {config_path}")
    except Exception as e:
        logging.error(f"Failed to initialize config manager: {e}")
    
    return agent_manager, config_manager


# ============================================================================
# WORKFLOW DIAGRAM GENERATION
# ============================================================================

def generate_workflow_diagram(
    workflow_yaml: str,
    endpoint: str,
    deployment: str,
    api_key: Optional[str] = None,
    api_version: str = "2024-12-01-preview",
    azure_token: Optional[str] = None,
    prompt_template_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate a Mermaid diagram from workflow YAML using Azure OpenAI LLM
    
    This is a shared utility function that can be used by both the web server
    and MCP server to generate workflow diagrams.
    
    Args:
        workflow_yaml: YAML content of the workflow
        endpoint: Azure OpenAI endpoint URL
        deployment: Azure OpenAI deployment name
        api_key: Optional API key for Azure OpenAI (preferred method)
        api_version: Azure OpenAI API version (default: 2024-12-01-preview)
        azure_token: Optional Azure AD bearer token (fallback if no api_key)
        prompt_template_path: Optional path to custom prompt template file
        
    Returns:
        Dictionary with keys:
        - success (bool): Whether generation succeeded
        - diagram (str): Generated Mermaid diagram text (if successful)
        - error (str): Error message (if failed)
        
    Example:
        >>> result = generate_workflow_diagram(
        ...     workflow_yaml=yaml_content,
        ...     endpoint="https://my-openai.openai.azure.com/",
        ...     deployment="gpt-4",
        ...     api_key="my-api-key"
        ... )
        >>> if result['success']:
        ...     print(result['diagram'])
    """
    try:
        import requests
        
        # Mermaid init fence for proper rendering
        MERMAID_INIT_FENCE = '%%{init: {"sequence": {"mirrorActors": false, "messageAlign": "center"}}}%%'
        
        # Compose the prompt
        escaped_yaml = str(workflow_yaml).replace("'", "''")
        
        # Try to load custom prompt template if provided
        if prompt_template_path and os.path.exists(prompt_template_path):
            try:
                with open(prompt_template_path, 'r', encoding='utf-8') as f:
                    template = f.read()
                prompt = template.replace('{yaml}', escaped_yaml)
            except Exception as e:
                logging.warning(f"Failed to load prompt template from {prompt_template_path}: {e}")
                prompt = None
        else:
            prompt = None
        
        # Fallback to inline template
        if not prompt:
            prompt = (
                "Generate a Mermaid sequence diagram from the provided workflow YAML. "
                "Return ONLY Mermaid text.\n\n"
                "Requirements:\n"
                "- Use sequenceDiagram syntax\n"
                "- Include autonumber\n"
                "- Define participants (User + one per agent, use aliases when needed)\n"
                "- Use alt/else blocks for routing events\n"
                "- Add colored rect blocks for context\n"
                "- Balance activate/deactivate calls\n"
                "- Output strict Mermaid lines only (no prose)\n\n"
                "YAML:\n"
                f"'{escaped_yaml}'\n"
            )
        
        # Build Azure OpenAI Chat Completions URL
        url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        
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
        
        # Build auth headers
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['api-key'] = api_key
        elif azure_token:
            headers['Authorization'] = f"Bearer {azure_token}"
        else:
            return {
                'success': False,
                'error': 'Authentication required: provide either api_key or azure_token'
            }
        
        # Make the request
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if resp.status_code != 200:
            return {
                'success': False,
                'error': f"LLM request failed: {resp.status_code} {resp.text[:500]}"
            }
        
        data = resp.json()
        diagram = None
        
        # Extract diagram from response
        try:
            if isinstance(data, dict) and data.get('choices'):
                diagram = (data['choices'][0].get('message', {}) or {}).get('content', '')
        except Exception:
            diagram = None
        
        if not diagram:
            # Fallback extraction
            diagram = (data.get('diagram') or data.get('text') or '').strip() if isinstance(data, dict) else ''
        
        if not diagram:
            return {
                'success': False,
                'error': 'No content returned by LLM'
            }
        
        # Clean up the diagram
        content = diagram.strip()
        
        # Strip code fences if present
        if content.startswith('```') and content.endswith('```'):
            first_nl = content.find('\n')
            last_fence = content.rfind('```')
            if first_nl != -1 and last_fence != -1 and last_fence > first_nl:
                content = content[first_nl+1:last_fence].strip()
        
        # Normalize line endings
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        
        # Ensure init fence is present
        head = content.lstrip()
        if not head.startswith('%%{init:'):
            content = f"{MERMAID_INIT_FENCE}\n{content}"
        
        # Fix common LLM error: "Endend" instead of "End\nend"
        try:
            import re
            content = re.sub(
                r'(^[^\n]*?:[^\n]*?)\b[Ee]ndend(\s*$)',
                r'\1End\nend\2',
                content,
                flags=re.MULTILINE
            )
        except Exception:
            pass
        
        return {
            'success': True,
            'diagram': content
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


# =====================================
# Azure Supercomputer Utilities
# =====================================

def get_azure_access_token(scope: str = "https://management.azure.com/.default") -> Optional[str]:
    """Get Azure access token using DefaultAzureCredential
    
    Args:
        scope: The Azure scope to request token for (default: management.azure.com)
        
    Returns:
        Access token string or None if acquisition fails
    """
    try:
        from azure.identity import DefaultAzureCredential
        
        credential = DefaultAzureCredential()
        token = credential.get_token(scope)
        return token.token
    except ImportError:
        logger.warning("azure-identity not available")
        return None
    except Exception as e:
        logger.error(f"Failed to get Azure token: {e}")
        return None


def list_azure_supercomputers(subscription_id: str, resource_group: str, 
                               access_token: str, api_version: str = "2025-07-01-preview") -> Dict[str, Any]:
    """List all supercomputers in a resource group
    
    Args:
        subscription_id: Azure subscription ID
        resource_group: Azure resource group name
        access_token: Azure management access token
        api_version: API version to use (default: 2025-07-01-preview)
        
    Returns:
        Dict with success, supercomputers list, or error
    """
    try:
        import requests
        
        url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/supercomputers"
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        params = {'api-version': api_version}
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            supercomputers = data.get('value', [])
            
            # Transform to simpler format
            supercomputer_list = []
            for sc in supercomputers:
                properties = sc.get('properties', {})
                supercomputer_list.append({
                    'name': sc.get('name', ''),
                    'id': sc.get('id', ''),
                    'location': sc.get('location', ''),
                    'type': sc.get('type', ''),
                    'provisioningState': properties.get('provisioningState', ''),
                    'status': properties.get('status', ''),
                    'resourceGroup': resource_group
                })
            
            return {
                'success': True,
                'supercomputers': supercomputer_list,
                'count': len(supercomputer_list)
            }
        else:
            return {
                'success': False,
                'error': f"Azure API returned {response.status_code}: {response.text}"
            }
            
    except Exception as e:
        return {'success': False, 'error': f"Failed to fetch supercomputers: {str(e)}"}


def get_supercomputer_nodepools(subscription_id: str, resource_group: str, 
                                supercomputer_name: str, access_token: str,
                                api_version: str = "2025-07-01-preview") -> Dict[str, Any]:
    """Get nodepools for a specific supercomputer
    
    Args:
        subscription_id: Azure subscription ID
        resource_group: Azure resource group name
        supercomputer_name: Name of the supercomputer
        access_token: Azure management access token
        api_version: API version to use (default: 2025-07-01-preview)
        
    Returns:
        Dict with success, nodepools list, or error
    """
    try:
        import requests
        
        url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/supercomputers/{supercomputer_name}/nodepools"
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        params = {'api-version': api_version}
        
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            nodepools = data.get('value', [])
            
            # Transform to simpler format
            nodepool_list = []
            for np in nodepools:
                properties = np.get('properties', {})
                nodepool_list.append({
                    'name': np.get('name', ''),
                    'id': np.get('id', ''),
                    'vmSize': properties.get('vmSize', 'Unknown'),
                    'maxNodes': properties.get('maxNodeCount', 0),
                    'minNodes': properties.get('minNodeCount', 0),
                    'currentNodes': properties.get('currentNodeCount', 0),
                    'provisioningState': properties.get('provisioningState', ''),
                    'location': np.get('location', ''),
                    'type': np.get('type', ''),
                    'subnetId': properties.get('subnetId', '')
                })
            
            return {
                'success': True,
                'nodepools': nodepool_list,
                'count': len(nodepool_list)
            }
        else:
            return {
                'success': False,
                'error': f"Azure API returned {response.status_code}: {response.text}"
            }
            
    except Exception as e:
        return {'success': False, 'error': f"Failed to fetch nodepools: {str(e)}"}


def get_supercomputer_details(subscription_id: str, resource_group: str, 
                              supercomputer_name: str, access_token: str,
                              api_version: str = "2025-07-01-preview") -> Dict[str, Any]:
    """Get detailed information about a supercomputer including its nodepools
    
    Args:
        subscription_id: Azure subscription ID
        resource_group: Azure resource group name
        supercomputer_name: Name of the supercomputer
        access_token: Azure management access token
        api_version: API version to use (default: 2025-07-01-preview)
        
    Returns:
        Dict with success, supercomputer details with nodepools, or error
    """
    try:
        import requests
        
        # Get supercomputer details
        sc_url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/supercomputers/{supercomputer_name}"
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        params = {'api-version': api_version}
        
        sc_response = requests.get(sc_url, headers=headers, params=params, timeout=30)
        
        if sc_response.status_code != 200:
            return {
                'success': False,
                'error': f"Supercomputer '{supercomputer_name}' not found: {sc_response.status_code} {sc_response.text}"
            }
        
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
        
        # Get nodepools
        nodepools_result = get_supercomputer_nodepools(
            subscription_id, resource_group, supercomputer_name, access_token, api_version
        )
        
        if nodepools_result.get('success'):
            supercomputer_info['nodepools'] = nodepools_result.get('nodepools', [])
            supercomputer_info['nodepool_count'] = nodepools_result.get('count', 0)
        else:
            supercomputer_info['nodepool_error'] = nodepools_result.get('error', 'Failed to fetch nodepools')
        
        return {'success': True, 'supercomputer': supercomputer_info}
        
    except Exception as e:
        return {'success': False, 'error': f"Failed to get supercomputer details: {str(e)}"}

