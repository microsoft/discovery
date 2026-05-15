"""
Nodepool Service - Centralized nodepool data management with caching.

Provides:
- Thread-safe caching of nodepool data with configurable TTL
- Reuses existing Azure API functions from workbench_common
- Human-readable context generation for agent instructions
- Integration with optimization preference settings

Note: This module reuses get_supercomputer_nodepools() from workbench_common.py
for Azure API calls to avoid code duplication.
"""

import threading
import time
import requests
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# Import existing nodepool fetching function from workbench_common
try:
    from workbench_common import get_supercomputer_nodepools
except ImportError:
    get_supercomputer_nodepools = None


# Global cache with thread-safe access
NODEPOOL_CACHE: Dict[str, Dict[str, Any]] = {}
NODEPOOL_CACHE_LOCK = threading.Lock()
DEFAULT_CACHE_TTL_HOURS = 24


@dataclass
class NodepoolInfo:
    """Structured nodepool information"""
    name: str
    id: str
    vm_size: str
    cpu_cores: int = 0
    memory_gb: float = 0.0
    gpu_count: int = 0
    gpu_type: Optional[str] = None
    infiniband_enabled: bool = False
    max_nodes: int = 0
    current_nodes: int = 0
    pool_type: str = "static"
    location: str = ""
    estimated_cost_per_hour: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'name': self.name,
            'id': self.id,
            'vm_size': self.vm_size,
            'cpu_cores': self.cpu_cores,
            'memory_gb': self.memory_gb,
            'gpu_count': self.gpu_count,
            'gpu_type': self.gpu_type,
            'infiniband_enabled': self.infiniband_enabled,
            'max_nodes': self.max_nodes,
            'current_nodes': self.current_nodes,
            'pool_type': self.pool_type,
            'location': self.location,
            'estimated_cost_per_hour': self.estimated_cost_per_hour
        }


class NodepoolService:
    """Service for managing nodepool data and context generation"""

    def __init__(self, config_manager):
        """Initialize with configuration manager

        Args:
            config_manager: DiscoveryConfigManager instance for loading config
        """
        self.config_manager = config_manager

    def get_cache_key(self, subscription_id: str, resource_group: str,
                      supercomputer_name: str) -> str:
        """Generate cache key for nodepool data

        Args:
            subscription_id: Azure subscription ID
            resource_group: Azure resource group name
            supercomputer_name: Name of the supercomputer

        Returns:
            Cache key string
        """
        return f"{subscription_id}:{resource_group}:{supercomputer_name}"

    def get_cached_nodepools(self, subscription_id: str, resource_group: str,
                              supercomputer_name: str,
                              cache_ttl_hours: int = DEFAULT_CACHE_TTL_HOURS) -> Optional[Dict[str, Any]]:
        """Retrieve cached nodepool data if still valid

        Args:
            subscription_id: Azure subscription ID
            resource_group: Azure resource group name
            supercomputer_name: Name of the supercomputer
            cache_ttl_hours: Cache TTL in hours

        Returns:
            Cached data dict or None if cache miss/expired
        """
        cache_key = self.get_cache_key(subscription_id, resource_group, supercomputer_name)

        with NODEPOOL_CACHE_LOCK:
            if cache_key not in NODEPOOL_CACHE:
                return None

            cached = NODEPOOL_CACHE[cache_key]
            cached_time = cached.get('timestamp', 0)
            ttl_seconds = cache_ttl_hours * 3600

            if time.time() - cached_time > ttl_seconds:
                # Cache expired
                del NODEPOOL_CACHE[cache_key]
                return None

            return cached.get('data')

    def set_cached_nodepools(self, subscription_id: str, resource_group: str,
                              supercomputer_name: str, data: Dict[str, Any]) -> None:
        """Cache nodepool data with timestamp

        Args:
            subscription_id: Azure subscription ID
            resource_group: Azure resource group name
            supercomputer_name: Name of the supercomputer
            data: Nodepool data to cache
        """
        cache_key = self.get_cache_key(subscription_id, resource_group, supercomputer_name)

        with NODEPOOL_CACHE_LOCK:
            NODEPOOL_CACHE[cache_key] = {
                'timestamp': time.time(),
                'data': data
            }

    def clear_cache(self, subscription_id: Optional[str] = None, resource_group: Optional[str] = None,
                    supercomputer_name: Optional[str] = None) -> int:
        """Clear nodepool cache

        Args:
            subscription_id: Optional - clear only for this subscription
            resource_group: Optional - clear only for this resource group
            supercomputer_name: Optional - clear only for this supercomputer

        Returns:
            Number of cache entries cleared
        """
        with NODEPOOL_CACHE_LOCK:
            if subscription_id and resource_group and supercomputer_name:
                # Clear specific entry
                cache_key = self.get_cache_key(subscription_id, resource_group, supercomputer_name)
                if cache_key in NODEPOOL_CACHE:
                    del NODEPOOL_CACHE[cache_key]
                    return 1
                return 0
            else:
                # Clear all
                count = len(NODEPOOL_CACHE)
                NODEPOOL_CACHE.clear()
                return count

    def fetch_vm_sku_details(self, access_token: str, subscription_id: str,
                             location: str) -> Dict[str, Dict[str, Any]]:
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
                'Accept': 'application/json',
                'User-Agent': 'Microsoft-Discovery-AgentWorkbench/1.0',
            }
            params = {
                'api-version': '2021-07-01',
                '$filter': f"location eq '{location}'"
            }

            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code != 200:
                print(f"[NodepoolService] Warning: Failed to fetch VM SKU details: {response.status_code}")
                return {}

            skus_data = response.json()
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

                    # Check for GPU and RDMA/InfiniBand capabilities
                    gpu_count = int(capabilities.get('GPUs', 0))
                    rdma_enabled = capabilities.get('RdmaEnabled', 'False') == 'True'

                    if cpu_count > 0 and memory_gb > 0:
                        vm_sku_map[sku_name] = {
                            'cpu_cores': cpu_count,
                            'memory_gb': memory_gb,
                            'gpu_count': gpu_count,
                            'rdma_enabled': rdma_enabled,
                            'tier': sku.get('tier', 'Standard'),
                            'family': sku.get('family', 'Unknown'),
                        }
                except (ValueError, TypeError, KeyError):
                    continue

            return vm_sku_map

        except Exception as e:
            print(f"[NodepoolService] Warning: Failed to fetch VM SKU details: {e}")
            return {}

    def fetch_nodepools_with_specs(self, subscription_id: str, resource_group: str,
                                    supercomputer_name: str, tenant_id: str,
                                    access_token: str, location: str) -> Dict[str, Any]:
        """Fetch nodepools from Azure API and enrich with VM SKU specs

        Reuses get_supercomputer_nodepools() from workbench_common.py for the base
        API call, then enriches with VM SKU details.

        Args:
            subscription_id: Azure subscription ID
            resource_group: Azure resource group name
            supercomputer_name: Name of the supercomputer
            tenant_id: Azure tenant ID
            access_token: Azure access token
            location: Azure region

        Returns:
            Dict with success status and list of NodepoolInfo objects
        """
        try:
            # Fetch VM SKU details for enrichment
            vm_sku_details = self.fetch_vm_sku_details(access_token, subscription_id, location)

            # Use existing function from workbench_common if available
            if get_supercomputer_nodepools is not None:
                result = get_supercomputer_nodepools(
                    subscription_id, resource_group, supercomputer_name, access_token
                )
                if not result.get('success'):
                    return {
                        'success': False,
                        'error': result.get('error', 'Failed to fetch nodepools'),
                        'nodepools': []
                    }
                nodepools_raw = result.get('nodepools', [])
            else:
                # Fallback: direct API call if workbench_common not available
                url = f"https://management.azure.com/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.Discovery/supercomputers/{supercomputer_name}/nodepools"
                headers = {
                    'Authorization': f'Bearer {access_token}',
                    'Accept': 'application/json',
                    'User-Agent': 'Microsoft-Discovery-AgentWorkbench/1.0',
                }
                params = {'api-version': '2025-07-01-preview'}

                response = requests.get(url, headers=headers, params=params, timeout=30)

                if response.status_code != 200:
                    return {
                        'success': False,
                        'error': f"Failed to fetch nodepools: {response.status_code}",
                        'nodepools': []
                    }

                nodepool_data = response.json()
                # Transform to match workbench_common format
                nodepools_raw = []
                for np in nodepool_data.get('value', []):
                    properties = np.get('properties', {})
                    nodepools_raw.append({
                        'name': np.get('name', ''),
                        'id': np.get('id', ''),
                        'vmSize': properties.get('vmSize', 'Unknown'),
                        'maxNodes': properties.get('maxNodeCount', 0),
                        'minNodes': properties.get('minNodeCount', 0),
                        'currentNodes': properties.get('currentNodeCount', 0),
                        'provisioningState': properties.get('provisioningState', ''),
                        'location': np.get('location', location),
                        'poolType': properties.get('poolType', 'static')
                    })

            if not nodepools_raw:
                return {
                    'success': True,
                    'nodepools': [],
                    'message': 'No nodepools found'
                }

            # Enrich with VM SKU details and convert to NodepoolInfo
            nodepool_list: List[NodepoolInfo] = []

            for np in nodepools_raw:
                # Filter: only include nodepools that are in 'Succeeded' provisioning state
                provisioning_state = np.get('provisioningState', 'Unknown')
                if provisioning_state != 'Succeeded':
                    continue

                np_name = np.get('name', 'unknown')
                np_id = np.get('id', '')
                vm_size = np.get('vmSize', 'Unknown')

                # Get detailed VM SKU information if available
                vm_specs = vm_sku_details.get(vm_size, {})

                # Fallback defaults if SKU details not available
                if not vm_specs:
                    vm_specs = {
                        'cpu_cores': 0,
                        'memory_gb': 0,
                        'gpu_count': 0,
                        'rdma_enabled': False,
                    }

                np_location = np.get('location', location)
                max_node_count = np.get('maxNodes', 0)
                current_node_count = np.get('currentNodes', 0)
                pool_type = np.get('poolType', 'static')

                # Get gpu_type as string or None
                gpu_type_val = vm_specs.get('gpu_type')
                gpu_type_str = str(gpu_type_val) if gpu_type_val is not None else None

                nodepool_info = NodepoolInfo(
                    name=np_name,
                    id=np_id,
                    vm_size=vm_size,
                    cpu_cores=int(vm_specs.get('cpu_cores', 0)),
                    memory_gb=float(vm_specs.get('memory_gb', 0)),
                    gpu_count=int(vm_specs.get('gpu_count', 0)),
                    gpu_type=gpu_type_str,
                    infiniband_enabled=bool(vm_specs.get('rdma_enabled', False)),
                    max_nodes=int(max_node_count) if max_node_count else 0,
                    current_nodes=int(current_node_count) if current_node_count else 0,
                    pool_type=pool_type,
                    location=np_location
                )
                nodepool_list.append(nodepool_info)

            # Sort by name for consistency
            nodepool_list.sort(key=lambda x: x.name)

            return {
                'success': True,
                'nodepools': nodepool_list,
                'count': len(nodepool_list),
                'supercomputer': supercomputer_name,
                'location': location
            }

        except Exception as e:
            print(f"[NodepoolService] Error fetching nodepools: {e}")
            return {
                'success': False,
                'error': str(e),
                'nodepools': []
            }

    def generate_nodepool_context(self, nodepools: List[NodepoolInfo],
                                   optimization_preference: str = 'balanced',
                                   tool_requirements: Optional[Dict[str, Any]] = None) -> str:
        """Generate human-readable nodepool context for LLM injection

        Args:
            nodepools: List of NodepoolInfo objects
            optimization_preference: One of "performance", "cost", "balanced"
            tool_requirements: Optional dict with keys like 'gpu', 'infiniband', 'min_memory_gb'

        Returns:
            Formatted string for template variable replacement
        """
        if not nodepools:
            return """## Available Compute Nodepools

No nodepools are currently available. Please ensure the Discovery Supercomputer is properly configured.
"""

        lines = []

        # Tool requirements block (compact, if provided)
        if tool_requirements:
            reqs = []
            if tool_requirements.get('gpu'):
                reqs.append("GPU: required")
            if tool_requirements.get('infiniband'):
                reqs.append("InfiniBand: required")
            if tool_requirements.get('min_memory_gb'):
                reqs.append(f"Memory: ≥{tool_requirements['min_memory_gb']}GB")
            if tool_requirements.get('min_cpu_cores'):
                reqs.append(f"CPU: ≥{tool_requirements['min_cpu_cores']} cores")
            if reqs:
                lines.append(f"**Tool Requirements:** {' | '.join(reqs)}")
                lines.append("")

        # Header with optimization preference
        preference_descriptions = {
            'performance': 'prioritize speed',
            'cost': 'prioritize cost-efficiency',
            'balanced': 'balance cost and performance'
        }
        pref_desc = preference_descriptions.get(optimization_preference, preference_descriptions['balanced'])

        lines.extend([
            "## Available Compute Nodepools",
            f"**Optimization: {optimization_preference}** ({pref_desc})",
            ""
        ])

        # Generate compact details for each nodepool
        for np in nodepools:
            lines.append(f"### {np.name}")

            # Compact specs line
            specs = [f"{np.cpu_cores} CPU", f"{np.memory_gb:.0f}GB RAM"]
            if np.gpu_count > 0:
                gpu_str = f"{np.gpu_count}x GPU"
                if np.gpu_type:
                    gpu_str = f"{np.gpu_count}x {np.gpu_type}"
                specs.append(gpu_str)
            if np.infiniband_enabled:
                specs.append("IB")
            lines.append(f"- {np.vm_size}: {' | '.join(specs)}")
            lines.append(f"- Max {np.max_nodes} nodes, {np.pool_type}")
            lines.append("")

        # Compact recommendation format - emphasize JSON is REQUIRED as additional output
        lines.extend([
            "**REQUIRED: After providing your tool invocation or code, append this JSON block:**",
            "```json",
            '{"nodepool_compatibility": [{"nodepool_name": "NAME", "status": "preferred|compatible|not_compatible", "reason": "..."}]}',
            "```",
            "Status: `preferred`=best fit | `compatible`=works but suboptimal | `not_compatible`=will FAIL",
            "Rule: GPU pool for CPU-only → `compatible`. Use `not_compatible` only for actual failures."
        ])

        return '\n'.join(lines)

    def get_nodepool_context_for_agent(self, tool_requirements: Optional[Dict[str, Any]] = None) -> str:
        """Main entry point: get formatted nodepool context for agent instructions

        Loads configuration, fetches/caches nodepool data, and generates context string.

        Args:
            tool_requirements: Optional dict with keys like 'gpu', 'infiniband', 'min_memory_gb'

        Returns:
            Formatted nodepool context string for template variable replacement
        """
        try:
            # Load configuration
            config = self.config_manager.load_config()
            if not config:
                return "## Available Compute Nodepools\n\nConfiguration not available. Nodepool context cannot be loaded."

            azure_config = config.get('azure', {})
            azure_compute_config = config.get('azure_compute', {})

            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            tenant_id = azure_config.get('tenant_id', '').strip()
            supercomputer_name = azure_compute_config.get('discovery_supercomputer', '').strip()
            location = azure_config.get('location', 'swedencentral').strip()
            optimization_preference = azure_compute_config.get('optimization_preference', 'balanced')
            cache_ttl_hours = azure_compute_config.get('nodepool_cache_ttl_hours', DEFAULT_CACHE_TTL_HOURS)

            if not subscription_id or not resource_group or not supercomputer_name:
                return """## Available Compute Nodepools

Azure configuration incomplete. Please configure subscription_id, resource_group, and discovery_supercomputer in settings.
"""

            # Check cache first
            cached_data = self.get_cached_nodepools(
                subscription_id, resource_group, supercomputer_name, cache_ttl_hours
            )

            if cached_data:
                nodepools = cached_data.get('nodepools', [])
                # Convert dicts back to NodepoolInfo if needed
                if nodepools and isinstance(nodepools[0], dict):
                    nodepools = [NodepoolInfo(**np) for np in nodepools]
                return self.generate_nodepool_context(nodepools, optimization_preference, tool_requirements)

            # Need to fetch fresh data - get access token
            if not tenant_id:
                return """## Available Compute Nodepools

Azure tenant_id not configured. Please sign in to Azure to enable nodepool context.
"""

            try:
                from azure_auth_helpers import get_token_for_tenant
                server_traces = []
                access_token = get_token_for_tenant(
                    "https://management.azure.com/.default",
                    tenant_id,
                    server_traces,
                    purpose='nodepool-context'
                )
                if not access_token:
                    return """## Available Compute Nodepools

Failed to obtain Azure access token. Please ensure you are signed in to Azure.
"""
            except ImportError:
                return """## Available Compute Nodepools

Azure authentication module not available. Nodepool context cannot be loaded.
"""
            except Exception as e:
                print(f"[NodepoolService] Error getting access token: {e}")
                return f"""## Available Compute Nodepools

Error authenticating with Azure: {str(e)}
"""

            # Fetch nodepools
            result = self.fetch_nodepools_with_specs(
                subscription_id, resource_group, supercomputer_name,
                tenant_id, access_token, location
            )

            if not result.get('success'):
                error_msg = result.get('error', 'Unknown error')
                return f"""## Available Compute Nodepools

Failed to fetch nodepool information: {error_msg}
"""

            nodepools = result.get('nodepools', [])

            # Cache the results (convert to dicts for JSON serialization)
            cache_data = {
                'nodepools': [np.to_dict() for np in nodepools],
                'supercomputer': supercomputer_name,
                'location': location
            }
            self.set_cached_nodepools(subscription_id, resource_group, supercomputer_name, cache_data)

            return self.generate_nodepool_context(nodepools, optimization_preference, tool_requirements)

        except Exception as e:
            print(f"[NodepoolService] Error generating nodepool context: {e}")
            import traceback
            traceback.print_exc()
            return f"""## Available Compute Nodepools

Error loading nodepool context: {str(e)}
"""


# Singleton instance for easy access
_nodepool_service_instance: Optional[NodepoolService] = None


def get_nodepool_service(config_manager=None) -> Optional[NodepoolService]:
    """Get or create the NodepoolService singleton

    Args:
        config_manager: Optional config manager to initialize with

    Returns:
        NodepoolService instance or None if not initialized
    """
    global _nodepool_service_instance

    if _nodepool_service_instance is None and config_manager is not None:
        _nodepool_service_instance = NodepoolService(config_manager)

    return _nodepool_service_instance


def initialize_nodepool_service(config_manager) -> NodepoolService:
    """Initialize the NodepoolService with a config manager

    Args:
        config_manager: DiscoveryConfigManager instance

    Returns:
        Initialized NodepoolService instance
    """
    global _nodepool_service_instance
    _nodepool_service_instance = NodepoolService(config_manager)
    return _nodepool_service_instance
