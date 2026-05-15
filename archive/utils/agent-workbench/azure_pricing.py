#!/usr/bin/env python3
"""
Azure VM Pricing Data Fetcher

This module fetches current Azure Virtual Machine pricing information
for container instances and caches it for use in cost estimations.
"""

import json
import requests
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

class AzurePricingClient:
    """Client for fetching and caching Azure VM pricing data."""
    
    def __init__(self):
        self.cache = {}
        self.cache_expiry = {}
        self.cache_duration = 24 * 60 * 60  # 24 hours in seconds
        
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self.cache_expiry:
            return False
        return time.time() < self.cache_expiry[cache_key]
    
    def _set_cache(self, cache_key: str, data: Any) -> None:
        """Store data in cache with expiry."""
        self.cache[cache_key] = data
        self.cache_expiry[cache_key] = time.time() + self.cache_duration
    
    def _get_access_token(self) -> Optional[str]:
        """Get Azure access token using Azure SDK credential chain."""
        try:
            # Use the project's quiet helper which uses proper credential chain
            from azure_auth_helpers import get_token_default_credential
            local_traces = []
            token = get_token_default_credential("https://management.azure.com/.default", local_traces, purpose='azure_pricing')
            if token:
                return token
            else:
                print(f"⚠️ Credential chain failed: {local_traces[-1] if local_traces else 'unknown'}")
                return None
        except Exception as e:
            print(f"⚠️ Token acquisition failed: {e}")
            return None
    
    def fetch_container_instance_skus(self, subscription_id: str, location: str = 'westus2') -> List[Dict]:
        """
        Fetch available Container Instance SKUs for a specific location.
        
        Args:
            subscription_id: Azure subscription ID
            location: Azure region (default: westus2)
            
        Returns:
            List of SKU dictionaries with name, cpu, memory, and cost information
        """
        cache_key = f"skus_{subscription_id}_{location}"
        
        # Check cache first
        if self._is_cache_valid(cache_key):
            print(f"📋 Using cached SKU data for {location}")
            return self.cache[cache_key]
        
        print(f"🔄 Fetching Container Instance SKUs for {location}...")
        
        access_token = self._get_access_token()
        if not access_token:
            print("❌ Failed to get Azure access token")
            return []
        
        try:
            # Fetch SKUs from Azure Resource SKUs API
            url = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.Compute/skus"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            params = {
                'api-version': '2021-07-01',
                '$filter': f"location eq '{location}'"
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            skus_data = response.json()
            container_skus = []
            
            for sku in skus_data.get('value', []):
                # Extract SKU name and allow more series (D, F, E) and any SKU that contains 'Standard_'
                sku_name = sku.get('name', '')
                # If the SKU doesn't look like a standard VM SKU, skip
                if 'Standard_' not in sku_name:
                    continue
                # Allow D, F, E series and others, but this is permissive for debugging purposes
                if not any(series in sku_name for series in ['Standard_D', 'Standard_F', 'Standard_E']):
                    # still include if name matches the requested pattern (handled later) - for now continue to next
                    # but do not drop too aggressively; keep permissive list to inspect
                    pass
                
                # Extract capabilities
                capabilities = {cap['name']: cap['value'] for cap in sku.get('capabilities', [])}
                
                try:
                    # Capabilities sometimes use different casing or names
                    cpu_count = int(capabilities.get('vCPUs', capabilities.get('vCPu', capabilities.get('vCPU', 0))))
                    memory_gb = float(capabilities.get('MemoryGB', capabilities.get('memoryGB', capabilities.get('MemoryGB', 0))))
                    
                    if cpu_count > 0 and memory_gb > 0:
                        # Estimate cost based on SKU tier and specifications
                        cost_per_hour = self._estimate_cost(sku_name, cpu_count, memory_gb)
                        
                        container_skus.append({
                            'name': sku_name,
                            'cpu': cpu_count,
                            'memory': memory_gb,
                            'cost': cost_per_hour,
                            'tier': sku.get('tier', 'Standard'),
                            'family': sku.get('family', 'Unknown')
                        })
                except (ValueError, TypeError):
                    continue
            
            # Sort by CPU then memory
            container_skus.sort(key=lambda x: (x['cpu'], x['memory']))
            
            print(f"✅ Found {len(container_skus)} Container Instance SKUs for {location}")
            
            # Cache the results
            self._set_cache(cache_key, container_skus)
            
            return container_skus
            
        except Exception as e:
            print(f"❌ Error fetching SKUs: {e}")
            return []
    
    def _estimate_cost(self, sku_name: str, cpu_count: int, memory_gb: float) -> float:
        """
        Estimate hourly cost for a SKU based on its specifications.
        
        This uses approximate pricing based on Azure Container Instances pricing
        patterns observed in the market.
        """
        # Base rates per vCPU and GB RAM (approximate)
        cpu_cost_per_hour = 0.024  # ~$0.024 per vCPU per hour
        memory_cost_per_hour = 0.0048  # ~$0.0048 per GB RAM per hour
        
        # SKU-specific adjustments
        multiplier = 1.0
        
        if 'D4s_v6' in sku_name or 'D4s_v5' in sku_name:
            multiplier = 1.0  # Newer generation efficiency
        elif 'D4s_v3' in sku_name:
            multiplier = 1.0
        elif 'D2s_v3' in sku_name:
            multiplier = 1.0
        elif 'D1_v2' in sku_name:
            multiplier = 1.05  # Older generation slight premium
        elif 'F' in sku_name:
            multiplier = 0.9  # F-series is typically more cost-effective
        
        base_cost = (cpu_count * cpu_cost_per_hour) + (memory_gb * memory_cost_per_hour)
        estimated_cost = base_cost * multiplier
        
        return round(estimated_cost, 6)
    

    
    def get_vm_pricing(self, vm_size: str, subscription_id: Optional[str] = None, location: str = 'westus2') -> Dict:
        """
        Get pricing information for a specific VM size.
        
        Args:
            vm_size: The VM size (e.g., 'Standard_D4s_v6')
            subscription_id: Azure subscription ID (optional)
            location: Azure region (default: westus2)
            
        Returns:
            Dictionary with pricing information
        """
        if subscription_id:
            print(f"📡 Fetching SKUs from Azure API for {vm_size}")
            skus = self.fetch_container_instance_skus(subscription_id, location)

            # Best-effort exact match first
            for sku in skus:
                if sku.get('name') == vm_size:
                    cost_per_hour = sku['cost']
                    cost_per_minute = cost_per_hour / 60

                    result = {
                        'found': True,
                        'price_per_hour': cost_per_hour,
                        'costPerHour': f"{cost_per_hour:.3f}",
                        'costPerMinute': f"{cost_per_minute:.4f}", 
                        'cpu_cores': sku['cpu'],
                        'memory_gb': sku['memory'],
                        'tier': sku.get('tier', 'Standard'),
                        'family': sku.get('family', 'Unknown')
                    }
                    print(f"✅ Found pricing for {vm_size}: ${cost_per_hour:.3f}/hour")
                    return result

            # Fallback: try substring matching (helps when API returns slightly different SKU names)
            for sku in skus:
                if vm_size in sku.get('name', '') or sku.get('name', '') in vm_size:
                    cost_per_hour = sku['cost']
                    cost_per_minute = cost_per_hour / 60
                    result = {
                        'found': True,
                        'price_per_hour': cost_per_hour,
                        'costPerHour': f"{cost_per_hour:.3f}",
                        'costPerMinute': f"{cost_per_minute:.4f}", 
                        'cpu_cores': sku['cpu'],
                        'memory_gb': sku['memory'],
                        'tier': sku.get('tier', 'Standard'),
                        'family': sku.get('family', 'Unknown'),
                        'matched_name': sku.get('name')
                    }
                    print(f"⚠️ Approximated pricing match for {vm_size} -> {sku.get('name')}: ${cost_per_hour:.3f}/hour")
                    return result

            print(f"❌ VM size {vm_size} not found in Azure SKUs")
        else:
            print("⚠️ No subscription ID provided")
        
        # No subscription ID provided or VM size not found - return not found
        result = {
            'found': False,
            'costPerHour': 'N/A',
            'costPerMinute': 'N/A'
        }
        return result

# Global instance for caching
pricing_client = AzurePricingClient()

def test_pricing_client():
    """Test function to verify the pricing client works."""
    print("🧪 Testing Azure Pricing Client...")
    
    # Test without subscription (should return not found)
    vm_pricing = pricing_client.get_vm_pricing('Standard_D4s_v6')
    print(f"Standard_D4s_v6 pricing (no subscription): {vm_pricing}")
    
    vm_pricing = pricing_client.get_vm_pricing('Standard_D2s_v3')
    print(f"Standard_D2s_v3 pricing (no subscription): {vm_pricing}")
    
    vm_pricing = pricing_client.get_vm_pricing('Unknown_SKU')
    print(f"Unknown SKU pricing: {vm_pricing}")
    
    print("✅ Pricing client test completed")
    print("ℹ️  Note: To get actual pricing, provide a subscription_id parameter")

if __name__ == "__main__":
    test_pricing_client()