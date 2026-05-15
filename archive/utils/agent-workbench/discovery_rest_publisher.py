"""
Discovery REST API Publisher
Handles publishing tools and agents to Microsoft Discovery platform using REST API

Configuration:
- Uses DiscoveryConfigManager for persistent configuration
- Requires all parameters to be provided - no defaults or fallbacks
"""

import os
import json
import tempfile
import uuid
from typing import Dict, Any, Optional, Tuple
import subprocess
import platform
from discovery_config_manager import DiscoveryConfigManager
import re
from azure_auth_helpers import azure_rest_call

class DiscoveryRestPublisher:
    """Publisher for Microsoft Discovery platform using REST API calls"""
    
    def __init__(self, subscription_id: Optional[str] = None, 
                 resource_group: Optional[str] = None,
                 location: Optional[str] = None,
                 tenant_id: Optional[str] = None):
        # Load saved configuration first
        config_manager = DiscoveryConfigManager()
        saved_config = config_manager.get_azure_config()
        
        # Use parameters first, then saved config - no defaults or environment variables
        self.subscription_id = subscription_id or saved_config.get('subscription_id') or ""
        self.resource_group = resource_group or saved_config.get('resource_group') or ""
        self.location = location or saved_config.get('location') or ""
        self.tenant_id = tenant_id or ""
        
        # Validate that required configuration is provided
        if not self.subscription_id:
            raise ValueError("Azure subscription ID is required but not provided")
        if not self.resource_group:
            raise ValueError("Azure resource group is required but not provided")
        if not self.location:
            raise ValueError("Azure location is required but not provided")
            
        self.api_version = "2025-07-01-preview"

    # ---- Name validation helpers ----
    def _is_valid_agent_name(self, name: str) -> Tuple[bool, str]:
        """Validate agent name according to publisher rules.

        Rules (from docs/user):
          - Permitted chars: letters (A-Za-z), digits, dashes (-)
          - Length: 3..24
          - Must start and end with a letter; dashes may separate words
        """
        if not name or not isinstance(name, str):
            return False, "Agent name must be a non-empty string"
        # Strict pattern: start with letter, end with letter, total 3-24 chars
        pattern = r'^[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z]$'
        if not re.match(pattern, name):
            return False, (
                "Invalid agent name. Allowed: letters, digits, dashes; length 3-24; "
                "must start and end with a letter. Example: 'search-agent'"
            )
        return True, ""

    def _is_valid_workflow_name(self, name: str) -> Tuple[bool, str]:
        """Validate workflow name according to publisher rules.

        Rules (from docs/user):
          - Permitted chars: letters (A-Za-z), digits (0-9), dashes (-)
          - Length: 3..24
          - Must begin with a letter and end with a letter or digit
        """
        if not name or not isinstance(name, str):
            return False, "Workflow name must be a non-empty string"
        pattern = r'^[A-Za-z][A-Za-z0-9-]{1,22}[A-Za-z0-9]$'
        if not re.match(pattern, name):
            return False, (
                "Invalid workflow name. Allowed: letters, digits, dashes; length 3-24; "
                "must begin with a letter and end with a letter or digit. Example: 'chemistry-workflow'"
            )
        return True, ""

    def create_discovery_tool(self, tool_name: str, tool_definition: Dict[str, Any], location: Optional[str] = None, 
                             preserve_yaml_name: bool = True) -> Dict[str, Any]:
        """Create a Discovery tool using REST API
        
        Args:
            tool_name: Name for the tool resource
            tool_definition: The complete tool definition dictionary
            location: Azure region (optional, defaults to instance location)
            preserve_yaml_name: Whether to use the exact tool definition name instead of generating unique name
        """
        
        # Use provided location or default to instance location
        deploy_location = location or self.location
        
        # Sanitize tool name to be Azure-compatible
        # Pattern: ^[a-zA-Z0-9-]{3,24}$ (letters, numbers, hyphens only, 3-24 chars)
        sanitized_name = tool_name.replace('_', '-').replace(' ', '-')
        # Remove any invalid characters (keep only letters, numbers, hyphens)
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        
        if preserve_yaml_name:
            # Use the tool definition name as-is (sanitized) for consistent publishing
            if len(sanitized_name) > 24:
                # Trim to max allowed length; keep the root of the name
                sanitized_name = sanitized_name[:24]
            # Ensure minimum length of 3 by padding if needed
            if len(sanitized_name) < 3:
                sanitized_name = (sanitized_name + "tool")[:3]
            resource_name = sanitized_name
        else:
            # Generate unique resource name (legacy behavior)
            # Ensure it doesn't exceed length limit when combined with UUID
            max_base_length = 24 - 9  # 24 total - 8 UUID chars - 1 hyphen = 15
            if len(sanitized_name) > max_base_length:
                sanitized_name = sanitized_name[:max_base_length]
            resource_name = f"{sanitized_name}-{str(uuid.uuid4())[:8]}"
        
        # Build REST API URL
        url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
               f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
               f"tools/{resource_name}?api-version={self.api_version}")
        
        # Build request body for tool
        # Ensure required top-level fields are present in definitionContent
        enhanced_definition = {
            "Name": tool_definition.get("name", resource_name),
            "Description": tool_definition.get("description", "Tool definition"),
            "Version": tool_definition.get("version", "1.0.0"),
            "Category": tool_definition.get("category", "General"),
            **tool_definition  # Include all original fields
        }
        
        # Extract environment variables from tool definition if they exist
        env_vars = {}
        if 'properties' in tool_definition and 'environmentVariables' in tool_definition['properties']:
            env_vars = tool_definition['properties']['environmentVariables']
            print(f"DEBUG: Extracted environment variables: {env_vars}")
        else:
            print("DEBUG: No environment variables found in tool definition")
            print(f"DEBUG: Tool definition keys: {list(tool_definition.keys())}")
            if 'properties' in tool_definition:
                print(f"DEBUG: Properties keys: {list(tool_definition['properties'].keys())}")
        
        body = {
            "location": deploy_location,
            "properties": {
                "definitionContent": enhanced_definition,
                "version": "1.0.0",
                "environmentVariables": env_vars
            }
        }
        
        print(f" Creating Discovery tool: {resource_name}")
        
        
        try:
            # Before creating, check if resource already exists using REST API (like agents do)
            check_url = url  # Same URL used for PUT
            
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for create_discovery_tool; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Try to GET the resource first
            try:
                check_response = azure_rest_call(
                    method='GET',
                    url=check_url,
                    subscription_id=self.subscription_id,
                    tenant_id=tenant_id
                )
                # If GET succeeds, resource exists - should update instead
                if check_response.get('success') and check_response.get('data'):
                    response_data = check_response['data']
                    existing_id = response_data.get('id')
                    if existing_id:
                        print(f" Tool {resource_name} already exists; performing update instead of create")
                        # Call update_discovery_tool instead
                        update_result = self.update_discovery_tool(existing_id, tool_definition, deploy_location)
                        return update_result
            except Exception as check_err:
                # Exception means resource doesn't exist, continue with PUT
                print(f"DEBUG: Error checking tool existence (will create): {check_err}")
            
            # Resource doesn't exist, proceed with PUT create
            
            # Use native REST API call
            result = azure_rest_call(
                method='PUT',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id,
                body=body
            )
            
            # Return result without assuming provisioning state
            # The caller should verify the actual provisioning state using Azure Resource Manager API
            return {
                "success": True,
                "resource_name": resource_name,
                "tool_id": f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/tools/{resource_name}",
                "tool_name": resource_name,
                "result": result
            }
        except Exception as e:
            print(f" Error creating Discovery tool: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_name": resource_name
            }
    
    def create_or_update_discovery_tool(self, tool_name: str, tool_definition: Dict[str, Any], location: Optional[str] = None) -> Dict[str, Any]:
        """Create a new Discovery tool or update if it already exists
        
        Args:
            tool_name: Name for the tool resource (from tool definition)
            tool_definition: The complete tool definition dictionary
            location: Azure region (optional, defaults to instance location)
            
        Returns:
            Dictionary with success status, resource information, and action taken
        """
        # Use provided location or default to instance location
        deploy_location = location or self.location
        
        # Sanitize tool name to be Azure-compatible
        sanitized_name = tool_name.replace('_', '-').replace(' ', '-')
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        
        # Ensure name meets Azure requirements
        if len(sanitized_name) > 24:
            sanitized_name = sanitized_name[:24]
        if len(sanitized_name) < 3:
            sanitized_name = (sanitized_name + "tool")[:3]
        
        resource_name = sanitized_name
        
        # Check if tool already exists
        existing_resource_id = self.check_tool_exists(resource_name)
        
        if existing_resource_id:
            print(f" Tool '{resource_name}' already exists, updating...")
            result = self.update_discovery_tool(existing_resource_id, tool_definition, deploy_location)
            if result['success']:
                result['action'] = 'updated'
                result['resource_name'] = resource_name
                result['tool_name'] = resource_name
                result['tool_id'] = existing_resource_id
            return result
        else:
            print(f" Creating new tool '{resource_name}'...")
            result = self.create_discovery_tool(tool_name, tool_definition, deploy_location, preserve_yaml_name=True)
            if result['success']:
                result['action'] = 'created'
            return result
    
    def create_or_update_discovery_agent(self, agent_name: str, agent_definition: Dict[str, Any], 
                                       tool_id: str, location: Optional[str] = None, model_name: Optional[str] = None) -> Dict[str, Any]:
        """Create a new Discovery agent or update if it already exists
        
        Args:
            agent_name: Name for the agent resource (from agent definition)
            agent_definition: The complete agent definition dictionary
            tool_id: The resource ID of the associated tool
            location: Azure region (optional, defaults to instance location)
            model_name: The model to use for the agent
            
        Returns:
            Dictionary with success status, resource information, and action taken
        """
        # Use provided location or default to instance location
        deploy_location = location or self.location
        
        # Sanitize agent name to be Azure-compatible
        sanitized_name = agent_name.replace('_', '-').replace(' ', '-')
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        
        # Ensure name meets Azure requirements
        if len(sanitized_name) > 24:
            sanitized_name = sanitized_name[:24]
        if len(sanitized_name) < 3:
            sanitized_name = (sanitized_name + "agent")[:3]
        
        resource_name = sanitized_name
        
        # Check if agent already exists
        existing_resource_id = self.check_agent_exists(resource_name)
        
        if existing_resource_id:
            print(f" Agent '{resource_name}' already exists, updating...")
            result = self.update_discovery_agent(existing_resource_id, agent_definition, tool_id, deploy_location, model_name)
            if result['success']:
                result['action'] = 'updated'
                result['resource_name'] = resource_name
                result['agent_name'] = resource_name
                result['agent_id'] = existing_resource_id
            return result
        else:
            print(f" Creating new agent '{resource_name}'...")
            result = self.create_discovery_agent(agent_name, agent_definition, tool_id, deploy_location, model_name, preserve_yaml_name=True)
            if result['success']:
                result['action'] = 'created'
            return result

    def create_discovery_agent(self, agent_name: str, agent_definition: Dict[str, Any], 
                             tool_id: str, location: Optional[str] = None, model_name: Optional[str] = None, 
                             generate_unique_name: bool = False,
                             preserve_yaml_name: bool = True) -> Dict[str, Any]:
        """Create a Discovery agent using REST API
        
        Args:
            agent_name: Name for the agent resource
            agent_definition: The complete agent definition dictionary
            tool_id: The resource ID of the associated tool
            location: Azure region (optional, defaults to instance location)
            model_name: The model to use for the agent
            generate_unique_name: Whether to generate a unique name (True for Entry Agent components, False for tool agents)
        """
        
        # Use provided location or default to instance location
        deploy_location = location or self.location
        
        # Sanitize the agent name to be Azure-compatible
        # Pattern: ^[a-zA-Z0-9-]{3,24}$ (letters, numbers, hyphens only, 3-24 chars)
        # Validate name according to stricter publisher rules before any mutation
        is_valid, err = self._is_valid_agent_name(agent_name)
        if not is_valid:
            return {
                "success": False,
                "error": f"Agent name validation failed: {err}",
                "resource_name": agent_name
            }

        sanitized_name = agent_name.replace('_', '-').replace(' ', '-')
        # Remove any invalid characters (keep only letters, numbers, hyphens)
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        
        if generate_unique_name:
            # Generate unique resource name for Entry Agent components
            # Ensure it doesn't exceed length limit when combined with UUID
            max_base_length = 24 - 9  # 24 total - 8 UUID chars - 1 hyphen = 15
            if len(sanitized_name) > max_base_length:
                sanitized_name = sanitized_name[:max_base_length]
            resource_name = f"{sanitized_name}-{str(uuid.uuid4())[:8]}"
        else:
            # For tool agents, prefer the YAML name as source of truth (preserve naming)
            # If preserve_yaml_name is True we will avoid adding any unique suffixes.
            # Still enforce Azure naming constraints (allowed chars and max length).
            if preserve_yaml_name:
                if len(sanitized_name) > 24:
                    # Trim to max allowed length; keep the YAML root of the name
                    sanitized_name = sanitized_name[:24]
                # Ensure minimum length of 3 by padding if needed
                if len(sanitized_name) < 3:
                    sanitized_name = (sanitized_name + "xxx")[:3]
                resource_name = sanitized_name
            else:
                # If caller explicitly requests a non-preserved name, fall back to safe unique naming
                if len(sanitized_name) > 24:
                    sanitized_name = sanitized_name[:24]
                if len(sanitized_name) < 3:
                    sanitized_name = (sanitized_name + "xxx")[:3]
                resource_name = sanitized_name
        
        # Build REST API URL
        url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
               f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
               f"agents/{resource_name}?api-version={self.api_version}")
        
        # Resolve model name: prefer explicit param, else YAML agent.model, else omit
        resolved_model = model_name
        if not resolved_model:
            try:
                resolved_model = (agent_definition or {}).get('agent', {}).get('model')
            except Exception:
                resolved_model = None

        # Build request body for agent
        # Ensure required top-level fields are present in definitionContent for agents
        enhanced_agent_definition = {
            "Name": agent_definition.get("name", resource_name),
            "Description": agent_definition.get("description", "Agent definition"),
            "Version": agent_definition.get("version", "1.0.0"),
            "Category": agent_definition.get("category", "General"),
            **agent_definition  # Include all original fields
        }
        
        properties: Dict[str, Any] = {
            "definitionContent": enhanced_agent_definition,
            "version": "1.0"
        }
        if resolved_model:
            properties["modelName"] = resolved_model

        # Wire the tool binding on the agent (authoritative place)
        if tool_id:
            try:
                tool_name = tool_id.split('/')[-1] or "tool"
            except Exception:
                tool_name = "tool"
            properties["tools"] = [
                {
                    "toolId": tool_id,
                    "name": tool_name
                }
            ]

        body = {
            "location": deploy_location,
            "properties": properties
        }
        
        print(f" Creating Discovery agent: {resource_name}")
        try:
            # Before creating, check if resource already exists using REST API
            check_url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
                        f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
                        f"agents/{resource_name}?api-version={self.api_version}")
            
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for create_discovery_agent; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            try:
                check_response = azure_rest_call(
                    method='GET',
                    url=check_url,
                    subscription_id=self.subscription_id,
                    tenant_id=tenant_id
                )
                if check_response.get('success'):
                    # Resource exists - perform PATCH update via update_discovery_agent
                    existing_id = f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/agents/{resource_name}"
                    print(f" Agent {resource_name} already exists; performing update instead of create")
                    update_result = self.update_discovery_agent(existing_id, agent_definition, tool_id, location, model_name)
                    return update_result
                else:
                    print(f" Agent {resource_name} does not exist (status: {check_response.get('status_code')}), will create new agent")
            except Exception as check_error:
                # 404 means resource doesn't exist, proceed with create
                error_str = str(check_error).lower()
                if '404' not in error_str and 'not found' not in error_str:
                    # Some other error occurred, but proceed with create attempt anyway
                    pass

            # Use native REST API call (tenant already retrieved above)
            result = azure_rest_call(
                method='PUT',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id,
                body=body
            )
            
            # Return result without assuming provisioning state
            # The caller should verify the actual provisioning state using Azure Resource Manager API
            return {
                "success": True,
                "resource_name": resource_name,
                "agent_id": f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/agents/{resource_name}",
                "agent_name": resource_name,
                "result": result
            }
        except Exception as e:
            print(f" Error creating Discovery agent: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_name": resource_name
            }
    
    def check_existing_tools(self) -> list:
        """Check for existing Discovery tools using REST API"""
        try:
            # Build REST API URL to list tools
            url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
                   f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
                   f"tools?api-version={self.api_version}")
            
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for check_existing_tools; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Call REST API
            response = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id
            )
            
            # Extract tool names from response
            # azure_rest_call returns {'success': bool, 'data': {...}}
            if response and response.get('success') and response.get('data'):
                data = response['data']
                if 'value' in data:
                    return [tool.get('name', '') for tool in data['value'] if tool.get('name')]
            return []
            
        except Exception as e:
            print(f"Warning: Could not check existing tools: {e}")
            return []

    def check_tool_exists(self, tool_name: str) -> Optional[str]:
        """Check if a tool with the given name already exists using REST API
        
        Args:
            tool_name: The tool name to check
            
        Returns:
            The resource ID if the tool exists, None otherwise
        """
        try:
            # Build REST API URL to get specific tool
            url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
                   f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
                   f"tools/{tool_name}?api-version={self.api_version}")
            
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for check_tool_exists; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Try to get the resource
            response = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id
            )
            
            # Return the resource ID if found
            # azure_rest_call returns {'success': bool, 'data': {...}}
            if response and response.get('success') and response.get('data'):
                data = response['data']
                if 'id' in data:
                    return data['id']
            return None
            
        except Exception as e:
            # 404 means resource doesn't exist
            error_str = str(e).lower()
            if '404' in error_str or 'not found' in error_str:
                return None
            print(f"Warning: Could not check if tool exists: {e}")
            return None
    def check_agent_exists(self, agent_name: str) -> Optional[str]:
        """Check if an agent with the given name already exists using REST API
        
        Args:
            agent_name: The agent name to check
            
        Returns:
            The resource ID if the agent exists, None otherwise
        """
        try:
            # Build REST API URL to get specific agent
            url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
                   f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
                   f"agents/{agent_name}?api-version={self.api_version}")
            
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for deploy_kb_agent; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Try to get the resource
            response = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id
            )
            
            # Return the resource ID if found
            # azure_rest_call returns {'success': bool, 'data': {...}}
            if response and response.get('success') and response.get('data'):
                data = response['data']
                if 'id' in data:
                    return data['id']
            return None
            
        except Exception as e:
            # 404 means resource doesn't exist
            error_str = str(e).lower()
            if '404' in error_str or 'not found' in error_str:
                return None
            print(f"Warning: Could not check if agent exists: {e}")
            return None
            return None

    def update_discovery_tool(self, resource_id: str, tool_definition: Dict[str, Any], location: Optional[str] = None) -> Dict[str, Any]:
        """Update an existing Discovery tool using PATCH method
        
        Args:
            resource_id: Full resource ID of the existing tool to update
            tool_definition: The updated tool definition dictionary  
            location: Azure region (optional, defaults to instance location)
        """
        
        # Use provided location or default to instance location
        deploy_location = location or self.location
        
        # Extract resource name from resource_id
        # resource_id format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Discovery/tools/{name}
        resource_name = resource_id.split('/')[-1]
        
        # Build REST API URL for PATCH update
        url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
               f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
               f"tools/{resource_name}?api-version={self.api_version}")
        
        # Build request body for tool update (exclude location for PATCH)
        # Ensure required top-level fields are present in definitionContent
        enhanced_definition = {
            "Name": tool_definition.get("name", resource_name),
            "Description": tool_definition.get("description", "Tool definition"),
            "Version": tool_definition.get("version", "1.0.0"),
            "Category": tool_definition.get("category", "General"),
            **tool_definition  # Include all original fields
        }
        
        # Extract environment variables from tool definition if they exist
        env_vars = {}
        if 'properties' in tool_definition and 'environmentVariables' in tool_definition['properties']:
            env_vars = tool_definition['properties']['environmentVariables']
            print(f"DEBUG: Extracted environment variables for update: {env_vars}")
        else:
            print("DEBUG: No environment variables found in tool definition for update")
        
        body = {
            "properties": {
                "definitionContent": enhanced_definition,
                "version": "1.0.0",
                "environmentVariables": env_vars
            }
        }
        
        print(f" Updating Discovery tool: {resource_name}")
        
        # Debug: Log the request body being sent
        import json
        print(f"DEBUG: Tool update (PATCH) request body:")
        print(json.dumps(body, indent=2))
        
        try:
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for update_discovery_tool; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Use native REST API call
            result = azure_rest_call(
                method='PATCH',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id,
                body=body
            )
            
            # Debug: Log the API response
            print(f"DEBUG: Tool update (PATCH) API response:")
            print(json.dumps(result, indent=2) if result else "No response data")
            
            # Format response for web server
            return {
                "success": True,
                "resource_name": resource_name,
                "tool_id": resource_id,
                "tool_name": resource_name,
                "provisioning_state": "Succeeded",
                "result": result
            }
        except Exception as e:
            print(f" Error updating Discovery tool: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_name": resource_name
            }

    def update_discovery_agent(self, resource_id: str, agent_definition: Dict[str, Any], 
                             tool_id: str, location: Optional[str] = None, model_name: Optional[str] = None) -> Dict[str, Any]:
        """Update an existing Discovery agent using PATCH method
        
        Args:
            resource_id: Full resource ID of the existing agent to update
            agent_definition: The updated agent definition dictionary
            tool_id: The tool resource ID this agent should reference
            location: Azure region (optional, defaults to instance location)
            model_name: AI model name for the agent
        """
        
        # Use provided location or default to instance location
        deploy_location = location or self.location
        
        # Extract resource name from resource_id
        resource_name = resource_id.split('/')[-1]
        
        # Build REST API URL for PATCH update
        url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
               f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
               f"agents/{resource_name}?api-version={self.api_version}")
        
        # Resolve model for update: prefer explicit param, else YAML agent.model, else omit
        resolved_model = model_name
        if not resolved_model:
            try:
                resolved_model = (agent_definition or {}).get('agent', {}).get('model')
            except Exception:
                resolved_model = None

        # Build request body for agent update (minimal payload for PATCH)
        properties: Dict[str, Any] = {
            "definitionContent": agent_definition,
            "version": "1.0"
        }
        if resolved_model:
            properties["modelName"] = resolved_model

        # Ensure the tool binding exists/updates on PATCH as well
        if tool_id:
            try:
                tool_name = tool_id.split('/')[-1] or "tool"
            except Exception:
                tool_name = "tool"
            properties["tools"] = [
                {
                    "toolId": tool_id,
                    "name": tool_name
                }
            ]

        body = {
            "properties": properties
        }
        
        print(f" Updating Discovery agent: {resource_name}")
        try:
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for update_discovery_agent; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Use native REST API call
            result = azure_rest_call(
                method='PATCH',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id,
                body=body
            )
            
            # Return result without assuming provisioning state
            # The caller should verify the actual provisioning state using Azure Resource Manager API
            return {
                "success": True,
                "resource_name": resource_name,
                "agent_id": resource_id,
                "agent_name": resource_name,
                "result": result
            }
        except Exception as e:
            print(f" Error updating Discovery agent: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_name": resource_name
            }

    def create_discovery_workflow(self, workflow_name: str, workflow_definition: Dict[str, Any], 
                                  location: Optional[str] = None, version: str = "2025-05-15-preview") -> Dict[str, Any]:
        """Create a Discovery workflow resource using REST API
        
        Args:
            workflow_name: Name for the workflow resource
            workflow_definition: The workflow definition JSON (no agent wrapper)
            location: Azure region (optional)
            version: Definition content version string
        """
        deploy_location = location or self.location
        # Validate workflow name per publisher rules
        is_valid, err = self._is_valid_workflow_name(workflow_name)
        if not is_valid:
            return {
                "success": False,
                "error": f"Workflow name validation failed: {err}",
                "resource_name": workflow_name
            }

        # If valid, sanitize minimally (convert underscores/spaces to dashes)
        sanitized_name = workflow_name.replace('_', '-').replace(' ', '-')
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')

        url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
               f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
               f"workflows/{sanitized_name}?api-version={self.api_version}")

        # Align definitionContent.name with sanitized resource name to satisfy API validation
        workflow_definition = dict(workflow_definition or {})
        try:
            workflow_definition['name'] = sanitized_name
        except Exception:
            pass

        body = {
            "location": deploy_location,
            "properties": {
                "definitionContent": workflow_definition,
                "version": version
            }
        }

        print(f" Creating Discovery workflow: {sanitized_name}")
        try:
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for create_discovery_workflow; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Use native REST API call
            result = azure_rest_call(
                method='PUT',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id,
                body=body
            )
            
            # Check if the REST API call actually succeeded
            if not result or not result.get('success'):
                error_msg = (result or {}).get('error', 'Unknown REST API error')
                print(f" REST API error creating workflow: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "resource_name": sanitized_name,
                    "result": result
                }
            
            return {
                "success": True,
                "resource_name": sanitized_name,
                "workflow_id": f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/workflows/{sanitized_name}",
                "workflow_name": sanitized_name,
                "result": result
            }
        except Exception as e:
            print(f" Error creating Discovery workflow: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_name": sanitized_name
            }

    def update_discovery_workflow(self, workflow_name: str, workflow_definition: Dict[str, Any], 
                                  version: str = "2025-05-15-preview") -> Dict[str, Any]:
        """Update an existing Discovery workflow resource using REST API (PATCH).
        Args:
            workflow_name: Existing workflow resource name to update
            workflow_definition: The workflow definition JSON (no agent wrapper)
            version: Definition content version string
        """
        # Sanitize provided name minimally to ensure it's URL-safe; do NOT alter identity beyond allowed chars
        sanitized_name = (workflow_name or "").replace('_', '-').replace(' ', '-')
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        if len(sanitized_name) < 3:
            # Keep minimal padding (server still identifies same resource)
            sanitized_name = (sanitized_name + "xxx")[:3]

        url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
               f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
               f"workflows/{sanitized_name}?api-version={self.api_version}")

        # Align definitionContent.name with sanitized resource name for API validation
        wf_def = dict(workflow_definition or {})
        try:
            wf_def['name'] = sanitized_name
        except Exception:
            pass

        body = {
            "properties": {
                "definitionContent": wf_def,
                "version": version
            }
        }

        print(f" Updating Discovery workflow: {sanitized_name}")
        try:
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for update_discovery_workflow; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Use native REST API call
            result = azure_rest_call(
                method='PATCH',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id,
                body=body
            )
            
            # Check if the REST API call actually succeeded
            if not result or not result.get('success'):
                error_msg = (result or {}).get('error', 'Unknown REST API error')
                print(f" REST API error updating workflow: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "resource_name": sanitized_name,
                    "result": result
                }
            
            return {
                "success": True,
                "resource_name": sanitized_name,
                "workflow_id": f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/workflows/{sanitized_name}",
                "workflow_name": sanitized_name,
                "result": result
            }
        except Exception as e:
            print(f" Error updating Discovery workflow: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_name": sanitized_name
            }
    
    def check_workflow_exists(self, workflow_name: str) -> Optional[str]:
        """Check if a workflow with the given name already exists using REST API.

        Args:
            workflow_name: The workflow name to check

        Returns:
            The resource ID if the workflow exists, None otherwise
        """
        try:
            sanitized_name = (workflow_name or "").replace('_', '-').replace(' ', '-')
            sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')

            url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
                   f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
                   f"workflows/{sanitized_name}?api-version={self.api_version}")

            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for check_workflow_exists")
            tenant_id = self.tenant_id

            response = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id
            )

            if response and response.get('success') and response.get('data'):
                data = response['data']
                if 'id' in data:
                    return data['id']
            return None

        except Exception as e:
            error_str = str(e).lower()
            if '404' in error_str or 'not found' in error_str:
                return None
            print(f"Warning: Could not check if workflow exists: {e}")
            return None

    def create_or_update_discovery_workflow(self, workflow_name: str, workflow_definition: Dict[str, Any],
                                            location: Optional[str] = None,
                                            version: str = "2025-05-15-preview") -> Dict[str, Any]:
        """Create a new Discovery workflow or update if it already exists.

        Mirrors the create_or_update pattern used by tools and agents so that
        callers don't need to manually decide between create and update modes.

        Args:
            workflow_name: Name for the workflow resource
            workflow_definition: The workflow definition JSON (no agent wrapper)
            location: Azure region (optional)
            version: Definition content version string

        Returns:
            Dictionary with success status, resource information, and action taken
        """
        # Sanitize workflow name for the existence check
        sanitized_name = (workflow_name or "").replace('_', '-').replace(' ', '-')
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')

        # Check if workflow already exists
        existing_resource_id = self.check_workflow_exists(sanitized_name)

        if existing_resource_id:
            print(f" Workflow '{sanitized_name}' already exists, updating...")
            result = self.update_discovery_workflow(
                workflow_name=sanitized_name,
                workflow_definition=workflow_definition,
                version=version
            )
            if result.get('success'):
                result['action'] = 'updated'
            return result
        else:
            print(f" Creating new workflow '{sanitized_name}'...")
            result = self.create_discovery_workflow(
                workflow_name=workflow_name,
                workflow_definition=workflow_definition,
                location=location,
                version=version
            )
            if result.get('success'):
                result['action'] = 'created'
            return result

    def deploy_kb_agent(self, agent_name: str, agent_definition: Dict[str, Any], 
                       knowledge_bases: Optional[list] = None, location: Optional[str] = None, force_update: bool = False) -> Dict[str, Any]:
        """Deploy a Knowledge Base Agent using REST API
        
        Args:
            agent_name: Name for the agent resource
            agent_definition: The complete agent definition dictionary
            location: Azure region (optional, defaults to instance location)
            force_update: Whether to update if agent already exists
        """
        
        # Use provided location or default to instance location
        deploy_location = location or self.location
        
        # Extract the agent name from the agent definition (this is the authoritative name)
        # Azure requires the resource name in the URL to match definitionContent.agent.name
        definition_agent_name = agent_definition.get('agent', {}).get('name')
        if not definition_agent_name:
            return {
                "success": False,
                "error": "Agent definition must contain 'agent.name' field",
                "resource_name": agent_name
            }
        
        # Use the definition name as the authoritative name
        agent_name_to_use = definition_agent_name
        
        # Check for reserved keywords that Azure Discovery blocks
        # Note: These keywords are blocked by Azure's internal validation (discovered through testing)
        # Agents with these substrings in their names will fail with "ResourceCreationValidateFailed"
        reserved_keywords = ['filewriter']
        agent_name_lower = agent_name_to_use.lower()
        for keyword in reserved_keywords:
            if keyword in agent_name_lower:
                return {
                    "success": False,
                    "error": f"Agent name '{agent_name_to_use}' contains reserved keyword '{keyword}'. This name is blocked by Azure Discovery. Please use an alternative like 'file-writer', 'document-writer', or 'content-saver'.",
                    "resource_name": agent_name_to_use
                }
        
        # Validate and sanitize the agent name
        is_valid, err = self._is_valid_agent_name(agent_name_to_use)
        if not is_valid:
            return {
                "success": False,
                "error": f"Agent name validation failed: {err}",
                "resource_name": agent_name_to_use
            }

        sanitized_name = agent_name_to_use.replace('_', '-').replace(' ', '-')
        # Remove any invalid characters (keep only letters, numbers, hyphens)
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        
        # Ensure proper length constraints
        if len(sanitized_name) > 24:
            sanitized_name = sanitized_name[:24]
        if len(sanitized_name) < 3:
            sanitized_name = (sanitized_name + "xxx")[:3]
        
        # Build REST API URL
        url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
               f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
               f"agents/{sanitized_name}?api-version={self.api_version}")
        
        # Extract model from agent definition if available
        resolved_model = None
        try:
            # Extract model from YAML agent structure
            resolved_model = agent_definition.get('agent', {}).get('model')
        except Exception:
            resolved_model = None

        # Ensure model is provided (required by Azure API)
        if not resolved_model:
            return {
                "success": False,
                "error": "Model name is required for Knowledge Base agents. Please specify 'model' in the agent YAML.",
                "resource_name": sanitized_name
            }

        # Build request body for Knowledge Base agent
        # The definitionContent should be the YAML config converted to JSON
        properties: Dict[str, Any] = {
            "definitionContent": agent_definition,  # This is the YAML content as JSON
            "version": "1.0",
            "modelName": resolved_model
        }
        
        # Use provided knowledge bases from frontend instead of trying to extract from agent definition
        try:
            provided_knowledge_bases = knowledge_bases or []
            
            if provided_knowledge_bases:
                # Use knowledge bases as provided from frontend
                azure_kb_format = []
                for kb in provided_knowledge_bases:
                    if isinstance(kb, dict):
                        # Normalize knowledgeBaseId to include bookshelf segment if missing.
                        kb_id = (kb.get('knowledgeBaseId') or '').strip()
                        kb_name = (kb.get('name') or '').strip()
                        kb_bookshelf = (kb.get('bookshelfName') or '').strip()
                        kb_version = (kb.get('version') or '')

                        # If the id already contains the bookshelf segment, accept it.
                        if kb_id and '/bookshelves/' in kb_id:
                            normalized_id = kb_id
                        else:
                            # If id starts with '/knowledgeBases/' and we have a bookshelf, prepend it.
                            if kb_id.startswith('/knowledgeBases/') and kb_bookshelf:
                                normalized_id = f"/bookshelves/{kb_bookshelf}{kb_id}"
                            elif not kb_id:
                                # Construct using provided name and bookshelf if possible
                                if kb_name and kb_bookshelf:
                                    version_segment = f"/versions/{kb_version}" if kb_version else '/versions/1'
                                    normalized_id = f"/bookshelves/{kb_bookshelf}/knowledgeBases/{kb_name}{version_segment}"
                                else:
                                    # Leave as empty or original value and log a warning
                                    normalized_id = kb_id
                                    print(f" Unable to normalize knowledgeBaseId for KB entry: name='{kb_name}', bookshelf='{kb_bookshelf}', id='{kb_id}'")
                            else:
                                # Fallback: use original kb_id (may be a plain name or unexpected format)
                                normalized_id = kb_id

                        azure_kb_format.append({
                            "knowledgeBaseId": normalized_id,
                            "name": kb_name
                        })
                properties["knowledgeBases"] = azure_kb_format
            else:
                properties["knowledgeBases"] = []
        except Exception as e:
            print(f" Error processing knowledge bases: {e}")
            properties["knowledgeBases"] = []

        # KB agents don't have tools, but the definitionContent contains the full agent definition
        
        print(f" Deploying Knowledge Base Agent: {sanitized_name}")
        
        try:
            # Check if resource already exists using REST API
            check_url = (f"https://management.azure.com/subscriptions/{self.subscription_id}/"
                        f"resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/"
                        f"agents/{sanitized_name}?api-version={self.api_version}")
            
            # Require explicit tenant_id; do not auto-detect
            if not self.tenant_id:
                raise ValueError("Explicit tenant_id required for deploy_kb_agent; configure it when constructing DiscoveryRestPublisher")
            tenant_id = self.tenant_id
            
            # Try to get the existing resource
            try:
                check_response = azure_rest_call(
                    method='GET',
                    url=check_url,
                    subscription_id=self.subscription_id,
                    tenant_id=tenant_id
                )
                # azure_rest_call returns a dict with 'success' flag
                if isinstance(check_response, dict) and check_response.get('success'):
                    resource_exists = True
                else:
                    # If it failed with an explicit 404, treat as not existing
                    status = (check_response or {}).get('status_code')
                    err = (check_response or {}).get('error', '')
                    if status == 404 or (isinstance(err, str) and 'not found' in err.lower()):
                        resource_exists = False
                    else:
                        # Other failure - raise to surface the error
                        raise RuntimeError(f"Failed checking resource existence: {err}")
            except Exception as check_error:
                # Propagate unexpected errors
                raise
            
            if resource_exists and not force_update:
                return {
                    "success": False,
                    "error": f"Knowledge Base Agent '{sanitized_name}' already exists. Use force_update=True to overwrite.",
                    "resource_name": sanitized_name,
                    "duplicate": True
                }
            
            # Create or update the resource
            method = "PATCH" if resource_exists else "PUT"
            action = "Updating" if resource_exists else "Creating"
            
            # Include location only for new resource creation (PUT), not for updates (PATCH)
            body: Dict[str, Any] = {
                "properties": properties
            }
            if not resource_exists:
                body["location"] = deploy_location
            
            print(f" {action} Knowledge Base Agent: {sanitized_name}")
            
            # Use native REST API call instead of az command
            result = azure_rest_call(
                method=method,
                url=url,
                subscription_id=self.subscription_id,
                tenant_id=tenant_id,
                body=body
            )
            
            # Return the result and reflect actual success from the REST call
            overall_success = False
            if isinstance(result, dict) and result.get('success'):
                overall_success = True

            return {
                "success": overall_success,
                "resource_name": sanitized_name,
                "resource_id": f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/Microsoft.Discovery/agents/{sanitized_name}",
                "agent_name": sanitized_name,
                "action": action.lower(),
                "result": result
            }
                
        except Exception as e:
            print(f" Error deploying Knowledge Base Agent: {e}")
            return {
                "success": False,
                "error": str(e),
                "resource_name": sanitized_name
            }

