"""
Azure Discovery Data Asset Manager

Provides utilities for managing Discovery data assets including automatic creation
of workbench assets when they're not configured or don't exist.

This module handles:
- Checking if data assets exist
- Creating data assets with proper authentication
- Validating data asset resource IDs
- Providing default asset names and paths

Functions:
- check_data_asset_exists(): Check if a data asset exists
- create_data_asset(): Create a new data asset
- ensure_data_asset(): Ensure a data asset exists (check and create if needed)
- parse_data_asset_resource_id(): Parse a data asset resource ID
- generate_default_asset_name(): Generate a default asset name
"""

import requests
import json
import time
from typing import Dict, Any, Optional, List, Tuple
from azure_auth_helpers import get_token_for_tenant


def parse_data_asset_resource_id(resource_id: str) -> Dict[str, str]:
    """
    Parse a Discovery data asset resource ID into its components.
    
    Args:
        resource_id: Full Azure resource ID for the data asset
                    Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Discovery/
                           dataContainers/{container}/dataAssets/{asset}
    
    Returns:
        Dict with keys: subscription_id, resource_group, data_container, asset_name
        
    Raises:
        ValueError: If resource ID format is invalid
    """
    try:
        parts = resource_id.strip('/').split('/')
        if len(parts) < 8:
            raise ValueError("Resource ID too short")
        
        # Find the indices of key segments
        if 'subscriptions' not in parts or 'resourceGroups' not in parts:
            raise ValueError("Invalid resource ID format")
        
        sub_idx = parts.index('subscriptions')
        rg_idx = parts.index('resourceGroups')
        
        # Case-insensitive search for datacontainers and dataassets
        container_idx = -1
        asset_idx = -1
        
        for i, part in enumerate(parts):
            if part.lower() == 'datacontainers':
                container_idx = i
            elif part.lower() == 'dataassets':
                asset_idx = i
        
        if container_idx == -1 or asset_idx == -1:
            raise ValueError("Missing dataContainers or dataAssets in resource ID")
        
        return {
            'subscription_id': parts[sub_idx + 1],
            'resource_group': parts[rg_idx + 1],
            'data_container': parts[container_idx + 1],
            'asset_name': parts[asset_idx + 1]
        }
    except Exception as e:
        raise ValueError(f"Failed to parse data asset resource ID '{resource_id}': {str(e)}")


def generate_default_asset_name(purpose: str = "workbench") -> str:
    """
    Generate a default data asset name.
    
    Args:
        purpose: Purpose of the asset (e.g., "workbench", "inputs", "outputs")
    
    Returns:
        Generated asset name
    """
    return purpose.lower()


def check_data_asset_exists(
    subscription_id: str,
    resource_group: str,
    data_container: str,
    asset_name: str,
    tenant_id: str,
    server_traces: Optional[List[str]] = None,
    api_version: str = "2025-07-01-preview"
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if a data asset exists in Azure Discovery.
    
    Args:
        subscription_id: Azure subscription ID
        resource_group: Resource group name
        data_container: Data container name
        asset_name: Data asset name
        tenant_id: Azure AD tenant ID for authentication
        server_traces: Optional list to append trace messages
        api_version: Discovery API version
    
    Returns:
        Tuple of (exists: bool, asset_data: Optional[Dict])
        If exists is True, asset_data contains the asset properties
        
    Raises:
        Exception: If API call fails with unexpected error
    """
    if server_traces is None:
        server_traces = []
    
    try:
        # Get management token for the tenant
        token = get_token_for_tenant(
            scope='https://management.azure.com/.default',
            tenant_id=tenant_id,
            server_traces=server_traces,
            purpose='check-data-asset'
        )
        
        if not token:
            raise Exception("Failed to obtain management token")
        
        # Build the API URL
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Discovery/dataContainers/{data_container}"
            f"/dataAssets/{asset_name}?api-version={api_version}"
        )
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json',
            'User-Agent': 'Microsoft-Discovery-AgentWorkbench/1.0',
        }
        
        server_traces.append(f"🔍 Checking data asset: {asset_name}")
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            asset_data = response.json()
            server_traces.append(f"✅ Data asset '{asset_name}' exists")
            return True, asset_data
        elif response.status_code == 404:
            server_traces.append(f"ℹ️ Data asset '{asset_name}' does not exist")
            return False, None
        else:
            # Unexpected status code
            error_msg = f"Unexpected status {response.status_code} checking data asset"
            try:
                error_body = response.json()
                error_msg += f": {error_body.get('error', {}).get('message', response.text)}"
            except:
                error_msg += f": {response.text}"
            
            server_traces.append(f"⚠️ {error_msg}")
            raise Exception(error_msg)
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error checking data asset: {str(e)}"
        server_traces.append(f"❌ {error_msg}")
        raise Exception(error_msg)
    except Exception as e:
        if "Failed to obtain management token" in str(e):
            raise
        error_msg = f"Error checking data asset: {str(e)}"
        server_traces.append(f"❌ {error_msg}")
        raise Exception(error_msg)


def create_data_asset(
    subscription_id: str,
    resource_group: str,
    data_container: str,
    asset_name: str,
    location: str,
    tenant_id: str,
    description: Optional[str] = None,
    path: Optional[str] = None,
    server_traces: Optional[List[str]] = None,
    api_version: str = "2025-07-01-preview",
    wait_for_provisioning: bool = True,
    max_wait_seconds: int = 120
) -> Dict[str, Any]:
    """
    Create a new data asset in Azure Discovery.
    
    Args:
        subscription_id: Azure subscription ID
        resource_group: Resource group name
        data_container: Data container name
        asset_name: Data asset name to create
        location: Azure region (e.g., "eastus")
        tenant_id: Azure AD tenant ID for authentication
        description: Optional description for the asset
        path: Optional storage path (defaults to "{asset_name}/")
        server_traces: Optional list to append trace messages
        api_version: Discovery API version
        wait_for_provisioning: Whether to wait for provisioning to complete
        max_wait_seconds: Maximum seconds to wait for provisioning
    
    Returns:
        Dict containing the created asset data
        
    Raises:
        Exception: If asset creation fails
    """
    if server_traces is None:
        server_traces = []
    
    try:
        # Get management token for the tenant
        token = get_token_for_tenant(
            scope='https://management.azure.com/.default',
            tenant_id=tenant_id,
            server_traces=server_traces,
            purpose='create-data-asset'
        )
        
        if not token:
            raise Exception("Failed to obtain management token")
        
        # Build the API URL
        url = (
            f"https://management.azure.com/subscriptions/{subscription_id}"
            f"/resourceGroups/{resource_group}"
            f"/providers/Microsoft.Discovery/dataContainers/{data_container}"
            f"/dataAssets/{asset_name}?api-version={api_version}"
        )
        
        # Build the request body
        if path is None:
            path = f"{asset_name}/"
        
        if description is None:
            description = f"Auto-created data asset for {asset_name}"
        
        body = {
            "location": location,
            "properties": {
                "description": description,
                "path": path
            }
        }
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Microsoft-Discovery-AgentWorkbench/1.0',
        }
        
        server_traces.append(f"📦 Creating data asset: {asset_name}")
        server_traces.append(f"   Location: {location}")
        server_traces.append(f"   Path: {path}")
        
        response = requests.put(url, headers=headers, json=body, timeout=60)
        
        if response.status_code not in [200, 201]:
            error_msg = f"Failed to create data asset (status {response.status_code})"
            try:
                error_body = response.json()
                error_msg += f": {error_body.get('error', {}).get('message', response.text)}"
            except:
                error_msg += f": {response.text}"
            
            server_traces.append(f"❌ {error_msg}")
            raise Exception(error_msg)
        
        asset_data = response.json()
        provisioning_state = asset_data.get('properties', {}).get('provisioningState', 'Unknown')
        
        server_traces.append(f"✅ Data asset created: {asset_name} (state: {provisioning_state})")
        
        # Wait for provisioning to complete if requested
        if wait_for_provisioning and provisioning_state not in ['Succeeded', 'Failed']:
            server_traces.append(f"⏳ Waiting for provisioning to complete...")
            
            start_time = time.time()
            poll_interval = 5  # seconds
            
            while (time.time() - start_time) < max_wait_seconds:
                time.sleep(poll_interval)
                
                # Check status
                check_response = requests.get(url, headers=headers, timeout=30)
                if check_response.status_code == 200:
                    asset_data = check_response.json()
                    provisioning_state = asset_data.get('properties', {}).get('provisioningState', 'Unknown')
                    
                    if provisioning_state == 'Succeeded':
                        server_traces.append(f"✅ Provisioning completed successfully")
                        break
                    elif provisioning_state == 'Failed':
                        error_msg = "Data asset provisioning failed"
                        server_traces.append(f"❌ {error_msg}")
                        raise Exception(error_msg)
                    
                    elapsed = int(time.time() - start_time)
                    server_traces.append(f"   Still provisioning... ({elapsed}s elapsed)")
                else:
                    server_traces.append(f"⚠️ Failed to check provisioning status")
                    break
            
            if provisioning_state not in ['Succeeded', 'Failed']:
                server_traces.append(f"⚠️ Provisioning did not complete within {max_wait_seconds}s")
        
        return asset_data
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error creating data asset: {str(e)}"
        server_traces.append(f"❌ {error_msg}")
        raise Exception(error_msg)
    except Exception as e:
        if "Failed to obtain management token" in str(e) or "Failed to create data asset" in str(e):
            raise
        error_msg = f"Error creating data asset: {str(e)}"
        server_traces.append(f"❌ {error_msg}")
        raise Exception(error_msg)


def ensure_data_asset(
    subscription_id: str,
    resource_group: str,
    data_container: str,
    asset_name: str,
    location: str,
    tenant_id: str,
    description: Optional[str] = None,
    path: Optional[str] = None,
    server_traces: Optional[List[str]] = None,
    api_version: str = "2025-07-01-preview"
) -> Tuple[bool, Dict[str, Any]]:
    """
    Ensure a data asset exists, creating it if necessary.
    
    This is the main function to use when you need a data asset to exist.
    It checks if the asset exists and creates it if not.
    
    Args:
        subscription_id: Azure subscription ID
        resource_group: Resource group name
        data_container: Data container name
        asset_name: Data asset name
        location: Azure region (e.g., "eastus")
        tenant_id: Azure AD tenant ID for authentication
        description: Optional description for the asset
        path: Optional storage path (defaults to "{asset_name}/")
        server_traces: Optional list to append trace messages
        api_version: Discovery API version
    
    Returns:
        Tuple of (created: bool, asset_data: Dict)
        created is True if the asset was created, False if it already existed
        asset_data contains the asset properties
        
    Raises:
        Exception: If checking or creation fails
    """
    if server_traces is None:
        server_traces = []
    
    # Check if asset exists
    exists, asset_data = check_data_asset_exists(
        subscription_id=subscription_id,
        resource_group=resource_group,
        data_container=data_container,
        asset_name=asset_name,
        tenant_id=tenant_id,
        server_traces=server_traces,
        api_version=api_version
    )
    
    if exists:
        return False, asset_data
    
    # Asset doesn't exist, create it
    asset_data = create_data_asset(
        subscription_id=subscription_id,
        resource_group=resource_group,
        data_container=data_container,
        asset_name=asset_name,
        location=location,
        tenant_id=tenant_id,
        description=description,
        path=path,
        server_traces=server_traces,
        api_version=api_version
    )
    
    return True, asset_data


def ensure_asset_from_resource_id(
    resource_id: str,
    location: str,
    tenant_id: str,
    description: Optional[str] = None,
    server_traces: Optional[List[str]] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Ensure a data asset exists given its full resource ID.
    
    This is a convenience function that parses the resource ID and calls ensure_data_asset.
    
    Args:
        resource_id: Full Azure resource ID for the data asset
        location: Azure region (e.g., "eastus")
        tenant_id: Azure AD tenant ID for authentication
        description: Optional description for the asset
        server_traces: Optional list to append trace messages
    
    Returns:
        Tuple of (created: bool, asset_data: Dict)
        
    Raises:
        ValueError: If resource ID format is invalid
        Exception: If checking or creation fails
    """
    if server_traces is None:
        server_traces = []
    
    # Parse the resource ID
    try:
        parsed = parse_data_asset_resource_id(resource_id)
    except ValueError as e:
        server_traces.append(f"❌ Invalid resource ID: {str(e)}")
        raise
    
    # Ensure the asset exists
    return ensure_data_asset(
        subscription_id=parsed['subscription_id'],
        resource_group=parsed['resource_group'],
        data_container=parsed['data_container'],
        asset_name=parsed['asset_name'],
        location=location,
        tenant_id=tenant_id,
        description=description,
        server_traces=server_traces
    )


def build_data_asset_resource_id(
    subscription_id: str,
    resource_group: str,
    data_container: str,
    asset_name: str
) -> str:
    """
    Build a full data asset resource ID.
    
    Args:
        subscription_id: Azure subscription ID
        resource_group: Resource group name
        data_container: Data container name
        asset_name: Data asset name
    
    Returns:
        Full resource ID string
    """
    return (
        f"/subscriptions/{subscription_id}"
        f"/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Discovery/datacontainers/{data_container}"
        f"/DataAssets/{asset_name}"
    )
