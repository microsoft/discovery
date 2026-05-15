"""
Microsoft Discovery Publisher

Core module for publishing agents and tools to Microsoft Discovery platform.
Includes tool existence checking, optimization logic, and deployment orchestration.
"""

import json
import subprocess
import tempfile
import os
import re
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from discovery_config import DiscoveryConfigParser, AgentCatalogParser
import logging
import io
import contextlib
import base64
import requests

# Logger for this module
_LOG = logging.getLogger(__name__)

# Check if debug mode is enabled via environment variable
_DEBUG_DISCOVERY = os.getenv('DEBUG_DISCOVERY', 'false').lower() in ('true', '1', 'yes')

def _debug_print(msg: str):
    """Print debug message to logger if debug mode is enabled, otherwise suppress."""
    if _DEBUG_DISCOVERY:
        _LOG.debug(msg)

# Quiet token acquisition helper (local copy to avoid circular imports)
def _get_token_default_credential(scope: str, traces: list | None = None, purpose: str = '') -> Optional[str]:
    # Delegate to centralized helper to keep behavior consistent across modules
    try:
        from azure_auth_helpers import get_token_default_credential
        return get_token_default_credential(scope, traces, purpose=purpose)
    except Exception:
        if isinstance(traces, list):
            traces.append('❌ azure_auth_helpers unavailable')
        return None


def _arm_list_resources_via_rest(subscription_id: str, resource_group: str, resource_type: str, api_version: str = '2025-07-01-preview', traces: list | None = None) -> Tuple[bool, Optional[list], Optional[str]]:
    """List ARM resources via REST API (returns (success, items, error_message)).

    This is used as a fallback when Azure CLI is not available but DefaultAzureCredential is.
    """
    scope = 'https://management.azure.com/.default'
    token = _get_token_default_credential(scope, traces, purpose='arm-list')
    if not token:
        return False, None, 'auth_unavailable'

    url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/{resource_type}?api-version={api_version}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'User-Agent': 'Microsoft-Discovery-AgentWorkbench/1.0',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get('value') or []
            return True, items, None
        else:
            return False, None, f'ARM API returned {resp.status_code}: {resp.text[:500]}'
    except Exception as e:
        return False, None, str(e)


def _arm_get_resource_via_rest(resource_id: str, api_version: str = '2025-07-01-preview', traces: list | None = None) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Get a single ARM resource via REST API (returns (success, resource_data, error_message)).

    This is used as a fallback when Azure CLI is not available but DefaultAzureCredential is.
    
    Args:
        resource_id: Full ARM resource ID (e.g., /subscriptions/.../resourceGroups/.../providers/Microsoft.Discovery/agents/agentName)
        api_version: API version to use
        traces: Optional list to append trace messages
        
    Returns:
        Tuple of (success, resource_data, error_message)
    """
    scope = 'https://management.azure.com/.default'
    token = _get_token_default_credential(scope, traces, purpose='arm-get')
    if not token:
        return False, None, 'auth_unavailable'

    url = f"https://management.azure.com{resource_id}?api-version={api_version}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'User-Agent': 'Microsoft-Discovery-AgentWorkbench/1.0',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return True, data, None
        elif resp.status_code == 404:
            return False, None, 'resource_not_found'
        else:
            return False, None, f'ARM API returned {resp.status_code}: {resp.text[:500]}'
    except Exception as e:
        return False, None, str(e)


class AzureDiscoveryClient:
    """Client for interacting with Azure Discovery resources using REST API."""
    
    # Class-level cache for agents listing with TTL (Time To Live)
    _agents_cache = {}
    _agents_cache_ttl = 30  # Cache for 30 seconds during validation operations
    
    def __init__(self):
        # All operations now use REST API via azure_rest_call()
        pass

    @classmethod
    def clear_agents_cache(cls) -> None:
        """Clear the cached agents listings"""
        cls._agents_cache.clear()
        _debug_print(" Agents cache cleared")

    @classmethod
    def clear_all_caches(cls) -> None:
        """Clear all caches (agents listings)"""
        cls.clear_agents_cache()
        _debug_print(" All caches cleared")
    
    def check_azure_auth(self) -> Dict[str, Any]:
        """Check if user is authenticated to Azure using REST API.
        
        Returns dict with authentication status and subscription information.
        """
        try:
            from azure_auth_helpers import get_token_default_credential
            import requests
            
            # Try to get token for Azure Management API
            token = get_token_default_credential("https://management.azure.com/.default")
            
            # Test token by listing subscriptions
            url = "https://management.azure.com/subscriptions?api-version=2020-01-01"
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "Microsoft-Discovery-AgentWorkbench/1.0",
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                subscriptions = response.json().get('value', [])
                if subscriptions:
                    first_sub = subscriptions[0]
                    return {
                        'authenticated': True,
                        'subscription_id': first_sub.get('subscriptionId'),
                        'subscription_name': first_sub.get('displayName'),
                        'tenant_id': first_sub.get('tenantId'),
                        'user': 'Azure SDK',
                        'method': 'rest_api',
                        'total_subscriptions': len(subscriptions)
                    }
                else:
                    return {
                        'authenticated': True,
                        'method': 'rest_api',
                        'message': 'Authenticated but no subscriptions accessible'
                    }
            else:
                # REST API failed
                _debug_print(f"⚠️ REST API auth check failed ({response.status_code})")
                return {
                    'authenticated': False,
                    'error': f'Authentication check failed: HTTP {response.status_code}'
                }
        
        except ImportError:
            _debug_print("⚠️ azure_auth_helpers not available")
            return {
                'authenticated': False,
                'error': 'Azure authentication modules not available'
            }
        except Exception as e:
            _debug_print(f"⚠️ REST API auth check error: {str(e)}")
            return {
                'authenticated': False,
                'error': f'Authentication check failed: {str(e)}'
            }
    
    def _azure_rest_call(self, method: str, url: str, body: dict = None, timeout: int = 60) -> Dict[str, Any]:
        """Make authenticated REST API call to Azure using azure_auth_helpers.
        
        Args:
            method: HTTP method (GET, PUT, PATCH, POST, DELETE)
            url: Full Azure Management API URL
            body: Request body as dictionary
            timeout: Request timeout in seconds
            
        Returns:
            Dict compatible with old _run_azure_command format:
            - success (bool)
            - stdout (str): JSON response as string (for compatibility)
            - stderr (str): Error message if failed
            - data (dict): Parsed response data
        """
        from azure_auth_helpers import azure_rest_call
        
        server_traces = []
        result = azure_rest_call(
            method=method,
            url=url,
            subscription_id=self.subscription_id if hasattr(self, 'subscription_id') else None,
            body=body,
            server_traces=server_traces,
            timeout=timeout
        )
        
        # Print traces
        for trace in server_traces:
            _debug_print(trace)
        
        # Convert to old format for compatibility
        if result['success']:
            return {
                'success': True,
                'stdout': json.dumps(result.get('data', {})) if result.get('data') else '',
                'stderr': '',
                'returncode': result.get('status_code', 200),
                'data': result.get('data')
            }
        else:
            return {
                'success': False,
                'stdout': '',
                'stderr': result.get('error', 'Unknown error'),
                'returncode': result.get('status_code', 1),
                'error': result.get('error')
            }
    
    def check_authentication(self) -> Dict[str, Any]:
        """Check Azure authentication status using REST API with tenant-aware authentication.
        
        Returns:
            Dict with 'authenticated', 'subscription_id', 'subscription_name', 'user', 'tenant_id'
        """
        # Try REST API with our centralized auth helper
        try:
            from azure_auth_helpers import get_token_default_credential
            import requests
            
            server_traces = []
            
            # Acquire OAuth token
            token = get_token_default_credential(
                'https://management.azure.com/.default',
                server_traces,
                purpose='check-authentication'
            )
            
            if not token:
                _debug_print("⚠️ Token acquisition failed, trying CLI fallback")
                # Fall through to CLI fallback below
                raise Exception("Token acquisition failed")
            
            # Get subscriptions list to verify authentication
            url = "https://management.azure.com/subscriptions"
            headers = {
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
                'User-Agent': 'Microsoft-Discovery-AgentWorkbench/1.0',
            }
            params = {
                'api-version': '2022-12-01'
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                subscriptions = data.get('value', [])
                
                if subscriptions:
                    # Return info from first subscription
                    first_sub = subscriptions[0]
                    return {
                        'authenticated': True,
                        'subscription_id': first_sub.get('subscriptionId'),
                        'subscription_name': first_sub.get('displayName'),
                        'tenant_id': first_sub.get('tenantId'),
                        'user': 'Azure SDK',
                        'method': 'rest_api',
                        'total_subscriptions': len(subscriptions)
                    }
                else:
                    return {
                        'authenticated': True,
                        'method': 'rest_api',
                        'message': 'Authenticated but no subscriptions accessible'
                    }
            else:
                # REST API failed
                _debug_print(f"⚠️ REST API auth check failed ({response.status_code})")
                return {
                    'authenticated': False,
                    'error': f'Authentication check failed: HTTP {response.status_code}'
                }
        
        except ImportError:
            _debug_print("⚠️ azure_auth_helpers not available")
            return {
                'authenticated': False,
                'error': 'Azure authentication modules not available'
            }
        except Exception as e:
            _debug_print(f"⚠️ REST API auth check error: {str(e)}")
            return {
                'authenticated': False,
                'error': f'Authentication check failed: {str(e)}'
            }
    
    def _list_tools_via_rest_api(self, subscription_id: str, resource_group: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """List Microsoft Discovery tools using REST API with tenant-aware authentication.
        
        Args:
            subscription_id: Azure subscription ID
            resource_group: Resource group name
            tenant_id: Specific tenant ID (optional, will auto-detect if not provided)
            
        Returns:
            Dict with 'success', 'tools' list, and optional 'error'
        """
        from azure_auth_helpers import azure_rest_call
        
        try:
            # Build REST API URL
            url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/tools?api-version=2025-07-01-preview"
            
            _debug_print(f"🔧 Fetching tools via REST API: {url}")
            
            server_traces = []
            result = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=subscription_id,
                tenant_id=tenant_id,
                server_traces=server_traces,
                timeout=30
            )
            
            # Print traces
            for trace in server_traces:
                _debug_print(trace)
            
            if result['success']:
                data = result.get('data', {})
                tools = data.get('value', [])
                _debug_print(f"✅ REST API returned {len(tools)} tools")
                return {
                    'success': True,
                    'tools': tools
                }
            else:
                error_msg = result.get('error', 'Unknown error')
                _debug_print(f"❌ {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'tools': []
                }
                
        except Exception as e:
            _debug_print(f"❌ REST API error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'tools': []
            }

    def list_discovery_tools(self, subscription_id: str, resource_group: str, acr_image: Optional[str] = None, tool_name: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """List Microsoft Discovery tools in a resource group.

        Options:
        - If `tool_name` is provided, perform an exact name match against the tool resource name.
        - Else if `acr_image` is provided, perform an exact ACR image string match against the tool's definitionContent.acrImage.
        """
        _debug_print(f"DEBUG: list_discovery_tools called with:")
        _debug_print(f"  subscription_id: {subscription_id}")
        _debug_print(f"  resource_group: {resource_group}")
        _debug_print(f"  acr_image: {acr_image}")
        _debug_print(f"  acr_image type: {type(acr_image)}")
        _debug_print(f"  tool_name param: {tool_name}")
        _debug_print(f"  tenant_id: {tenant_id}")
        
        # Try REST API first (primary method)
        rest_result = self._list_tools_via_rest_api(subscription_id, resource_group, tenant_id=tenant_id)
        
        if rest_result['success']:
            tools = rest_result['tools']
            _debug_print(f"DEBUG: REST API returned {len(tools) if tools else 0} tools")
        else:
            # REST API failed
            _debug_print(f"DEBUG: REST API failed: {rest_result.get('error')}")
            return {'exists': False, 'error': rest_result.get('error', 'Unknown error'), 'message': 'Failed to retrieve tools via REST API'}
        
        # Process tools
        if not tools:
            return {'exists': False, 'tools': [], 'message': 'No tools found in resource group'}
        
        # Log all tools for debugging
        _debug_print(f"DEBUG: Found tools:")
        for i, tool in enumerate(tools[:5]):  # Show first 5 tools
            if tool and isinstance(tool, dict):
                tname_debug = tool.get('name', 'Unknown')
                properties = tool.get('properties') or {}  # Handle None properties
                definition_content = properties.get('definitionContent', {}) if properties else {}
                tool_acr_image = definition_content.get('acrImage', 'N/A') if definition_content else 'N/A'
                _debug_print(f"  [{i}] {tname_debug} - ACR: {tool_acr_image}")
        
        # If `tool_name` provided, perform exact name matching
        if tool_name:
            matching_tools = []
            for tool in tools:
                if not tool or not isinstance(tool, dict):
                    continue
                try:
                    tname = tool.get('name', '')
                    if tname and tname.lower() == tool_name.lower():
                        properties = tool.get('properties') or {}
                        definition_content = properties.get('definitionContent') or {} if properties else {}
                        tool_acr_image = definition_content.get('acrImage', '') if definition_content else ''
                        matching_tools.append({
                            'tool': tool,
                            'match_type': 'exact',
                            'tool_name': tname,
                            'tool_acr_image': tool_acr_image
                        })
                except Exception:
                    continue

            if matching_tools:
                tools_info = []
                for match in matching_tools:
                    tool = match['tool']
                    properties = tool.get('properties') or {}
                    provisioning_state = properties.get('provisioningState', 'Unknown') if properties else 'Unknown'
                    location = tool.get('location', 'Unknown')
                    tools_info.append({
                        'name': match['tool_name'],
                        'acr_image': match['tool_acr_image'],
                        'match_type': match['match_type'],
                        'provisioning_state': provisioning_state,
                        'location': location,
                        'resource_id': tool.get('id', ''),
                        'tool_data': tool
                    })
                return {
                    'exists': True,
                    'total_matches': len(matching_tools),
                    'best_match': tools_info[0],
                    'all_tools': tools_info,
                    'message': f'Found {len(matching_tools)} matching tool(s) by name'
                }
            else:
                return {'exists': False, 'message': f'No tools found matching name: {tool_name}'}

        # If no ACR image provided, return all tools
        if not acr_image:
            valid_tools = [tool for tool in tools if tool and isinstance(tool, dict)]
            return {'exists': len(valid_tools) > 0, 'tools': valid_tools, 'message': f'Found {len(valid_tools)} tools'}
        
        # Filter by ACR image and tool name patterns
        input_acr_image = acr_image
        matching_tools = []

        # First check whether any tooling records actually have an ACR image set
        any_acr_present = False
        for tool in tools:
            if not tool or not isinstance(tool, dict):
                continue
            try:
                props = tool.get('properties') or {}
                defc = props.get('definitionContent') or {} if props else {}
                if defc.get('acrImage'):
                    any_acr_present = True
                    break
            except Exception:
                continue

        if not any_acr_present:
            # If no tools have an ACR value set, do not report a false positive match
            _debug_print("DEBUG: No discovery tools have definitionContent.acrImage set; cannot match by ACR image")
            return {
                'exists': False,
                'message': 'No discovery tools in the resource group have an ACR image set; please check by tool_name instead.'
            }

        # For exact-only matching, we compare the full ACR image strings
        _debug_print("DEBUG: Using exact ACR image matching only")

        for i, tool in enumerate(tools):
            if not tool or not isinstance(tool, dict):
                continue

            try:
                tname = tool.get('name', '')
                properties = tool.get('properties') or {}
                definition_content = properties.get('definitionContent') or {} if properties else {}
                tool_acr_image = definition_content.get('acrImage', '') if definition_content else ''

                # Only include exact ACR image matches
                exact_match = tool_acr_image == input_acr_image
                _debug_print(f"DEBUG: Tool {i} ({tname}): Tool ACR='{tool_acr_image}', Input ACR='{input_acr_image}', Exact match: {exact_match}")
                if exact_match:
                    matching_tools.append({
                        'tool': tool,
                        'match_type': 'exact',
                        'tool_name': tname,
                        'tool_acr_image': tool_acr_image
                    })

            except Exception as e:
                _debug_print(f"DEBUG: Error processing tool {i}: {e}")
                continue

        _debug_print(f"DEBUG: Found {len(matching_tools)} matching tools")

        if matching_tools:
            # Sort matches by preference: exact first
            match_priority = {'exact': 0}
            sorted_matches = sorted(matching_tools, key=lambda x: match_priority.get(x['match_type'], 999))

            # Prepare detailed information for all matches
            tools_info = []
            for match in sorted_matches:
                tool = match['tool']
                properties = tool.get('properties') or {}
                provisioning_state = properties.get('provisioningState', 'Unknown') if properties else 'Unknown'
                location = tool.get('location', 'Unknown')

                tools_info.append({
                    'name': match['tool_name'],
                    'acr_image': match['tool_acr_image'],
                    'match_type': match['match_type'],
                    'provisioning_state': provisioning_state,
                    'location': location,
                    'resource_id': tool.get('id', ''),
                    'tool_data': tool
                })

            return {
                'exists': True,
                'total_matches': len(matching_tools),
                'best_match': tools_info[0],
                'all_tools': tools_info,
                'message': f'Found {len(matching_tools)} matching tool(s) by ACR image'
            }
        else:
            return {
                'exists': False,
                'message': f'No tools found matching ACR image: {input_acr_image}'
            }
    
    # Note: Name normalization helpers were removed to keep discovery matching exact-only.
    
    def _list_agents_via_rest_api(self, subscription_id: str, resource_group: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """List agents using Azure Management REST API with tenant-aware authentication.
        
        Args:
            subscription_id: Azure subscription ID
            resource_group: Resource group name
            tenant_id: Specific tenant ID (optional, will auto-detect if not provided)
        
        Returns:
            Dict with 'success' boolean, 'agents' list if successful, 'error' if failed
        """
        from azure_auth_helpers import azure_rest_call
        
        try:
            # Build REST API URL
            api_version = '2025-07-01-preview'
            url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/agents?api-version={api_version}"
            
            _debug_print(f"DEBUG: Calling REST API: {url[:120]}...")
            
            server_traces = []
            result = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=subscription_id,
                tenant_id=tenant_id,
                server_traces=server_traces,
                timeout=30
            )
            
            # Print traces
            for trace in server_traces:
                _debug_print(trace)
            
            if result['success']:
                data = result.get('data', {})
                agents = data.get('value', [])
                _debug_print(f"DEBUG: ✅ REST API success - received {len(agents)} agents")
                return {
                    'success': True,
                    'agents': agents
                }
            else:
                error_msg = result.get('error', 'Unknown error')
                _debug_print(f"DEBUG: ❌ REST API failed: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except Exception as e:
            _debug_print(f"DEBUG: ❌ REST API call failed: {e}")
            return {
                'success': False,
                'error': f'REST API call failed: {str(e)}'
            }
    
    def list_discovery_agents(self, subscription_id: str, resource_group: str, agent_name_pattern: Optional[str] = None, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """List Microsoft Discovery agents in a resource group, optionally filtered by agent name pattern."""
        import time
        
        # Create cache key for this specific request
        cache_key = f"{subscription_id}|{resource_group}|{agent_name_pattern or '*'}"
        current_time = time.time()
        
        # Check if we have a valid cached result
        if cache_key in AzureDiscoveryClient._agents_cache:
            cached_entry = AzureDiscoveryClient._agents_cache[cache_key]
            cache_age = current_time - cached_entry['timestamp']
            
            if cache_age < AzureDiscoveryClient._agents_cache_ttl:
                _debug_print(f"DEBUG: ✅ Using cached agents list (age: {cache_age:.1f}s, TTL: {AzureDiscoveryClient._agents_cache_ttl}s)")
                return cached_entry['result']
            else:
                _debug_print(f"DEBUG: 🕐 Cache expired (age: {cache_age:.1f}s), fetching fresh data")
                # Remove expired entry
                del AzureDiscoveryClient._agents_cache[cache_key]
        
        _debug_print(f"DEBUG: list_discovery_agents called with:")
        _debug_print(f"  subscription_id: {subscription_id}")
        _debug_print(f"  resource_group: {resource_group}")
        _debug_print(f"  agent_name_pattern: {agent_name_pattern}")
        _debug_print(f"  tenant_id: {tenant_id}")
        
        # Use REST API
        result = self._list_agents_via_rest_api(subscription_id, resource_group, tenant_id=tenant_id)
        
        if result['success']:
            agents = result.get('agents', [])
            _debug_print(f"DEBUG: REST API returned {len(agents)} agents")
            
            if not agents:
                return {'exists': False, 'agents': [], 'message': 'No agents found in resource group'}
            
            # Log all agents for debugging
            _debug_print(f"DEBUG: Found agents:")
            for i, agent in enumerate(agents[:20]):  # Show first 20 agents (increased for debugging)
                if agent and isinstance(agent, dict):
                    agent_name = agent.get('name', 'Unknown')
                    _debug_print(f"  [{i}] {agent_name}")
            
            # If no pattern provided or pattern is "*", return all agents
            if not agent_name_pattern or agent_name_pattern == "*":
                valid_agents = [agent for agent in agents if agent and isinstance(agent, dict)]
                cached_result = {'exists': len(valid_agents) > 0, 'all_agents': valid_agents, 'message': f'Found {len(valid_agents)} agents'}
                
                # Cache the result
                AzureDiscoveryClient._agents_cache[cache_key] = {
                    'result': cached_result,
                    'timestamp': current_time
                }
                _debug_print(f"DEBUG: 💾 Cached agents list ({len(valid_agents)} agents) with key: {cache_key[:50]}...")
                return cached_result
            
            # Filter by agent name patterns
            matching_agents = []
            input_pattern = agent_name_pattern.lower()
            
            # For exact-only matching we use the full provided pattern (already lowercased)
            _debug_print("DEBUG: Using exact agent name matching only")
            
            checked_count = 0
            for i, agent in enumerate(agents):
                if not agent or not isinstance(agent, dict):
                    continue
                    
                try:
                    agent_name = agent.get('name', '')
                    checked_count += 1
                    
                    # Only accept exact name matches
                    exact_match = agent_name.lower() == input_pattern
                    if exact_match:
                        _debug_print(f"✓ Exact match {len(matching_agents)+1}: '{agent_name}'")
                        matching_agents.append({
                            'agent': agent,
                            'match_type': 'exact',
                            'agent_name': agent_name
                        })
                    
                except Exception as e:
                    _debug_print(f"DEBUG: Error processing agent {i}: {e}")
                    continue
            
            _debug_print(f"🔍 Checked {checked_count} agents, found {len(matching_agents)} matches")
            
            if matching_agents:
                # Sort matches by preference: exact first, then base_name
                match_priority = {'exact': 0, 'base_name': 1}
                sorted_matches = sorted(matching_agents, key=lambda x: match_priority.get(x['match_type'], 999))
                
                # Prepare detailed information for all matches
                agents_info = []
                for match in sorted_matches:
                    agent = match['agent']
                    properties = agent.get('properties') or {}  # Handle None properties
                    
                    # Get provisioning state from properties
                    if properties and 'provisioningState' in properties:
                        provisioning_state = properties['provisioningState']
                    elif 'provisioningState' in agent:
                        provisioning_state = agent['provisioningState']
                    else:
                        provisioning_state = 'Unknown'
                    
                    location = agent.get('location', 'Unknown')
                    
                    agents_info.append({
                        'name': match['agent_name'],
                        'match_type': match['match_type'],
                        'provisioning_state': provisioning_state,
                        'location': location,
                        'resource_id': agent.get('id', ''),
                        'agent_data': agent
                    })
                
                cached_result = {
                    'exists': True,
                    'total_matches': len(matching_agents),
                    'best_match': agents_info[0],  # First in sorted list
                    'all_agents': agents_info,
                    'message': f'Found {len(matching_agents)} matching agent(s)'
                }
                
                # Cache the result
                AzureDiscoveryClient._agents_cache[cache_key] = {
                    'result': cached_result,
                    'timestamp': current_time
                }
                _debug_print(f"DEBUG: 💾 Cached filtered agents result ({len(matching_agents)} matches) with key: {cache_key[:50]}...")
                return cached_result
            else:
                cached_result = {
                    'exists': False,
                    'message': f'No agents found matching pattern: {agent_name_pattern}'
                }
                
                # Cache the negative result too (to avoid repeated lookups for non-existent agents)
                AzureDiscoveryClient._agents_cache[cache_key] = {
                    'result': cached_result,
                    'timestamp': current_time
                }
                _debug_print(f"DEBUG: 💾 Cached negative result for key: {cache_key[:50]}...")
                return cached_result
                
        else:
            _debug_print(f"DEBUG: REST API call failed: {result.get('error', 'Unknown error')}")
            return {'exists': False, 'error': result.get('error', 'Unknown error'), 'message': 'Failed to list agents via REST API'}


    def get_discovery_agent_details(self, subscription_id: str, resource_group: str, agent_name: str, tenant_id: str) -> Dict[str, Any]:
        """Get detailed information for a specific Discovery agent.

        Retrieves full agent definition including:
        - Agent configuration (instructions, description, model)
        - Tools references with full resource IDs
        - Knowledge bases
        - Provisioning state and metadata

        Args:
            subscription_id: Azure subscription ID
            resource_group: Resource group name
            agent_name: Name of the agent to retrieve
            tenant_id: Azure tenant ID (must be provided)
        Returns:
            Dict with agent details or error information
        """
        # Build resource ID
        resource_id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/agents/{agent_name}"
        # Try REST API using azure_rest_call
        try:
            from azure_auth_helpers import azure_rest_call
            if not tenant_id:
                raise ValueError("Explicit tenant_id required for get_discovery_agent_details")
            url = f"https://management.azure.com{resource_id}?api-version=2025-07-01-preview"
            response = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=subscription_id,
                tenant_id=tenant_id
            )
            if response and 'error' not in response:
                return {
                    'success': True,
                    'agent_data': response,
                    'method': 'rest_api'
                }
            elif response and 'ResourceNotFound' in str(response.get('error', '')):
                return {
                    'success': False,
                    'error': 'resource_not_found',
                    'message': f"Agent '{agent_name}' not found in resource group '{resource_group}'",
                    'method': 'rest_api'
                }
            else:
                error = response.get('error', 'Unknown error') if response else 'No response'
                return {
                    'success': False,
                    'error': str(error),
                    'method': 'rest_api'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'method': 'rest_api'
            }

    def list_discovery_workflows(self, subscription_id: str, resource_group: str, workflow_name_pattern: Optional[str] = None, tenant_id: str = None) -> Dict[str, Any]:
        """List Microsoft Discovery workflows in a resource group using REST API, optionally filtered by name pattern."""
        _debug_print(f"DEBUG: list_discovery_workflows called with:")
        _debug_print(f"  subscription_id: {subscription_id}")
        _debug_print(f"  resource_group: {resource_group}")
        _debug_print(f"  workflow_name_pattern: {workflow_name_pattern}")

        # Build REST API URL to list workflows
        api_version = "2025-07-01-preview"
        url = (f"https://management.azure.com/subscriptions/{subscription_id}/"
               f"resourceGroups/{resource_group}/providers/Microsoft.Discovery/"
               f"workflows?api-version={api_version}")
        
        try:
            from azure_auth_helpers import azure_rest_call
            if not tenant_id:
                raise ValueError("Explicit tenant_id required for list_discovery_workflows")
            response = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=subscription_id,
                tenant_id=tenant_id
            )
            
            workflows = response.get('value', []) if response else []
            _debug_print(f"DEBUG: REST API returned {len(workflows)} workflows")

            if not workflows:
                return {'exists': False, 'workflows': [], 'message': 'No workflows found in resource group'}

            # If no pattern provided or pattern is "*", return all workflows
            if not workflow_name_pattern or workflow_name_pattern == "*":
                valid_wf = [wf for wf in workflows if wf and isinstance(wf, dict)]
                return {'exists': len(valid_wf) > 0, 'all_workflows': valid_wf, 'message': f'Found {len(valid_wf)} workflows'}

            input_pattern = workflow_name_pattern.lower()
            matching = []
            for wf in workflows:
                if not wf or not isinstance(wf, dict):
                    continue
                try:
                    name = wf.get('name', '')
                    if not isinstance(name, str):
                        continue
                    exact = name.lower() == input_pattern
                    base_match = input_pattern in name.lower()
                    if exact or base_match:
                        matching.append({
                            'workflow': wf,
                            'workflow_name': name,
                            'match_type': 'exact' if exact else 'base_name'
                        })
                except Exception as e:
                    _debug_print(f"DEBUG: Error processing workflow: {e}")
                    continue

            if matching:
                # Prefer exact matches first
                match_priority = {'exact': 0, 'base_name': 1}
                sorted_matches = sorted(matching, key=lambda x: match_priority.get(x['match_type'], 999))
                infos = []
                for m in sorted_matches:
                    wf = m['workflow']
                    infos.append({
                        'name': m['workflow_name'],
                        'match_type': m['match_type'],
                        'resource_id': wf.get('id', ''),
                        'workflow_data': wf
                    })
                return {
                    'exists': True,
                    'total_matches': len(infos),
                    'best_match': infos[0],
                    'all_workflows': infos,
                    'message': f'Found {len(infos)} matching workflow(s)'
                }
            else:
                return { 'exists': False, 'message': f'No workflows found matching pattern: {workflow_name_pattern}' }
        except Exception as e:
            _debug_print(f"DEBUG: Error listing workflows: {e}")
            return {'exists': False, 'error': f'Error listing workflows: {e}'}

    def get_discovery_tool_details(self, tool_resource_id: str, tenant_id: str = None) -> Optional[Dict[str, Any]]:
        """Get detailed information about a Discovery tool using REST API."""
        try:
            from azure_auth_helpers import azure_rest_call
            parts = tool_resource_id.split('/')
            if len(parts) < 3:
                _debug_print(f"DEBUG: Invalid resource ID format: {tool_resource_id}")
                return None
            
            subscription_id = parts[2]
            if not tenant_id:
                raise ValueError("Explicit tenant_id required for get_discovery_tool_details")
            url = f"https://management.azure.com{tool_resource_id}?api-version=2025-07-01-preview"
            _debug_print(f"DEBUG: Getting tool details via REST API: {tool_resource_id}")
            response = azure_rest_call(
                method='GET',
                url=url,
                subscription_id=subscription_id,
                tenant_id=tenant_id
            )
            
            if response and 'error' not in response:
                return response
            else:
                error = response.get('error', 'Unknown error') if response else 'No response'
                _debug_print(f"DEBUG: REST API failed to get tool details: {error}")
                return None
                
        except Exception as e:
            _debug_print(f"DEBUG: Exception getting tool details: {str(e)}")
            return None
    
    def delete_discovery_resource(self, resource_id: str, tenant_id: str = None) -> Dict[str, Any]:
        """Delete a Discovery resource (tool or agent) by resource ID using REST API."""
        _debug_print(f"DEBUG: Deleting Discovery resource: {resource_id}")
        
        try:
            from azure_auth_helpers import azure_rest_call
            parts = resource_id.split('/')
            if len(parts) < 3:
                error_msg = f"Invalid resource ID format: {resource_id}"
                _debug_print(f"DEBUG: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
            
            subscription_id = parts[2]
            if not tenant_id:
                raise ValueError("Explicit tenant_id required for delete_discovery_resource")
            url = f"https://management.azure.com{resource_id}?api-version=2025-07-01-preview"
            response = azure_rest_call(
                method='DELETE',
                url=url,
                subscription_id=subscription_id,
                tenant_id=tenant_id
            )
            
            # DELETE typically returns empty response on success
            if response is not None and 'error' not in response:
                _debug_print(f"DEBUG: Resource deleted successfully: {resource_id}")
                return {
                    'success': True,
                    'message': f'Resource deleted: {resource_id}'
                }
            else:
                error_msg = response.get('error', 'Unknown error during deletion') if response else 'No response'
                _debug_print(f"DEBUG: Failed to delete resource {resource_id}: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
                
        except Exception as e:
            error_msg = str(e)
            _debug_print(f"DEBUG: Exception deleting resource {resource_id}: {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }

    def update_discovery_resource(self, resource_id: str, resource_type: str, updated_definition: Dict[str, Any]) -> Dict[str, Any]:
        """Update a Discovery resource (tool or agent) with new definition content."""
        _debug_print(f"DEBUG: Updating Discovery resource: {resource_id}")
        
        # Extract subscription, resource group, and resource name from resource ID
        # Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Discovery/{type}/{name}
        parts = resource_id.split('/')
        if len(parts) < 8:
            return {'success': False, 'error': 'Invalid resource ID format'}
            
        subscription_id = parts[2]
        resource_group = parts[4]
        resource_name = parts[8]
        
        # Construct the REST API URL for update
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Discovery/{resource_type}s/{resource_name}"
            f"?api-version=2025-07-01-preview"
        )
        
        # Prepare the payload for update (PATCH operation)
        # Ensure required top-level fields are present in definitionContent
        enhanced_definition = {
            "Name": updated_definition.get("name", resource_name),
            "Description": updated_definition.get("description", f"{resource_type.title()} definition"),
            "Version": updated_definition.get("version", "1.0.0"),
            "Category": updated_definition.get("category", "General"),
            **updated_definition  # Include all original fields
        }
        
        # Extract environment variables from updated definition if they exist
        env_vars = {}
        if 'properties' in updated_definition and 'environmentVariables' in updated_definition['properties']:
            env_vars = updated_definition['properties']['environmentVariables']
            _debug_print(f"DEBUG: Extracted environment variables for update: {env_vars}")
        else:
            _debug_print("DEBUG: No environment variables found in update definition")
        
        payload = {
            "properties": {
                "definitionContent": enhanced_definition,
                "version": updated_definition.get("version", "1.0.0"),
                "environmentVariables": env_vars
            }
        }
        
        _debug_print(f"DEBUG: Running REST API update command for {resource_name}")
        result = self._azure_rest_call('PATCH', url, body=payload, timeout=180)
        
        if result['success']:
            response_data = result.get('data')
            if response_data:
                _debug_print(f"DEBUG: Resource update successful, provisioning state: {response_data.get('properties', {}).get('provisioningState')}")
                return {
                    'success': True,
                    'resource_id': response_data.get('id'),
                    'resource_name': response_data.get('name'),
                    'provisioning_state': response_data.get('properties', {}).get('provisioningState'),
                    'data': response_data
                }
            else:
                _debug_print("DEBUG: Empty response but update command succeeded")
                return {
                    'success': True,
                    'resource_id': resource_id,
                    'message': 'Resource updated successfully'
                }
        else:
            _debug_print(f"DEBUG: Resource update failed: {result.get('error')}")
            return {
                'success': False,
                'error': result.get('error'),
                'stderr': result.get('stderr')
            }

    def create_discovery_tool_rest(self, 
                                  subscription_id: str,
                                  resource_group: str, 
                                  tool_name: str,
                                  tool_definition: Dict[str, Any],
                                  location: str = "uksouth") -> Dict[str, Any]:
        """Create Discovery tool using REST API (bypasses ARM template CLI bug)."""
        
        _debug_print(f"DEBUG: Creating Discovery tool via REST API: {tool_name}")
        
        # Construct the REST API URL
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Discovery/tools/{tool_name}"
            f"?api-version=2025-07-01-preview"
        )
        
        # Prepare the payload (definitionContent as JSON object for REST API)
        # Ensure required top-level fields are present in definitionContent
        enhanced_definition = {
            "Name": tool_definition.get("name", tool_name),
            "Description": tool_definition.get("description", "Tool definition"),
            "Version": tool_definition.get("version", "1.0.0"),
            "Category": tool_definition.get("category", "General"),
            **tool_definition  # Include all original fields
        }
        
        # Extract environment variables from tool definition if they exist
        env_vars = {}
        if 'properties' in tool_definition and 'environmentVariables' in tool_definition['properties']:
            env_vars = tool_definition['properties']['environmentVariables']
            _debug_print(f"DEBUG: Extracted environment variables: {env_vars}")
        else:
            _debug_print("DEBUG: No environment variables found in tool definition")
            _debug_print(f"DEBUG: Tool definition structure: {json.dumps(tool_definition, indent=2)[:500]}...")
        
        payload = {
            "properties": {
                "version": tool_definition.get("version", "1.0.0"),
                "definitionContent": enhanced_definition,  # JSON object with required fields
                "environmentVariables": env_vars
            },
            "location": location
        }
        
        _debug_print(f"DEBUG: Tool definition keys: {list(tool_definition.keys())}")
        _debug_print(f"DEBUG: Tool name: {tool_definition.get('name')}")
        _debug_print(f"DEBUG: Tool version: {tool_definition.get('version')}")
        if 'properties' in tool_definition:
            _debug_print(f"DEBUG: Tool properties keys: {list(tool_definition['properties'].keys())}")
            if 'environmentVariables' in tool_definition['properties']:
                _debug_print(f"DEBUG: Environment variables found: {tool_definition['properties']['environmentVariables']}")
            else:
                _debug_print("DEBUG: No environmentVariables in tool properties")
        else:
            _debug_print("DEBUG: No properties section in tool definition")
        
        _debug_print(f"DEBUG: Running REST API command for tool creation")
        result = self._azure_rest_call('PUT', url, body=payload, timeout=300)
        
        _debug_print(f"DEBUG: REST API result: success={result['success']}")
        
        if result['success']:
            response_data = result.get('data')
            if response_data:
                _debug_print(f"DEBUG: Tool creation successful, provisioning state: {response_data.get('properties', {}).get('provisioningState')}")
                return {
                    'success': True,
                    'tool_id': response_data.get('id'),
                    'tool_name': response_data.get('name'),
                    'provisioning_state': response_data.get('properties', {}).get('provisioningState'),
                    'data': response_data
                }
            else:
                _debug_print("DEBUG: Empty response but command succeeded")
                return {
                    'success': True,
                    'data': None
                }
        else:
            _debug_print(f"DEBUG: Tool creation failed: {result.get('error')}")
            return {
                'success': False,
                'error': result.get('error'),
                'stderr': result.get('stderr')
            }
    
    def create_discovery_agent_rest(self,
                                   subscription_id: str,
                                   resource_group: str,
                                   agent_name: str,
                                   agent_definition: Dict[str, Any],
                                   tool_id: str,
                                   tenant_id: str,
                                   location: str = "uksouth") -> Dict[str, Any]:
        """Create Discovery agent using REST API."""
        
        _debug_print(f"DEBUG: Creating Discovery agent via REST API: {agent_name}")
        
        # Construct the REST API URL
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Discovery/agents/{agent_name}"
            f"?api-version=2025-07-01-preview"
        )
        
        # Prepare the payload - agents need to reference the tool
        agent_definition_with_tool = agent_definition.copy()
        if 'tools' not in agent_definition_with_tool:
            agent_definition_with_tool['tools'] = []

        # Add tool reference if not already present
        tool_ref = {"tool_id": tool_id}
        if tool_ref not in agent_definition_with_tool['tools']:
            agent_definition_with_tool['tools'].append(tool_ref)

        # Ensure required top-level fields are present in definitionContent for agents
        enhanced_agent_definition = {
            "Name": agent_definition.get("name", agent_name),
            "Description": agent_definition.get("description", "Agent definition"),
            "Version": agent_definition.get("version", "1.0.0"),
            "Category": agent_definition.get("category", "General"),
            **agent_definition_with_tool  # Include all original fields
        }
        
        payload = {
            "properties": {
                "version": agent_definition.get("version", "1.0.0"),
                "definitionContent": enhanced_agent_definition,  # JSON object with required fields
            },
            "location": location
        }
        
        _debug_print(f"DEBUG: Agent definition keys: {list(agent_definition.keys())}")
        _debug_print(f"DEBUG: Agent name: {agent_definition.get('name')}")
        _debug_print(f"DEBUG: Agent version: {agent_definition.get('version')}")
        _debug_print(f"DEBUG: Tool reference: {tool_id}")
        
        try:
            from azure_auth_helpers import azure_rest_call
            if not tenant_id:
                raise ValueError("Explicit tenant_id required for create_discovery_agent_rest")
            
            _debug_print(f"DEBUG: Creating agent via REST API: {url}")
            response = azure_rest_call(
                method='PUT',
                url=url,
                subscription_id=subscription_id,
                tenant_id=tenant_id,
                body=payload
            )
            
            _debug_print(f"DEBUG: REST API response received")
            
            if response and 'error' not in response:
                _debug_print(f"DEBUG: Agent creation successful, provisioning state: {response.get('properties', {}).get('provisioningState')}")
                return {
                    'success': True,
                    'agent_id': response.get('id'),
                    'agent_name': response.get('name'),
                    'provisioning_state': response.get('properties', {}).get('provisioningState'),
                    'data': response
                }
            else:
                error = response.get('error', 'Unknown error') if response else 'No response'
                _debug_print(f"DEBUG: Agent creation failed: {error}")
                return {
                    'success': False,
                    'error': str(error)
                }
        except Exception as e:
            _debug_print(f"DEBUG: Exception during agent creation: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }


def main():
    """Test the Discovery client."""
    client = AzureDiscoveryClient()
    _debug_print("Discovery client initialized successfully")

if __name__ == "__main__":
    main()
