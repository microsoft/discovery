"""
Discovery Configuration Manager
Handles persistence and retrieval of Discovery publishing configuration
"""

import json
import os
import time
import threading
from typing import Dict, Any, Optional, List
from pathlib import Path
from profile_manager import ProfileManager

class DiscoveryConfigManager:
    """Manages Discovery publishing configuration with persistence"""
    
    def __init__(self, config_file: str = "discovery_config.json", verbose: bool = False):
        self.config_file = Path(config_file)
        self.debug_enabled = verbose  # Control detailed tracing
        if self.debug_enabled:
            self._log_trace(f"🔧 DiscoveryConfigManager initialized with config file: {self.config_file.absolute()}")
        
        # Initialize ProfileManager
        self.profile_manager = ProfileManager(config_file)
        if self.debug_enabled:
            active_profile = self.profile_manager.get_active_profile_name()
            self._log_trace(f"👤 ProfileManager initialized - Active profile: {active_profile}")
        
        self.default_config = {
            "azure": {
                "subscription_id": "",
                # Optional friendly subscription name (e.g. "Contoso - Prod")
                "subscription_name": "",
                "resource_group": "",
                "location": "",
                # Azure Container Registry hostname (e.g. "contoso.azurecr.io")
                "acr_name": "",
                # Optional ACR token authentication
                "acr_token_name": "",
                "acr_token_password": ""
            },
            "azure_openai": {
                "endpoint_url": "",
                "deployment_name": "gpt-4o",
                "auth_type": "api_key",
                "api_key": "",
                "api_version": "2024-02-15-preview",
                "azure_ad": {
                    "subscription_id": "",
                    "resource_group": "",
                    "tenant_id": None,
                    "scope": "https://cognitiveservices.azure.com/.default"
                }
            },
            "conversation": {
                "max_tokens": 64000,
                "target_tokens": 48000,
                "max_retries": 3,
                "max_output_tokens": 16384,
                "safety_fraction": 0.85,
                "strategy": "hybrid",
                "temperature": 0.1
            },
            "directories": {
                "tool_agents_dir": "../../",
                "kb_agents_dir": "../../",
                "entry_agents_dir": "../../"
            },
            "llm": {
                "endpoint": "azureml://registries/azure-openai/models/gpt-4o/versions/2024-11-20"
            },
            "discovery_assistant": {
                "docs_mode": "retrieval",
                "docs_top_k": 12,
                "docs_context_fraction": 0.25,
                "chunk_token_target": 800,
                "chunk_token_overlap": 150,
                "debug_retrieval": False,
                "answer_detail": "detailed",
                "bm25_candidates": 64,
                "use_llm_rerank": True,
                "llm_rerank_candidates": 20,
                "use_embeddings_rerank": False,
                "embeddings_deployment_name": "",
                "embeddings_api_version": "",
                "hybrid_weight_bm25": 0.55,
                "hybrid_weight_embedding": 0.45,
                "max_output_tokens_override": 0,
                "refresh_docs_on_startup": True,
                "refresh_docs_max_age_days": 7
            },
            "template_files": {
                "PlannerAgent": "sample-agents/PlannerAgent.yaml",
                "RouterAgent": "sample-agents/RouterAgent.yaml",
                "SummarizerAgent": "sample-agents/SummarizerAgent.yaml",
                "WorkflowAgent": "sample-agents/WorkflowAgent.yaml",
                "ToolAgent": "sample-agents/GromacsAgent.yaml",
                "KnowledgeBaseAgent": "sample-agents/KnowledgeBaseAgent.yaml",
                "ToolDefinition": "sample-agents/GromacsToolDefinition.yaml",
                "AgentDefinitionSchema": "yaml-schemas/agent_definition_schema.json",
                "ToolDefinitionSchema": "yaml-schemas/tool_definition_schema.json",
                "WorkflowDefinitionSchema": "yaml-schemas/workflow_definition_schema.json"
            }
        }
        # Default parallel/agent-workbench runtime settings
        self.default_config.setdefault("parallel", {
            "max_concurrent_requests": 10,
            "use_async_by_default": True,
            "timeout_seconds": 120,
            "fallback_to_threading": True
        })
        if self.debug_enabled:
            self._log_trace(f"📋 Default configuration template loaded with {len(self.default_config)} sections")
        
    def _log_trace(self, message: str):
        """Log detailed trace messages with timestamp"""
        if self.debug_enabled:
            # Get current time with microseconds
            now = time.time()
            timestamp = time.strftime("%H:%M:%S", time.localtime(now))
            microseconds = int((now % 1) * 1000)  # Get milliseconds
            full_timestamp = f"{timestamp}.{microseconds:03d}"
            print(f"[{full_timestamp}] DISCOVERY_CONFIG: {message}")
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file (active profile) or return defaults"""
        self._log_trace(f"📂 Starting config load from: {self.config_file}")
        start_time = time.time()
        
        try:
            # Get active profile from ProfileManager
            active_profile = self.profile_manager.get_active_profile()
            active_profile_name = self.profile_manager.get_active_profile_name()
            
            self._log_trace(f"� Loading active profile: {active_profile_name}")
            self._log_trace(f"🔍 Profile config with keys: {list(active_profile.keys())}")
            
            # Log details of each section
            for section, content in active_profile.items():
                if isinstance(content, dict):
                    self._log_trace(f"  📁 Section '{section}': {len(content)} properties")
                else:
                    self._log_trace(f"  📄 Section '{section}': {type(content).__name__}")
            
            # Merge with defaults to ensure all keys exist
            self._log_trace("🔄 Merging profile config with defaults...")
            merged_config = self._merge_with_defaults(active_profile)

            load_time = (time.time() - start_time) * 1000
            self._log_trace(f"✅ Config loaded successfully in {load_time:.2f}ms")
            return merged_config
            
        except Exception as e:
            load_time = (time.time() - start_time) * 1000
            self._log_trace(f"❌ Error loading config after {load_time:.2f}ms: {e}")
            print(f"Warning: Could not load config from {self.config_file}: {e}")
            return self.default_config.copy()
    
    def save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration to the active profile"""
        self._log_trace(f"💾 Starting config save to: {self.config_file}")
        start_time = time.time()
        
        try:
            active_profile_name = self.profile_manager.get_active_profile_name()
            self._log_trace(f"� Saving to active profile: {active_profile_name}")
            
            # Log what we're about to save
            self._log_trace(f"📝 Saving config with {len(config)} sections:")
            for section, content in config.items():
                if isinstance(content, dict):
                    self._log_trace(f"  📁 Section '{section}': {len(content)} properties")
                else:
                    self._log_trace(f"  📄 Section '{section}': {type(content).__name__}")
            
            # Update the active profile
            result = self.profile_manager.update_profile(active_profile_name, config)
            
            if result['success']:
                save_time = (time.time() - start_time) * 1000
                self._log_trace(f"✅ Config saved successfully in {save_time:.2f}ms")
                return True
            else:
                self._log_trace(f"❌ Failed to save config: {result.get('error', 'Unknown error')}")
                return False
                
        except Exception as e:
            save_time = (time.time() - start_time) * 1000
            self._log_trace(f"❌ Error saving config after {save_time:.2f}ms: {e}")
            print(f"Error: Could not save config: {e}")
            return False

            file_size = self.config_file.stat().st_size
            save_time = (time.time() - start_time) * 1000
            self._log_trace(f"✅ Config saved successfully in {save_time:.2f}ms (size: {file_size} bytes)")
            return True
        except Exception as e:
            save_time = (time.time() - start_time) * 1000
            self._log_trace(f"❌ Error saving config after {save_time:.2f}ms: {e}")
            print(f"Error: Could not save config to {self.config_file}: {e}")
            return False
    
    def update_azure_config(self, subscription_id: str, resource_group: str, location: str, acr_name: Optional[str] = None, acr_token_name: Optional[str] = None, acr_token_password: Optional[str] = None, discovery_supercomputer: Optional[str] = None, tenant_id: Optional[str] = None, subscription_name: Optional[str] = None) -> bool:
        """Update Azure configuration and save.

        Note: subscription_name is treated as display-only metadata and is no longer
        persisted to discovery_config.json. The UI maintains friendly names in a
        local cache instead.
        """
        self._log_trace(f"🔧 Updating Azure configuration...")
        self._log_trace(f"  Subscription ID: {subscription_id[:8]}{'...' if len(subscription_id) > 8 else ''}")
        self._log_trace(f"  Resource Group: {resource_group}")
        self._log_trace(f"  Location: {location}")
        if acr_name is not None:
            self._log_trace(f"  ACR Name: {acr_name}")
        if acr_token_name is not None:
            self._log_trace(f"  ACR Token Name: {acr_token_name}")
        if acr_token_password is not None:
            self._log_trace(f"  ACR Token Password: {'*' * min(len(acr_token_password), 8)}")
        if discovery_supercomputer is not None:
            self._log_trace(f"  Discovery Supercomputer: {discovery_supercomputer}")
        if tenant_id is not None:
            self._log_trace(f"  Tenant ID: {tenant_id[:8]}{'...' if len(tenant_id) > 8 else ''}")

        config = self.load_config()
        # Preserve any existing azure values when updating
        azure_section = config.get("azure", {}).copy()
        azure_section.update({
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "location": location
        })
        # Do not persist subscription_name; remove it if present so it does not linger in config.
        azure_section.pop("subscription_name", None)
        if acr_name is not None:
            azure_section["acr_name"] = acr_name
        if acr_token_name is not None:
            azure_section["acr_token_name"] = acr_token_name
        if acr_token_password is not None:
            azure_section["acr_token_password"] = acr_token_password
        if discovery_supercomputer is not None:
            azure_section["discovery_supercomputer"] = discovery_supercomputer
        if tenant_id is not None:
            azure_section["tenant_id"] = tenant_id

        config["azure"] = azure_section

        result = self.save_config(config)
        if result:
            self._log_trace("✅ Azure configuration updated successfully")
        else:
            self._log_trace("❌ Failed to update Azure configuration")
        return result
    
    def get_azure_config(self) -> Dict[str, str]:
        """Get Azure configuration"""
        self._log_trace("🔧 Retrieving Azure configuration...")
        config = self.load_config()
        azure_config = config.get("azure", self.default_config["azure"])
        
        # Log current Azure settings (with privacy protection)
        subscription_masked = azure_config.get("subscription_id", "")
        if subscription_masked:
            subscription_masked = subscription_masked[:8] + "..." if len(subscription_masked) > 8 else subscription_masked
        
        self._log_trace(f"  Subscription ID: {subscription_masked if subscription_masked else 'NOT SET'}")
        self._log_trace(f"  Resource Group: {azure_config.get('resource_group', 'NOT SET')}")
        self._log_trace(f"  Location: {azure_config.get('location', 'NOT SET')}")
        # Ensure optional keys exist for backward compatibility
        if 'subscription_name' not in azure_config:
            azure_config['subscription_name'] = ''
        if 'acr_name' not in azure_config:
            azure_config['acr_name'] = ''
        if 'acr_token_name' not in azure_config:
            azure_config['acr_token_name'] = ''
        if 'acr_token_password' not in azure_config:
            azure_config['acr_token_password'] = ''
        if 'tenant_id' not in azure_config:
            azure_config['tenant_id'] = ''
        
        return azure_config
    
    def get_acr_name(self) -> str:
        """Get the ACR name from the active profile configuration"""
        azure_config = self.get_azure_config()
        return azure_config.get('acr_name', '')
    
    def replace_acr_placeholder(self, acr_url: str) -> str:
        """Replace {name} placeholder in ACR URL with the configured ACR name.
        
        Example:
            {name}.azurecr.io/bindingdb-image:latest -> fabrice.azurecr.io/bindingdb-image:latest
            
        Args:
            acr_url: ACR URL potentially containing {name} placeholder
            
        Returns:
            ACR URL with {name} replaced by the configured acr_name
        """
        if not acr_url or '{name}' not in acr_url:
            return acr_url
        
        acr_name = self.get_acr_name()
        if not acr_name:
            self._log_trace("⚠️ Warning: ACR URL contains {name} placeholder but acr_name is not configured")
            return acr_url
        
        replaced_url = acr_url.replace('{name}', acr_name)
        self._log_trace(f"🔄 Replaced ACR placeholder: {acr_url} -> {replaced_url}")
        return replaced_url
    
    def process_tool_definition_acr(self, tool_definition: Dict[str, Any]) -> Dict[str, Any]:
        """Process tool definition to replace {name} placeholders in ACR image URLs.
        
        Args:
            tool_definition: Tool definition dictionary
            
        Returns:
            Modified tool definition with ACR placeholders replaced
        """
        if not isinstance(tool_definition, dict):
            return tool_definition
        
        # Deep copy to avoid modifying the original
        import copy
        processed_def = copy.deepcopy(tool_definition)
        
        # Process top-level acr_image field (used by frontend modal)
        if 'acr_image' in processed_def and processed_def['acr_image']:
            processed_def['acr_image'] = self.replace_acr_placeholder(processed_def['acr_image'])
        
        # Process infra section
        if 'infra' in processed_def and isinstance(processed_def['infra'], list):
            for infra_item in processed_def['infra']:
                if isinstance(infra_item, dict) and 'image' in infra_item:
                    image_config = infra_item['image']
                    if isinstance(image_config, dict) and 'acr' in image_config:
                        original_acr = image_config['acr']
                        image_config['acr'] = self.replace_acr_placeholder(original_acr)
        
        return processed_def
    
    def update_preferences(self, preferences: Dict[str, Any]) -> bool:
        """Update preferences and save"""
        config = self.load_config()
        config["preferences"].update(preferences)
        return self.save_config(config)
    
    def get_preferences(self) -> Dict[str, Any]:
        """Get preferences"""
        config = self.load_config()
        return config.get("preferences", {})
    
    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration"""
        config = self.load_config()
        return config.get("llm", self.default_config["llm"])

    def get_parallel_config(self) -> Dict[str, Any]:
        """Get parallel/processing configuration for agent-workbench runtime"""
        config = self.load_config()
        return config.get('parallel', self.default_config.get('parallel', {}))

    def update_parallel_config(self, max_concurrent_requests: Optional[int] = None, use_async_by_default: Optional[bool] = None, timeout_seconds: Optional[int] = None, fallback_to_threading: Optional[bool] = None) -> bool:
        """Update parallel processing configuration and save"""
        try:
            cfg = self.load_config()
            if 'parallel' not in cfg:
                cfg['parallel'] = {}

            if max_concurrent_requests is not None:
                cfg['parallel']['max_concurrent_requests'] = int(max_concurrent_requests)
            if use_async_by_default is not None:
                cfg['parallel']['use_async_by_default'] = bool(use_async_by_default)
            if timeout_seconds is not None:
                cfg['parallel']['timeout_seconds'] = int(timeout_seconds)
            if fallback_to_threading is not None:
                cfg['parallel']['fallback_to_threading'] = bool(fallback_to_threading)

            return self.save_config(cfg)
        except Exception as e:
            self._log_trace(f"\u274c Error updating parallel config: {e}")
            return False
    
    def get_llm_endpoint(self) -> str:
        """
        Get LLM endpoint for GENERATED AGENT YAML FILES (not for testbed runtime).
        
        This endpoint is embedded in the 'model:' field of generated agent YAML files
        and defines what model the agents will use when deployed and running.
        
        This is DIFFERENT from the runtime LLM configuration used by the testbed itself,
        which comes from environment variables (ENDPOINT_URL, DEPLOYMENT_NAME, etc.)
        and is used for generating agent content via LLM API calls.
        
        Returns:
            str: Model endpoint like "azureml://registries/azure-openai/models/gpt-4o/versions/2024-11-20"
        """
        llm_config = self.get_llm_config()
        return llm_config.get("endpoint", self.default_config["llm"]["endpoint"])
    
    def get_template_files(self) -> Dict[str, str]:
        """Get template file paths for LLM component generation"""
        self._log_trace("🎯 Retrieving template files configuration...")
        start_time = time.time()
        
        config = self.load_config()
        template_files = config.get("template_files", self.default_config["template_files"])
        
        self._log_trace(f"📋 Template files found: {len(template_files)} entries")
        for component_type, file_path in template_files.items():
            # Check if file exists
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                self._log_trace(f"  ✅ {component_type}: {file_path} (size: {file_size} bytes)")
            else:
                self._log_trace(f"  ❌ {component_type}: {file_path} (FILE NOT FOUND)")
        
        load_time = (time.time() - start_time) * 1000
        self._log_trace(f"⏱️ Template files retrieved in {load_time:.2f}ms")
        return template_files
    
    def update_llm_config(self, endpoint: str) -> bool:
        """Update LLM configuration and save"""
        self._log_trace(f"🤖 Updating LLM configuration...")
        self._log_trace(f"  Endpoint: {endpoint}")
        
        config = self.load_config()
        if "llm" not in config:
            config["llm"] = {}
            self._log_trace("  Created new LLM config section")
        
        config["llm"]["endpoint"] = endpoint
        
        result = self.save_config(config)
        if result:
            self._log_trace("✅ LLM configuration updated successfully")
        else:
            self._log_trace("❌ Failed to update LLM configuration")
        return result
    
    def _merge_with_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge loaded config with defaults to ensure all keys exist"""
        self._log_trace("🔄 Starting config merge with defaults...")
        start_time = time.time()
        
        merged = self.default_config.copy()
        self._log_trace(f"📋 Base config copied with {len(merged)} sections")
        
        # Merge azure config
        if "azure" in config:
            before_count = len(merged["azure"])
            merged["azure"].update(config["azure"])
            after_count = len(merged["azure"])
            self._log_trace(f"  🔧 Azure config merged: {before_count} → {after_count} properties")
            self._log_trace(f"    Subscription ID: {'SET' if merged['azure'].get('subscription_id') else 'EMPTY'}")
            self._log_trace(f"    Resource Group: {'SET' if merged['azure'].get('resource_group') else 'EMPTY'}")
            self._log_trace(f"    Location: {'SET' if merged['azure'].get('location') else 'EMPTY'}")
        else:
            self._log_trace("  ⚠️ No azure config section in loaded file")
        
        # Merge preferences
        if "preferences" in config:
            before_count = len(merged["preferences"])
            merged["preferences"].update(config["preferences"])
            after_count = len(merged["preferences"])
            self._log_trace(f"  ⚙️ Preferences merged: {before_count} → {after_count} properties")
            for key, value in merged["preferences"].items():
                self._log_trace(f"    {key}: {value}")
        else:
            self._log_trace("  ⚠️ No preferences config section in loaded file")
        
        # Merge llm config
        if "llm" in config:
            before_count = len(merged["llm"])
            merged["llm"].update(config["llm"])
            after_count = len(merged["llm"])
            self._log_trace(f"  🤖 LLM config merged: {before_count} → {after_count} properties")
            self._log_trace(f"    Endpoint: {merged['llm'].get('endpoint', 'NOT SET')}")
        else:
            self._log_trace("  ⚠️ No llm config section in loaded file")

        # Merge azure_openai config
        if "azure_openai" in config:
            before_count = len(merged["azure_openai"])
            merged["azure_openai"].update(config["azure_openai"])
            after_count = len(merged["azure_openai"])
            self._log_trace(f"  🔑 Azure OpenAI config merged: {before_count} → {after_count} properties")
            self._log_trace(f"    Endpoint URL: {'SET' if merged['azure_openai'].get('endpoint_url') else 'EMPTY'}")
            self._log_trace(f"    Deployment: {'SET' if merged['azure_openai'].get('deployment_name') else 'EMPTY'}")
            self._log_trace(f"    API Key: {'SET' if merged['azure_openai'].get('api_key') else 'EMPTY'}")
        else:
            self._log_trace("  ⚠️ No azure_openai config section in loaded file")

        # Merge conversation config
        if "conversation" in config:
            before_count = len(merged["conversation"])
            merged["conversation"].update(config["conversation"])
            after_count = len(merged["conversation"])
            self._log_trace(f"  💬 Conversation config merged: {before_count} → {after_count} properties")
            self._log_trace(f"    Max Tokens: {merged['conversation'].get('max_tokens', 'NOT SET')}")
            self._log_trace(f"    Strategy: {merged['conversation'].get('strategy', 'NOT SET')}")
        else:
            self._log_trace("  ⚠️ No conversation config section in loaded file")

        # Merge directories config
        if "directories" in config:
            before_count = len(merged["directories"])
            merged["directories"].update(config["directories"])
            after_count = len(merged["directories"])
            self._log_trace(f"  📁 Directories config merged: {before_count} → {after_count} properties")
            for key, value in merged["directories"].items():
                self._log_trace(f"    {key}: {value}")
        else:
            self._log_trace("  ⚠️ No directories config section in loaded file")

        # Merge discovery assistant settings
        if "discovery_assistant" in config and isinstance(config.get("discovery_assistant"), dict):
            before_count = len(merged.get("discovery_assistant", {}) or {})
            if "discovery_assistant" not in merged or not isinstance(merged.get("discovery_assistant"), dict):
                merged["discovery_assistant"] = {}
            merged["discovery_assistant"].update(config["discovery_assistant"])
            after_count = len(merged["discovery_assistant"])
            self._log_trace(f"  🔎 Discovery assistant merged: {before_count} → {after_count} properties")
            self._log_trace(f"    docs_mode: {merged['discovery_assistant'].get('docs_mode', 'NOT SET')}")
            self._log_trace(f"    docs_top_k: {merged['discovery_assistant'].get('docs_top_k', 'NOT SET')}")
            self._log_trace(f"    bm25_candidates: {merged['discovery_assistant'].get('bm25_candidates', 'NOT SET')}")
        else:
            self._log_trace("  ⚠️ No discovery_assistant config section in loaded file")
        
        # Merge azure_compute config
        if "azure_compute" in config:
            merged["azure_compute"] = config["azure_compute"]
            self._log_trace(f"  🔧 Azure Compute config merged")
            # execution_target removed from config merging logs
            self._log_trace(f"    SKU: {merged['azure_compute'].get('sku', 'NOT SET')}")
            self._log_trace(f"    Auto Cleanup: {merged['azure_compute'].get('auto_cleanup', 'NOT SET')}")
        else:
            self._log_trace("  ⚠️ No azure_compute config section in loaded file")
        
        # Merge template_files config
        if "template_files" in config:
            before_count = len(merged["template_files"])
            merged["template_files"].update(config["template_files"])
            after_count = len(merged["template_files"])
            self._log_trace(f"  🎯 Template files merged: {before_count} → {after_count} entries")
            for component_type, file_path in merged["template_files"].items():
                self._log_trace(f"    {component_type}: {file_path}")
        else:
            self._log_trace("  ⚠️ No template_files config section in loaded file")
        
        merge_time = (time.time() - start_time) * 1000
        self._log_trace(f"✅ Config merge completed in {merge_time:.2f}ms")
        return merged
        
    def set_debug_tracing(self, enabled: bool = True):
        """Enable or disable detailed debug tracing"""
        self.debug_enabled = enabled
        self._log_trace(f"🔍 Debug tracing {'ENABLED' if enabled else 'DISABLED'}")
        
    def get_config_file_info(self) -> Dict[str, Any]:
        """Get information about the configuration file"""
        self._log_trace("📊 Getting config file information...")
        
        info = {
            "file_path": str(self.config_file.absolute()),
            "exists": self.config_file.exists(),
            "size_bytes": 0,
            "last_modified": None,
            "readable": False,
            "writable": False
        }
        
        if self.config_file.exists():
            try:
                stat = self.config_file.stat()
                info.update({
                    "size_bytes": stat.st_size,
                    "last_modified": time.ctime(stat.st_mtime),
                    "readable": os.access(self.config_file, os.R_OK),
                    "writable": os.access(self.config_file, os.W_OK)
                })
            except Exception as e:
                self._log_trace(f"❌ Error getting file stats: {e}")
        
        self._log_trace(f"📊 File info: exists={info['exists']}, size={info['size_bytes']} bytes")
        return info
        
    def validate_template_files(self) -> Dict[str, Any]:
        """Validate that all template files exist and are readable"""
        self._log_trace("🔍 Validating template files...")
        start_time = time.time()
        
        template_files = self.get_template_files()
        validation_results = {
            "valid": True,
            "total_files": len(template_files),
            "existing_files": 0,
            "missing_files": 0,
            "details": {}
        }
        
        for component_type, file_path in template_files.items():
            file_info = {
                "path": file_path,
                "exists": False,
                "readable": False,
                "size_bytes": 0,
                "error": None
            }
            
            try:
                if os.path.exists(file_path):
                    file_info["exists"] = True
                    file_info["readable"] = os.access(file_path, os.R_OK)
                    file_info["size_bytes"] = os.path.getsize(file_path)
                    validation_results["existing_files"] += 1
                    self._log_trace(f"  ✅ {component_type}: {file_path} ({file_info['size_bytes']} bytes)")
                else:
                    validation_results["missing_files"] += 1
                    validation_results["valid"] = False
                    self._log_trace(f"  ❌ {component_type}: {file_path} (NOT FOUND)")
                    
            except Exception as e:
                file_info["error"] = str(e)
                validation_results["valid"] = False
                self._log_trace(f"  ❌ {component_type}: Error checking {file_path} - {e}")
            
            validation_results["details"][component_type] = file_info
        
        validation_time = (time.time() - start_time) * 1000
        self._log_trace(f"🔍 Template validation completed in {validation_time:.2f}ms")
        self._log_trace(f"📊 Results: {validation_results['existing_files']}/{validation_results['total_files']} files found, valid={validation_results['valid']}")
        
        return validation_results

    # ===== NEW CONFIGURATION ACCESS METHODS =====
    
    def get_azure_openai_config(self) -> Dict[str, Any]:
        """Get Azure OpenAI configuration"""
        config = self.load_config()
        return config.get('azure_openai', self.default_config['azure_openai'])
    
    def get_conversation_config(self) -> Dict[str, Any]:
        """Get conversation management configuration"""
        config = self.load_config()
        return config.get('conversation', self.default_config['conversation'])
    
    def get_directories_config(self) -> Dict[str, Any]:
        """Get directories configuration"""
        config = self.load_config()
        return config.get('directories', self.default_config['directories'])
    
    def update_azure_openai_config(self, endpoint_url: str, deployment_name: str, api_key: str, api_version: Optional[str] = None) -> bool:
        """Update Azure OpenAI configuration"""
        try:
            config = self.load_config()
            if 'azure_openai' not in config:
                config['azure_openai'] = {}
            
            config['azure_openai']['endpoint_url'] = endpoint_url
            config['azure_openai']['deployment_name'] = deployment_name
            config['azure_openai']['api_key'] = api_key
            if api_version:
                config['azure_openai']['api_version'] = api_version
            
            return self.save_config(config)
        except Exception as e:
            self._log_trace(f"❌ Error updating Azure OpenAI config: {e}")
            return False
    
    def update_conversation_config(self, max_tokens: Optional[int] = None, target_tokens: Optional[int] = None, 
                                 max_retries: Optional[int] = None, max_output_tokens: Optional[int] = None,
                                 strategy: Optional[str] = None, temperature: Optional[float] = None) -> bool:
        """Update conversation management configuration"""
        try:
            config = self.load_config()
            if 'conversation' not in config:
                config['conversation'] = {}
            
            if max_tokens is not None:
                config['conversation']['max_tokens'] = max_tokens
            if target_tokens is not None:
                config['conversation']['target_tokens'] = target_tokens
            if max_retries is not None:
                config['conversation']['max_retries'] = max_retries
            if max_output_tokens is not None:
                config['conversation']['max_output_tokens'] = max_output_tokens
            if strategy is not None:
                config['conversation']['strategy'] = strategy
            if temperature is not None:
                config['conversation']['temperature'] = temperature
            
            return self.save_config(config)
        except Exception as e:
            self._log_trace(f"❌ Error updating conversation config: {e}")
            return False
    
    def update_directories_config(self, discovery_tool_output_dir: Optional[str] = None, kb_agent_output_dir: Optional[str] = None, entry_agents_dir: Optional[str] = None) -> bool:
        """Update directories configuration"""
        try:
            config = self.load_config()
            if 'directories' not in config:
                config['directories'] = {}
            
            if discovery_tool_output_dir is not None:
                config['directories']['tool_agents_dir'] = discovery_tool_output_dir
            if kb_agent_output_dir is not None:
                config['directories']['kb_agents_dir'] = kb_agent_output_dir
            if entry_agents_dir is not None:
                config['directories']['entry_agents_dir'] = entry_agents_dir
            
            return self.save_config(config)
        except Exception as e:
            self._log_trace(f"❌ Error updating directories config: {e}")
            return False
    
    def update_azure_compute_config(self, auto_cleanup: Optional[bool] = None, use_script_upload: Optional[bool] = None, storage_account: Optional[str] = None, discovery_storage: Optional[str] = None, discovery_supercomputer: Optional[str] = None, workspace: Optional[str] = None, project: Optional[str] = None, inputs_asset: Optional[str] = None, outputs_asset: Optional[str] = None, data_container: Optional[str] = None, optimization_preference: Optional[str] = None, nodepool_cache_ttl_hours: Optional[int] = None) -> bool:
        """Update Azure Compute configuration

        Args:
            auto_cleanup: Enable auto-cleanup of storage files
            use_script_upload: Upload scripts to storage before execution
            storage_account: Azure storage account name
            discovery_storage: Discovery storage resource ID
            discovery_supercomputer: Name of the Discovery supercomputer
            workspace: Discovery workspace name
            project: Project name
            inputs_asset: Input data asset path
            outputs_asset: Output data asset path
            data_container: Data container name
            optimization_preference: Nodepool optimization preference ('performance', 'cost', 'balanced')
            nodepool_cache_ttl_hours: Cache TTL for nodepool data in hours (default: 24)

        Returns:
            True if config saved successfully, False otherwise
        """
        try:
            config = self.load_config()
            if 'azure_compute' not in config:
                config['azure_compute'] = {}

            # execution_target removed: no-op for backward compatibility
            if auto_cleanup is not None:
                config['azure_compute']['auto_cleanup'] = auto_cleanup
            if use_script_upload is not None:
                config['azure_compute']['use_script_upload'] = use_script_upload
            if storage_account is not None:
                config['azure_compute']['storage_account'] = storage_account
            if discovery_storage is not None:
                config['azure_compute']['discovery_storage'] = discovery_storage
            if discovery_supercomputer is not None:
                config['azure_compute']['discovery_supercomputer'] = discovery_supercomputer
            if inputs_asset is not None:
                config['azure_compute']['inputs_asset'] = inputs_asset
            if outputs_asset is not None:
                config['azure_compute']['outputs_asset'] = outputs_asset
            if data_container is not None:
                config['azure_compute']['data_container'] = data_container
            if workspace is not None:
                config['azure_compute']['workspace'] = workspace
            if project is not None:
                config['azure_compute']['project'] = project

            # Nodepool optimization settings
            if optimization_preference is not None:
                if optimization_preference in ['performance', 'cost', 'balanced']:
                    config['azure_compute']['optimization_preference'] = optimization_preference
                else:
                    self._log_trace(f"⚠️ Invalid optimization_preference: {optimization_preference}. Must be 'performance', 'cost', or 'balanced'")
            if nodepool_cache_ttl_hours is not None:
                if isinstance(nodepool_cache_ttl_hours, int) and nodepool_cache_ttl_hours > 0:
                    config['azure_compute']['nodepool_cache_ttl_hours'] = nodepool_cache_ttl_hours
                else:
                    self._log_trace(f"⚠️ Invalid nodepool_cache_ttl_hours: {nodepool_cache_ttl_hours}. Must be a positive integer")

            self._log_trace(f"✅ Updated Azure Compute config: cleanup={auto_cleanup}, use_script_upload={use_script_upload}, storage={storage_account}, discovery_storage={discovery_storage}, supercomputer={discovery_supercomputer}, workspace={workspace}, project={project}, optimization_preference={optimization_preference}")
            return self.save_config(config)
        except Exception as e:
            self._log_trace(f"❌ Error updating Azure Compute config: {e}")
            return False
    
    def ensure_workbench_assets(self, server_traces: Optional[list] = None) -> Dict[str, Any]:
        """
        Ensure workbench data assets exist, creating them if necessary.
        
        This method checks if inputs_asset and outputs_asset are configured.
        If not, it creates default 'workbench' assets automatically.
        
        Args:
            server_traces: Optional list to append trace messages
        
        Returns:
            Dict with keys: success, created_inputs, created_outputs, inputs_asset, outputs_asset, error
        """
        if server_traces is None:
            server_traces = []
        
        try:
            from asset_manager import (
                ensure_data_asset,
                build_data_asset_resource_id,
                generate_default_asset_name
            )
        except ImportError as e:
            error_msg = f"Failed to import asset_manager: {str(e)}"
            server_traces.append(f"❌ {error_msg}")
            return {'success': False, 'error': error_msg}
        
        try:
            config = self.load_config()
            azure_config = config.get('azure', {})
            azure_compute = config.get('azure_compute', {})
            
            # Get required parameters
            subscription_id = azure_config.get('subscription_id', '').strip()
            resource_group = azure_config.get('resource_group', '').strip()
            location = azure_config.get('location', '').strip()
            tenant_id = azure_config.get('tenant_id', '').strip()
            data_container = azure_compute.get('data_container', '').strip()
            
            # Validate required parameters
            if not all([subscription_id, resource_group, location, tenant_id, data_container]):
                missing = []
                if not subscription_id: missing.append('subscription_id')
                if not resource_group: missing.append('resource_group')
                if not location: missing.append('location')
                if not tenant_id: missing.append('tenant_id')
                if not data_container: missing.append('data_container')
                
                error_msg = f"Missing required configuration: {', '.join(missing)}"
                server_traces.append(f"⚠️ {error_msg}")
                return {'success': False, 'error': error_msg}
            
            # Get current asset configuration
            inputs_asset = azure_compute.get('inputs_asset', '').strip()
            outputs_asset = azure_compute.get('outputs_asset', '').strip()
            
            # Generate default asset name if not configured
            default_asset_name = generate_default_asset_name("workbench")
            
            result = {
                'success': True,
                'created_inputs': False,
                'created_outputs': False,
                'inputs_asset': inputs_asset,
                'outputs_asset': outputs_asset
            }
            
            # Check/create inputs_asset
            # If configured, extract the asset name and verify it exists
            if inputs_asset:
                server_traces.append(f"ℹ️ inputs_asset already configured: {inputs_asset}")
                # Extract asset name from resource ID
                asset_name = inputs_asset.strip('/').split('/')[-1]
                server_traces.append(f"🔍 Verifying asset exists in Azure: {asset_name}")
            else:
                server_traces.append("📦 inputs_asset not configured, creating default workbench asset...")
                asset_name = default_asset_name
            
            try:
                created, asset_data = ensure_data_asset(
                    subscription_id=subscription_id,
                    resource_group=resource_group,
                    data_container=data_container,
                    asset_name=asset_name,
                    location=location,
                    tenant_id=tenant_id,
                    description="Auto-created workbench data asset for inputs and outputs",
                    server_traces=server_traces
                )
                
                # Build the full resource ID
                inputs_asset = build_data_asset_resource_id(
                    subscription_id=subscription_id,
                    resource_group=resource_group,
                    data_container=data_container,
                    asset_name=asset_name
                )
                
                result['inputs_asset'] = inputs_asset
                result['created_inputs'] = created
                
                # Update config
                config['azure_compute']['inputs_asset'] = inputs_asset
                
                if created:
                    server_traces.append(f"✅ Created inputs_asset: {asset_name}")
                else:
                    server_traces.append(f"✅ Verified existing inputs_asset: {asset_name}")
                
            except Exception as e:
                error_msg = f"Failed to ensure inputs_asset: {str(e)}"
                server_traces.append(f"❌ {error_msg}")
                result['success'] = False
                result['error'] = error_msg
                return result
            
            # Check/create outputs_asset
            # If configured, extract the asset name and verify it exists
            if outputs_asset:
                server_traces.append(f"ℹ️ outputs_asset already configured: {outputs_asset}")
                # Extract asset name from resource ID
                asset_name_out = outputs_asset.strip('/').split('/')[-1]
                server_traces.append(f"🔍 Verifying asset exists in Azure: {asset_name_out}")
            else:
                server_traces.append("📦 outputs_asset not configured, using same workbench asset...")
                # Use the same asset for outputs
                outputs_asset = result['inputs_asset']
                result['outputs_asset'] = outputs_asset
                result['created_outputs'] = result['created_inputs']
                
                # Update config
                config['azure_compute']['outputs_asset'] = outputs_asset
                server_traces.append(f"✅ Using workbench asset for outputs: {asset_name}")
            
            # Save config if we made changes
            if result['created_inputs'] or (not azure_compute.get('inputs_asset') and result['inputs_asset']) or (not azure_compute.get('outputs_asset') and result['outputs_asset']):
                if self.save_config(config):
                    server_traces.append("💾 Configuration saved successfully")
                else:
                    server_traces.append("⚠️ Failed to save configuration")
            
            return result
            
        except Exception as e:
            error_msg = f"Unexpected error ensuring workbench assets: {str(e)}"
            server_traces.append(f"❌ {error_msg}")
            import traceback
            server_traces.append(f"Traceback: {traceback.format_exc()}")
            return {'success': False, 'error': error_msg}
    
    def get_azure_compute_config(self) -> dict:
        """Get Azure Compute configuration"""
        try:
            config = self.load_config()
            azure_compute = config.get('azure_compute', {})

            # Return default values if not configured
            # Support both 'worksapce' (typo) and 'workspace' for backward compatibility
            workspace = azure_compute.get('workspace', '') or azure_compute.get('worksapce', '')

            return {
                'sku': azure_compute.get('sku', ''),
                'auto_cleanup': azure_compute.get('auto_cleanup', False),
                'use_script_upload': azure_compute.get('use_script_upload', True),
                'storage_account': azure_compute.get('storage_account', ''),
                'discovery_storage': azure_compute.get('discovery_storage', ''),
                'discovery_supercomputer': azure_compute.get('discovery_supercomputer', ''),
                'workspace': workspace,
                'project': azure_compute.get('project', ''),
                'inputs_asset': azure_compute.get('inputs_asset', ''),
                'outputs_asset': azure_compute.get('outputs_asset', ''),
                'data_container': azure_compute.get('data_container', ''),
                # Nodepool optimization settings
                'optimization_preference': azure_compute.get('optimization_preference', 'balanced'),
                'nodepool_cache_ttl_hours': azure_compute.get('nodepool_cache_ttl_hours', 24)
            }
        except Exception as e:
            self._log_trace(f"❌ Error loading Azure Compute config: {e}")
            # Return defaults on error
            return {
                'sku': '',
                'auto_cleanup': False,
                'storage_account': '',
                'discovery_supercomputer': '',
                'workspace': '',
                'project': '',
                'inputs_asset': '',
                'outputs_asset': '',
                'data_container': '',
                'optimization_preference': 'balanced',
                'nodepool_cache_ttl_hours': 24
            }
    
    def get_agent_search_directories(self) -> list:
        """Get list of directories to search for agent files."""
        config = self.load_config()
        directories = config.get('directories', {})
        
        if not directories:
            raise ValueError("No directories configuration found in discovery_config.json")
        
        search_dirs = []
        
        # Add each configured directory directly (preserve relative paths)
        for dir_key in ['tool_agents_dir', 'kb_agents_dir', 'entry_agents_dir']:
            dir_path = directories.get(dir_key)
            if dir_path:
                # Normalize the path but keep it as-is from config
                clean_path = dir_path.rstrip('/\\')
                if clean_path:  # Only add non-empty paths
                    search_dirs.append(clean_path)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_search_dirs = []
        for path in search_dirs:
            if path not in seen:
                seen.add(path)
                unique_search_dirs.append(path)
        
        self._log_trace(f"✅ Agent search directories: {unique_search_dirs}")
        return unique_search_dirs
    
    def is_config_complete(self) -> bool:
        """Check if all required configuration sections are complete"""
        config = self.load_config()
        
        # Check Azure OpenAI config
        azure_openai = config.get('azure_openai', {})
        if not azure_openai.get('endpoint_url') or not azure_openai.get('deployment_name') or not azure_openai.get('api_key'):
            return False
        
        # Check Azure config
        azure = config.get('azure', {})
        if not azure.get('subscription_id') or not azure.get('resource_group') or not azure.get('location'):
            return False
        
        return True


# Singleton instance for global access
_global_config_manager = None
_config_manager_lock = threading.Lock()

def get_global_config_manager(config_file: str = "discovery_config.json", verbose: bool = False) -> DiscoveryConfigManager:
    """Get the global singleton instance of DiscoveryConfigManager"""
    global _global_config_manager
    
    if _global_config_manager is None:
        with _config_manager_lock:
            # Double-check locking pattern
            if _global_config_manager is None:
                _global_config_manager = DiscoveryConfigManager(config_file, verbose)
    
    return _global_config_manager

def set_global_config_manager(config_manager: DiscoveryConfigManager):
    """Set the global config manager instance (for testing or custom initialization)"""
    global _global_config_manager
    with _config_manager_lock:
        _global_config_manager = config_manager
