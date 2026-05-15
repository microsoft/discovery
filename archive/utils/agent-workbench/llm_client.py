"""
LLM Client Module - Centralized Azure OpenAI integration for Discovery Agent Workbench

This module provides a unified interface for all LLM operations, including:
- Azure OpenAI API calls
- Response parsing and processing  
- Authentication and configuration management
- Error handling and retry logic

Consolidates LLM functionality from web_server.py and combiner.py to avoid duplication
and circular dependencies.
"""
import os
import re
import json
import time
from datetime import datetime, timezone
import requests
from typing import Dict, List, Any, Optional
from discovery_config_manager import DiscoveryConfigManager, get_global_config_manager


class LLMClient:
    """Centralized client for Azure OpenAI interactions"""
    
    def __init__(self, config_manager: Optional[DiscoveryConfigManager] = None):
        self.config_manager = config_manager or get_global_config_manager()
        self._capabilities = self._load_local_capabilities()
        self._validate_config()

    def _capabilities_store_path(self) -> str:
        """Persisted capability store path under .workbench/."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_dir, '.workbench', 'llm_capabilities.json')

    def _legacy_capabilities_store_path(self) -> str:
        """Legacy persisted capability store path (next to discovery_config.json)."""
        config_file = getattr(self.config_manager, 'config_file', None)
        try:
            base_dir = os.path.dirname(str(config_file)) if config_file else os.path.dirname(__file__)
        except Exception:
            base_dir = os.path.dirname(__file__)
        return os.path.join(base_dir or '.', 'llm_capabilities.json')

    def _load_local_capabilities(self) -> Dict[str, Any]:
        store_path = self._capabilities_store_path()
        legacy_path = self._legacy_capabilities_store_path()
        read_path = store_path if os.path.exists(store_path) else legacy_path
        if not os.path.exists(read_path):
            return {"version": 1, "entries": {}}
        try:
            with open(read_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"version": 1, "entries": {}}
            if not isinstance(data.get('entries', {}), dict):
                data['entries'] = {}
            if 'version' not in data:
                data['version'] = 1

            # Best-effort migration: if we loaded from legacy path and the new file doesn't exist,
            # write the same data to the new location so future runs use .workbench/.
            if read_path == legacy_path and not os.path.exists(store_path):
                self._capabilities = data
                self._save_local_capabilities()
            return data
        except Exception:
            return {"version": 1, "entries": {}}

    def _save_local_capabilities(self) -> None:
        store_path = self._capabilities_store_path()
        tmp_path = store_path + '.tmp'
        try:
            os.makedirs(os.path.dirname(store_path), exist_ok=True)
        except Exception:
            # If the directory cannot be created, best-effort: fall through and attempt write.
            pass
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self._capabilities, f, indent=2)
            os.replace(tmp_path, store_path)
        except Exception:
            # Best-effort persistence; do not fail requests.
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def _capability_key(self, endpoint: str, deployment: str, api_version: str) -> str:
        endpoint_norm = (endpoint or '').rstrip('/')
        deployment_norm = (deployment or '').strip()
        api_version_norm = (api_version or '').strip()
        return f"{endpoint_norm}|{deployment_norm}|{api_version_norm}"

    def _get_token_param_mode(self, endpoint: str, deployment: str, api_version: str) -> str:
        """Return preferred token parameter name: 'max_tokens', 'max_completion_tokens', or 'omit'."""
        key = self._capability_key(endpoint, deployment, api_version)
        entry = self._capabilities.get('entries', {}).get(key, {})
        mode = entry.get('token_param')
        if mode in ('max_tokens', 'max_completion_tokens', 'omit'):
            return mode
        return 'max_tokens'

    def _get_temperature_mode(self, endpoint: str, deployment: str, api_version: str) -> str:
        """Return temperature mode: 'settable' or 'default_only'."""
        key = self._capability_key(endpoint, deployment, api_version)
        entry = self._capabilities.get('entries', {}).get(key, {})
        mode = entry.get('temperature_mode')
        if mode in ('settable', 'default_only'):
            return mode
        return 'settable'

    def _remember_token_param_mode(self, endpoint: str, deployment: str, api_version: str, mode: str, reason: str) -> None:
        if mode not in ('max_tokens', 'max_completion_tokens', 'omit'):
            return
        key = self._capability_key(endpoint, deployment, api_version)
        entries = self._capabilities.setdefault('entries', {})
        entry = entries.get(key, {})
        if entry.get('token_param') == mode:
            return
        entry['token_param'] = mode
        entry['last_updated_utc'] = datetime.now(timezone.utc).isoformat()
        entry['reason'] = reason
        entries[key] = entry
        self._save_local_capabilities()

    def _remember_temperature_mode(self, endpoint: str, deployment: str, api_version: str, mode: str, reason: str) -> None:
        if mode not in ('settable', 'default_only'):
            return
        key = self._capability_key(endpoint, deployment, api_version)
        entries = self._capabilities.setdefault('entries', {})
        entry = entries.get(key, {})
        if entry.get('temperature_mode') == mode:
            return
        entry['temperature_mode'] = mode
        entry['last_updated_utc'] = datetime.now(timezone.utc).isoformat()
        entry['reason'] = reason
        entries[key] = entry
        self._save_local_capabilities()

    def _apply_token_param(self, payload: Dict[str, Any], mode: str, max_output_tokens: int) -> None:
        if mode == 'max_tokens':
            payload['max_tokens'] = max_output_tokens
        elif mode == 'max_completion_tokens':
            payload['max_completion_tokens'] = max_output_tokens
        elif mode == 'omit':
            return

    def _apply_temperature_param(self, payload: Dict[str, Any], mode: str, temperature: float) -> None:
        # If the model only supports the default temperature (1), omit the param entirely.
        if mode == 'default_only':
            payload.pop('temperature', None)
            return
        payload['temperature'] = temperature

    def get_token_param_mode(self, endpoint: str, deployment: str, api_version: str) -> str:
        """Public wrapper for preferred token parameter mode."""
        return self._get_token_param_mode(endpoint, deployment, api_version)

    def get_temperature_mode(self, endpoint: str, deployment: str, api_version: str) -> str:
        """Public wrapper for preferred temperature behavior."""
        return self._get_temperature_mode(endpoint, deployment, api_version)

    def apply_token_param(self, payload: Dict[str, Any], mode: str, max_output_tokens: int) -> None:
        """Public wrapper to apply token parameter to a payload."""
        self._apply_token_param(payload, mode, max_output_tokens)

    def apply_temperature_param(self, payload: Dict[str, Any], mode: str, temperature: float) -> None:
        """Public wrapper to apply temperature parameter to a payload."""
        self._apply_temperature_param(payload, mode, temperature)
    
    def _validate_config(self) -> bool:
        """Validate that Azure OpenAI configuration is available"""
        try:
            config = self.config_manager.get_azure_openai_config()
            # Check basic required fields
            if not config.get('endpoint_url') or not config.get('deployment_name'):
                return False
            
            # Check authentication - either API key or Azure AD must be configured
            auth_type = config.get('auth_type', 'api_key')
            if auth_type == 'api_key':
                return bool(config.get('api_key'))
            elif auth_type == 'azure_ad':
                # Azure AD uses tenant-aware credential chain (see azure_auth_helpers.py)
                # Supports same-tenant, cross-tenant, and cross-subscription scenarios
                # No config validation needed - will use EnvironmentCredential, ManagedIdentity,
                # VSCodeCredential, InteractiveBrowserCredential, or DeviceCodeCredential
                return True
            
            return False
        except Exception:
            return False
    
    def is_available(self) -> bool:
        """Check if LLM is configured and available"""
        result = self._validate_config()
        if not result:
            try:
                config = self.config_manager.get_azure_openai_config()
                print(f"[LLM Client] ❌ Config validation failed:")
                print(f"  - endpoint_url: {'✓' if config.get('endpoint_url') else '✗ MISSING'}")
                print(f"  - deployment_name: {'✓' if config.get('deployment_name') else '✗ MISSING'}")
                print(f"  - auth_type: {config.get('auth_type', 'api_key')}")
                if config.get('auth_type') == 'api_key':
                    print(f"  - api_key: {'✓ Present' if config.get('api_key') else '✗ MISSING'}")
            except Exception as e:
                print(f"[LLM Client] ❌ Could not read config: {e}")
        return result
    
    def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for Azure OpenAI API calls"""
        print("[LLM Client] 🔑 Getting authentication headers...")
        config = self.config_manager.get_azure_openai_config()
        auth_type = config.get('auth_type', 'api_key')
        
        headers = {"Content-Type": "application/json"}
        
        if auth_type == 'api_key':
            api_key = config.get('api_key')
            if not api_key:
                print("[LLM Client] ❌ API key not configured in discovery_config.json")
                raise Exception("Azure OpenAI API key not configured")
            headers["api-key"] = api_key
            
        elif auth_type == 'azure_ad':
            # Use Azure AD authentication with tenant-aware credential chain
            # get_token_for_tenant() handles: EnvironmentCredential, ManagedIdentity, 
            # VSCodeCredential, InteractiveBrowserCredential, DeviceCodeCredential
            # Explicitly supports cross-tenant scenarios via tenant_id parameter
            try:
                from azure_auth_helpers import get_token_for_tenant, get_subscription_tenant
                
                azure_ad_config = config.get('azure_ad', {})
                tenant_id = azure_ad_config.get('tenant_id')
                scope = azure_ad_config.get('scope', 'https://cognitiveservices.azure.com/.default')
                
                # If no tenant_id specified, try to get it from the Azure OpenAI subscription
                if not tenant_id:
                    openai_subscription_id = azure_ad_config.get('subscription_id')
                    if openai_subscription_id:
                        tenant_id = get_subscription_tenant(openai_subscription_id, server_traces=[], use_cache=True)
                
                server_traces = []
                if tenant_id:
                    # Get token for specific tenant (supports cross-tenant scenarios)
                    token = get_token_for_tenant(scope, tenant_id, server_traces, purpose='Azure OpenAI authentication')
                else:
                    print(f"[LLM Client] Getting token with default credential (no tenant specified) with scope: {scope}")
                    # Fall back to default credential without tenant specification
                    from azure_auth_helpers import get_token_default_credential
                    token = get_token_default_credential(scope, server_traces, purpose='Azure OpenAI authentication')
                
                if not token:
                    error_msg = "Failed to acquire Azure AD token for OpenAI. Traces: " + "; ".join(server_traces)
                    print(f"[LLM Client] ❌ {error_msg}")
                    raise Exception(error_msg)
                
                headers["Authorization"] = f"Bearer {token}"
                
            except ImportError as e:
                print(f"[LLM Client] ❌ Import error: {e}")
                raise Exception(f"Azure authentication libraries not available: {e}")
            except Exception as e:
                print(f"[LLM Client] ❌ Azure AD auth failed: {e}")
                raise Exception(f"Azure AD authentication failed: {e}")
        else:
            print(f"[LLM Client] ❌ Unknown auth type: {auth_type}")
            raise Exception(f"Unknown authentication type: {auth_type}")
        
        return headers
    
    def call_azure_openai_direct(self, messages: List[Dict], max_output_tokens: int = 16384, 
                                temperature: float = 0.3, tools: Optional[List[Dict]] = None,
                                tool_choice: str = "auto", top_p: float = 1.0,
                                frequency_penalty: float = 0.0, presence_penalty: float = 0.0,
                                stream: bool = False) -> Dict[str, Any]:
        """
        Call Azure OpenAI directly using requests library
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            max_output_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-1.0)
            tools: Optional list of tool definitions for function calling
            tool_choice: How to use tools ("auto", "none", or specific tool)
            top_p: Nucleus sampling parameter (0.0-1.0)
            frequency_penalty: Frequency penalty (-2.0 to 2.0)
            presence_penalty: Presence penalty (-2.0 to 2.0)
            stream: Whether to stream responses
            
        Returns:
            Raw response JSON from Azure OpenAI API
        """
        
        config = self.config_manager.get_azure_openai_config()
        endpoint = config.get('endpoint_url')
        deployment = config.get('deployment_name')
        api_version = config.get('api_version', '2024-02-15-preview')

        if not endpoint or not deployment:
            print("[LLM Client] ❌ Missing endpoint or deployment configuration")
            raise Exception("Azure OpenAI API URL not configured. Check discovery_config.json for endpoint_url and deployment_name.")

        # Build API URL
        api_url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        print(f"[LLM Client] 📍 Using api_version: {api_version}")
        print(f"[LLM Client] Full API URL: {api_url}")
        
        headers = self.get_auth_headers()
        
        token_param_mode = self._get_token_param_mode(endpoint, deployment, api_version)
        temperature_mode = self._get_temperature_mode(endpoint, deployment, api_version)

        payload = {
            "messages": messages,
            "top_p": top_p,
            "frequency_penalty": frequency_penalty,
            "presence_penalty": presence_penalty,
            "stream": stream
        }
        self._apply_token_param(payload, token_param_mode, max_output_tokens)
        self._apply_temperature_param(payload, temperature_mode, temperature)

        # Add function calling support if tools are provided
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
            print(f"[LLM Client] Tools provided: {len(tools)} tool(s)")
        
        # Trace LLM API call to SSE
        try:
            from sse_streaming import trace_system
            import json as json_module
            
            # Create a safe version of the request for tracing (don't include full message content)
            trace_details = json_module.dumps({
                'endpoint': endpoint,
                'deployment': deployment,
                'api_version': api_version,
                'message_count': len(messages),
                'max_output_tokens': max_output_tokens,
                'temperature': temperature,
                'tools': len(tools) if tools else 0
            }, indent=2)
            
            trace_system(
                f"🤖 Calling LLM endpoint: {deployment}",
                level='debug',
                metadata={'deployment': deployment, 'message_count': len(messages)},
                details=trace_details
            )
        except Exception:
            pass  # Don't fail the LLM call if tracing fails
        
        try:
            # Retry with capability detection and rate limit handling
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                response = requests.post(api_url, headers=headers, json=payload, timeout=120)
                print(f"[LLM Client] 📥 Response received: Status {response.status_code} (attempt {attempt}/{max_attempts})")

                if response.status_code == 200:
                    response_json = response.json()
                    print(f"[LLM Client] ✅ Successfully parsed JSON response")
                    if 'usage' in response_json:
                        usage = response_json['usage']
                        print(f"[LLM Client] Token usage - Prompt: {usage.get('prompt_tokens')}, Completion: {usage.get('completion_tokens')}, Total: {usage.get('total_tokens')}")
                    
                    # Trace successful LLM response to SSE
                    try:
                        from sse_streaming import trace_system
                        import json as json_module
                        
                        usage_info = response_json.get('usage', {})
                        trace_details = json_module.dumps({
                            'deployment': deployment,
                            'prompt_tokens': usage_info.get('prompt_tokens'),
                            'completion_tokens': usage_info.get('completion_tokens'),
                            'total_tokens': usage_info.get('total_tokens'),
                            'model': response_json.get('model')
                        }, indent=2)
                        
                        trace_system(
                            f"✅ LLM response received: {usage_info.get('total_tokens', 0)} tokens",
                            level='success',
                            metadata={'tokens': usage_info.get('total_tokens', 0)},
                            details=trace_details
                        )
                    except Exception:
                        pass  # Don't fail if tracing fails
                    
                    return response_json

                # Handle rate limit (429) with exponential backoff
                if response.status_code == 429:
                    if attempt < max_attempts:
                        # Try to get Retry-After header, fallback to parsing error message, then exponential backoff
                        retry_after = response.headers.get('Retry-After')
                        wait_seconds = None
                        
                        if retry_after:
                            try:
                                wait_seconds = int(retry_after)
                            except ValueError:
                                pass
                        
                        # If no Retry-After header, try parsing from error message
                        if not wait_seconds:
                            try:
                                error_json = response.json()
                                error_msg = error_json.get('error', {}).get('message', '')
                                # Look for "retry after X seconds"
                                match = re.search(r'retry after (\d+) second', error_msg, re.IGNORECASE)
                                if match:
                                    wait_seconds = int(match.group(1))
                            except Exception:
                                pass
                        
                        # Fallback to exponential backoff if no retry time found
                        if not wait_seconds:
                            wait_seconds = min(2 ** attempt, 60)  # Cap at 60 seconds
                        
                        print(f"[LLM Client] ⏳ Rate limit hit. Waiting {wait_seconds} seconds before retry...")
                        time.sleep(wait_seconds)
                        continue
                    else:
                        # Last attempt failed with rate limit
                        error_text = response.text
                        print(f"[LLM Client] ❌ Rate limit exceeded after {max_attempts} attempts")
                        print(f"[LLM Client] Error details: {error_text[:500]}")
                        print(f"[LLM Client] Response headers: {dict(response.headers)}")
                        
                        # Trace rate limit error to SSE
                        try:
                            from sse_streaming import trace_system
                            trace_system(
                                f"❌ LLM API rate limit exceeded",
                                level='error',
                                metadata={'status': 429, 'attempts': max_attempts},
                                details=error_text[:1000]
                            )
                        except Exception:
                            pass
                        
                        raise Exception(f"Azure OpenAI API rate limit exceeded after {max_attempts} attempts: {error_text}")

                # Non-200/429: attempt capability-based recovery for known errors.
                error_text = response.text
                error_json: Optional[Dict[str, Any]] = None
                try:
                    error_json = response.json()
                except Exception:
                    # Some gateways return JSON-as-text; try best-effort parse.
                    try:
                        error_json = json.loads(error_text) if error_text else None
                    except Exception:
                        error_json = None

                if response.status_code == 400 and attempt < max_attempts and isinstance(error_json, dict):
                    err_obj = error_json.get('error')
                    err = err_obj if isinstance(err_obj, dict) else {}
                    err_code = err.get('code') or error_json.get('code')
                    err_param = err.get('param') or error_json.get('param')
                    message = (err.get('message') or error_json.get('message') or '')

                    # Last-resort: try to infer from raw text
                    if not err_code or not err_param:
                        # Examples:
                        # "Unsupported parameter: 'max_tokens' ..."
                        # "Unsupported value: 'temperature' ..."
                        m = re.search(r"\"code\"\s*:\s*\"(?P<code>[^\"]+)\"", error_text or "")
                        if m and not err_code:
                            err_code = m.group('code')
                        m = re.search(r"\"param\"\s*:\s*\"(?P<param>[^\"]+)\"", error_text or "")
                        if m and not err_param:
                            err_param = m.group('param')

                    if err_code == 'unsupported_parameter':
                        unsupported_param = err_param

                        # Azure OpenAI: some models require max_completion_tokens instead of max_tokens.
                        if unsupported_param == 'max_tokens':
                            new_mode = 'max_completion_tokens' if 'max_completion_tokens' in message else 'omit'
                            self._remember_token_param_mode(
                                endpoint,
                                deployment,
                                api_version,
                                new_mode,
                                reason=f"unsupported_parameter: {unsupported_param}"
                            )
                            token_param_mode = new_mode
                            # Rebuild payload with the corrected token parameter and retry silently.
                            payload.pop('max_tokens', None)
                            payload.pop('max_completion_tokens', None)
                            self._apply_token_param(payload, token_param_mode, max_output_tokens)
                            print(f"[LLM Client] 🔁 Retrying with token param mode: {token_param_mode}")
                            continue

                    if err_code == 'unsupported_value':
                        unsupported_param = err_param
                        if unsupported_param == 'temperature':
                            # Some models only support the default temperature value.
                            self._remember_temperature_mode(
                                endpoint,
                                deployment,
                                api_version,
                                mode='default_only',
                                reason=f"unsupported_value: {unsupported_param}"
                            )
                            temperature_mode = 'default_only'
                            # Remove temperature and retry silently.
                            payload.pop('temperature', None)
                            print(f"[LLM Client] 🔁 Retrying without temperature (default-only model)")
                            continue

                print(f"[LLM Client] ❌ API Error ({response.status_code})")
                print(f"[LLM Client] Error details: {error_text[:500]}")
                print(f"[LLM Client] Response headers: {dict(response.headers)}")
                raise Exception(f"Azure OpenAI API returned status {response.status_code}: {error_text}")

            raise Exception("Azure OpenAI API request failed after retry")
        except requests.exceptions.Timeout as e:
            print(f"[LLM Client] ⏱️ Request timeout after 120s: {str(e)}")
            raise Exception(f"API call timed out: {str(e)}")
        except requests.exceptions.RequestException as e:
            print(f"[LLM Client] ❌ Request exception: {str(e)}")
            print(f"[LLM Client] Exception type: {type(e).__name__}")
            raise Exception(f"API call failed: {str(e)}")
    
    def parse_response(self, response_data: Dict[str, Any]) -> Optional[str]:
        """
        Parse Azure OpenAI response and extract content.
        Returns None if the response contains tool_calls (function calling).
        """
        try:
            if 'choices' in response_data and response_data['choices']:
                choice = response_data['choices'][0]
                
                # Check for tool calls (function calling)
                if 'message' in choice:
                    message = choice['message']
                    
                    # If there are tool_calls, return None to signal that tools need to be executed
                    if 'tool_calls' in message and message['tool_calls']:
                        return None
                    
                    # Otherwise return the content
                    if 'content' in message:
                        return message['content']
            return None
        except Exception as e:
            print(f"Error parsing response: {e}")
            return None
    
    def get_completion(self, system_prompt: str, user_prompt: str, session_id: Optional[str] = None, 
                      max_tokens: int = 16384, temperature: float = 0.3) -> str:
        """
        Get LLM completion with system and user prompts
        
        Args:
            system_prompt: System/instruction prompt
            user_prompt: User query/content
            session_id: Optional session identifier for tracking
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Returns:
            Generated text content
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response_data = self.call_azure_openai_direct(
            messages, 
            max_output_tokens=max_tokens, 
            temperature=temperature
        )
        
        response_text = self.parse_response(response_data)
        if not response_text:
            raise Exception("Failed to parse response from Azure OpenAI")
        
        return response_text
    
    def call_for_capability(self, system_prompt: str, user_prompt: str, max_tokens: int = 300) -> Dict[str, Any]:
        """
        Call LLM for capability analysis and return structured result
        
        Returns:
            Dict with 'success' boolean and either 'text' or 'error' key
        """
        if not self.is_available():
            return {'success': False, 'error': 'LLM configuration missing or not available'}
        
        try:
            text = self.get_completion(system_prompt, user_prompt, max_tokens=max_tokens, temperature=0.0)
            return {'success': True, 'text': text or ''}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_yaml_from_response(self, content: str) -> str:
        """Extract only the YAML content from LLM response, removing explanatory text"""
        if not content:
            return content
        
        # Look for YAML code blocks first
        yaml_pattern = r"```ya?ml\s*\n(.*?)\n```"
        yaml_match = re.search(yaml_pattern, content, re.DOTALL | re.IGNORECASE)
        
        if yaml_match:
            return yaml_match.group(1).strip()
        
        # If no YAML code block, look for YAML starting with 'agent:'
        agent_pattern = r"(agent:\s*\n(?:.*\n)*?)(?:\n\s*\n|$)"
        agent_match = re.search(agent_pattern, content, re.MULTILINE)
        
        if agent_match:
            yaml_content = agent_match.group(1).strip()
            # Ensure proper indentation
            lines = yaml_content.split('\n')
            if lines:
                # Find the minimum indentation (excluding empty lines)
                non_empty_lines = [line for line in lines if line.strip()]
                if non_empty_lines:
                    min_indent = min(len(line) - len(line.lstrip()) for line in non_empty_lines if line.strip())
                    # Remove the common indentation
                    if min_indent > 0:
                        dedented_lines = []
                        for line in lines:
                            if line.strip():  # Non-empty line
                                dedented_lines.append(line[min_indent:] if len(line) > min_indent else line)
                            else:  # Empty line
                                dedented_lines.append(line)
                        yaml_content = '\n'.join(dedented_lines)
            return yaml_content
        
        # If no structured YAML found, return original content
        return content


# Global instance for backward compatibility
_default_client = None

def get_default_client() -> LLMClient:
    """Get the default LLM client instance using the global config manager"""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()  # Will use get_global_config_manager() automatically
    return _default_client

def reset_default_client():
    """Reset the default LLM client to pick up configuration changes"""
    global _default_client
    print("[LLM Client] 🔄 Resetting default LLM client to reload configuration...")
    _default_client = None


# Convenience functions for backward compatibility
def llm_available() -> bool:
    """Check if LLM is available (backward compatibility)"""
    return get_default_client().is_available()

def call_azure_openai_direct(messages: List[Dict], max_output_tokens: int = 16384, 
                            temperature: float = 0.3, tools: Optional[List[Dict]] = None,
                            tool_choice: str = "auto", top_p: float = 1.0,
                            frequency_penalty: float = 0.0, presence_penalty: float = 0.0,
                            stream: bool = False) -> Dict[str, Any]:
    """Call Azure OpenAI directly (backward compatibility)"""
    return get_default_client().call_azure_openai_direct(
        messages, max_output_tokens, temperature, tools, tool_choice,
        top_p, frequency_penalty, presence_penalty, stream
    )

def parse_llm_response_direct(response_data: Dict[str, Any]) -> Optional[str]:
    """Parse LLM response (backward compatibility)"""
    return get_default_client().parse_response(response_data)

def get_llm_completion(system_prompt: str, user_prompt: str, session_id: Optional[str] = None, 
                      max_tokens: int = 16384, temperature: float = 0.3) -> str:
    """Get LLM completion (backward compatibility)"""
    return get_default_client().get_completion(system_prompt, user_prompt, session_id, max_tokens, temperature)

def call_llm_for_capability(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> Dict[str, Any]:
    """Call LLM for capability (backward compatibility)"""
    return get_default_client().call_for_capability(system_prompt, user_prompt, max_tokens)

def extract_yaml_from_llm_response(content: str) -> str:
    """Extract YAML from LLM response (backward compatibility)"""
    return get_default_client().extract_yaml_from_response(content)

def get_auth_headers(azure_openai_config: Dict[str, Any]) -> Dict[str, str]:
    """Get auth headers (backward compatibility) - config parameter ignored, uses config manager"""
    return get_default_client().get_auth_headers()