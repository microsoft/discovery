"""
Microsoft Discovery Configuration Parser

Handles parsing of agent and tool YAML files, extracting metadata,
and generating resource names for Microsoft Discovery publishing.
"""

import yaml
import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from discovery_config_manager import DiscoveryConfigManager

# Import robust file loading utilities
from file_utils import load_yaml_robust, FileEncodingError


class DiscoveryConfigParser:
    """Parser for Microsoft Discovery agent and tool configurations."""
    
    def __init__(self):
        self.config_manager = DiscoveryConfigManager()
        self.supported_api_versions = {
            'tool': '2025-07-01-preview',
            'agent': '2025-07-01-preview',
            'definition': '2025-05-15-preview'
        }
    
    def parse_agent_config(self, agent_config_path: str) -> Dict[str, Any]:
        """Parse agent YAML configuration file."""
        try:
            # Use robust YAML loading with encoding detection and normalization
            agent_data = load_yaml_robust(agent_config_path, normalize_chars=True)
            
            if 'agent' not in agent_data:
                raise ValueError(f"Invalid agent configuration: missing 'agent' section in {agent_config_path}")
            
            agent_info = agent_data['agent']
            
            # Extract and validate required fields
            parsed_config = {
                'name': agent_info.get('name', ''),
                'description': agent_info.get('description', ''),
                'model': agent_info.get('model', self.config_manager.get_llm_endpoint()),
                'temperature': agent_info.get('temperature', 0),
                'top_p': agent_info.get('top_p', 0),
                'response_format': agent_info.get('response_format', 'auto'),
                'instructions': agent_info.get('instructions', ''),
                'raw_data': agent_data  # Keep full data for ARM template generation
            }
            
            # Generate resource names
            parsed_config['resource_name'] = self.generate_agent_resource_name(parsed_config['name'])
            
            return parsed_config
        
        except FileEncodingError as e:
            raise Exception(f"Encoding error parsing agent config {agent_config_path}: {str(e)}")
        except Exception as e:
            raise Exception(f"Failed to parse agent config {agent_config_path}: {str(e)}")
    
    def parse_tool_definition(self, tool_definition_path: str) -> Dict[str, Any]:
        """Parse tool definition YAML file."""
        try:
            # Use robust YAML loading with encoding detection and normalization
            tool_data = load_yaml_robust(tool_definition_path, normalize_chars=True)
            
            # Extract ACR image information
            acr_image = None
            if 'infra' in tool_data and len(tool_data['infra']) > 0:
                infra = tool_data['infra'][0]
                if 'image' in infra and 'acr' in infra['image']:
                    acr_image = infra['image']['acr']
            
            parsed_config = {
                'name': tool_data.get('name', ''),
                'description': tool_data.get('description', ''),
                'version': tool_data.get('version', '1.0.0'),
                'category': tool_data.get('category', ''),
                'license': tool_data.get('license', 'MIT'),
                'acr_image': acr_image,
                'infra': tool_data.get('infra', []),
                'code_environments': tool_data.get('code_environments', []),
                'actions': tool_data.get('actions', []),
                'raw_data': tool_data  # Keep full data for ARM template generation
            }
            
            # Generate resource names
            parsed_config['resource_name'] = self.generate_tool_resource_name(parsed_config['name'])
            
            return parsed_config
            
        except Exception as e:
            raise Exception(f"Failed to parse tool definition {tool_definition_path}: {str(e)}")
    
    def generate_agent_resource_name(self, agent_name: str, version: str = "v1") -> str:
        """Generate Azure resource name for agent."""
        # Sanitize name for Azure resource naming
        sanitized = re.sub(r'[^a-zA-Z0-9]', '-', agent_name.lower())
        sanitized = re.sub(r'-+', '-', sanitized)  # Remove multiple consecutive dashes
        sanitized = sanitized.strip('-')  # Remove leading/trailing dashes
        
        return f"{sanitized}-agent-{version}"
    
    def generate_tool_resource_name(self, tool_name: str, version: str = "v1") -> str:
        """Generate Azure resource name for tool."""
        # Sanitize name for Azure resource naming
        sanitized = re.sub(r'[^a-zA-Z0-9]', '-', tool_name.lower())
        sanitized = re.sub(r'-+', '-', sanitized)  # Remove multiple consecutive dashes
        sanitized = sanitized.strip('-')  # Remove leading/trailing dashes
        
        return f"{sanitized}-tool-{version}"
    
    def extract_acr_image_info(self, acr_image_url: str) -> Dict[str, str]:
        """Extract ACR registry, image name, and tag from ACR URL."""
        try:
            # Parse ACR URL: registry.azurecr.io/image:tag
            parts = acr_image_url.split('/')
            if len(parts) < 2:
                raise ValueError("Invalid ACR image URL format")
            
            registry = parts[0]
            image_with_tag = parts[-1]
            
            if ':' in image_with_tag:
                image_name, tag = image_with_tag.rsplit(':', 1)
            else:
                image_name = image_with_tag
                tag = 'latest'
            
            return {
                'registry': registry,
                'image_name': image_name,
                'tag': tag,
                'full_url': acr_image_url
            }
            
        except Exception as e:
            raise Exception(f"Failed to parse ACR image URL {acr_image_url}: {str(e)}")
    
    def validate_configuration(self, agent_config: Dict[str, Any], tool_config: Dict[str, Any]) -> bool:
        """Validate that agent and tool configurations are compatible."""
        validation_errors = []
        
        # Check required agent fields
        if not agent_config.get('name'):
            validation_errors.append("Agent name is required")
        
        if not agent_config.get('model'):
            validation_errors.append("Agent model is required")
        
        # Check required tool fields
        if not tool_config.get('name'):
            validation_errors.append("Tool name is required")
        
        if not tool_config.get('acr_image'):
            validation_errors.append("Tool ACR image is required")
        
        # Check ACR image format
        if tool_config.get('acr_image'):
            try:
                self.extract_acr_image_info(tool_config['acr_image'])
            except Exception as e:
                validation_errors.append(f"Invalid ACR image format: {str(e)}")
        
        if validation_errors:
            raise ValueError("Configuration validation failed: " + "; ".join(validation_errors))
        
        return True
    
    def get_api_versions(self) -> Dict[str, str]:
        """Get supported API versions for Microsoft Discovery resources."""
        return self.supported_api_versions.copy()


class AgentCatalogParser:
    """Parser for the agents catalog YAML file."""
    
    def __init__(self, catalog_path: str = "agents-catalog.yaml"):
        self.catalog_path = catalog_path
        self.config_parser = DiscoveryConfigParser()
    
    def load_catalog(self) -> Dict[str, Any]:
        """Load the agents catalog file."""
        try:
            # Use robust YAML loading with encoding detection and normalization
            return load_yaml_robust(self.catalog_path, normalize_chars=True)
        except FileEncodingError as e:
            raise Exception(f"Encoding error loading agents catalog {self.catalog_path}: {str(e)}")
        except Exception as e:
            raise Exception(f"Failed to load agents catalog {self.catalog_path}: {str(e)}")
    

    def get_agent_info(self, agent_key: str, agent_type: str) -> Optional[Dict[str, Any]]:
        """Get information for a specific agent from the catalog by agent key (directory name).

        agent_type is required and must be one of the catalog sections:
        "agents", "tool_agents", "entry_agents", or "kb_agents". The
        search will be restricted to that section and will match only the
        explicit `name` field of catalog items.
        """
        catalog = self.load_catalog()

        # Candidate sections (backwards-compatible with older catalogs)
        candidate_sections = ['agents', 'tool_agents', 'entry_agents', 'kb_agents']

        # Validate and restrict the search to the provided agent_type
        normalized = agent_type.strip().lower()
        if normalized not in candidate_sections:
            raise ValueError(f"Unknown agent_type '{agent_type}', expected one of: {', '.join(candidate_sections)}")
        search_sections = [normalized]

        found_item = None
        found_section = None

        for section in search_sections:
            for item in catalog.get(section, []):
                # Direct name match (case-insensitive) only — callers must
                # provide the correct agent_type and items have a `name` field.
                item_name = item.get('name')
                if item_name and item_name.lower() == agent_key.lower():
                    found_item = item
                    found_section = section
                    break
            if found_item:
                break

        if not found_item:
            return None

        # Resolve paths
        agent_config_path = found_item.get('agent_config') or found_item.get('agent_config_path')
        tool_definition_path = found_item.get('tools_definition') or found_item.get('tools_definition_path') or found_item.get('tools_definition') or found_item.get('tool_definition')
        dockerfile_path = found_item.get('dockerfile') or found_item.get('dockerfile_path')

        # If workflow agent and no tool_definition found, try to resolve from coordinated agents
        # (coordinated_agents are no longer stored in catalog; infer from workflow YAML if agent_manager available)
        if (not tool_definition_path) and found_section == 'entry_agents':
            coordinated = found_item.get('coordinated_agents') or []
            if not coordinated:
                # Try dynamic inference via agent_manager if available
                try:
                    from agent_manager import StaticAgentManager
                    # Note: this is a fallback — callers with an agent_manager instance
                    # should use agent_manager.get_coordinated_agents() directly
                except Exception:
                    pass
            if coordinated:
                coord_name = coordinated[0]
                # Search tool_agents for matching coordinated tool by name
                for tool_item in catalog.get('tool_agents', []):
                    tname = tool_item.get('name')
                    if tname and tname.lower() == coord_name.lower():
                        tool_definition_path = tool_item.get('tools_definition') or tool_item.get('tools_definition_path') or tool_item.get('tool_definition')
                        dockerfile_path = dockerfile_path or tool_item.get('dockerfile')
                        break

        try:
            agent_config = self.config_parser.parse_agent_config(agent_config_path) if agent_config_path else None
        except Exception as e:
            print(f"Error parsing agent config for {agent_key}: {str(e)}")
            agent_config = None

        return {
            'agent_config_path': agent_config_path,
            'tool_definition_path': tool_definition_path,
            'dockerfile_path': dockerfile_path,
            'agent_config': agent_config,
            'catalog_section': found_section
        }
    
    def get_all_agents(self) -> list:
        """Get information for all agents in the catalog."""
        catalog = self.load_catalog()
        agents = []
        
        for agent in catalog.get('agents', []):
            try:
                agent_config = self.config_parser.parse_agent_config(agent['agent_config'])
                tool_config = self.config_parser.parse_tool_definition(agent['tools_definition'])
                
                agents.append({
                    'name': agent_config['name'],
                    'description': agent_config['description'],
                    'agent_config_path': agent['agent_config'],
                    'tool_definition_path': agent['tools_definition'],
                    'dockerfile_path': agent['dockerfile'],
                    'agent_config': agent_config,
                    'tool_config': tool_config
                })
            except Exception as e:
                print(f"Warning: Failed to parse agent configuration: {str(e)}")
                continue
        
        return agents


def main():
    """Test the configuration parser."""
    parser = DiscoveryConfigParser()
    catalog_parser = AgentCatalogParser()
    
    # Test parsing a specific agent
    try:
        agents = catalog_parser.get_all_agents()
        print(f"Found {len(agents)} agents in catalog:")
        
        for agent in agents:
            print(f"\nAgent: {agent['name']}")
            print(f"Description: {agent['description']}")
            print(f"Tool: {agent['tool_config']['name']}")
            print(f"ACR Image: {agent['tool_config']['acr_image']}")
            print(f"Agent Resource Name: {agent['agent_config']['resource_name']}")
            print(f"Tool Resource Name: {agent['tool_config']['resource_name']}")
            
    except Exception as e:
        print(f"Error: {str(e)}")


if __name__ == "__main__":
    main()
