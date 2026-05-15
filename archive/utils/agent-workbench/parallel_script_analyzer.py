"""
Parallel Script Analyzer for Tool Agent Creation
Processes multiple scripts concurrently for faster tool agent generation
"""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Tuple
import traceback
from prompt_loader import get_script_analysis_prompts
from llm_client import get_default_client


class ParallelScriptAnalyzer:
    """Handles parallel analysis of scripts for tool agent creation"""
    
    def __init__(self, api_url: str = None, api_key: str = None, max_concurrent_requests: int = 10):
        # Legacy parameters kept for backward compatibility but not used
        # Now uses centralized LLMClient for authentication (API Key or Azure AD)
        self.llm_client = get_default_client()
        self.max_concurrent_requests = max_concurrent_requests
        self._semaphore = None  # Will be created in async context
        
    async def analyze_scripts_parallel(self, script_files: List[Dict], dockerfile_content: str = "", aiohttp_module = None) -> Tuple[List[Dict], Dict]:
        """
        Analyze multiple scripts in parallel using async HTTP requests
        
        Args:
            script_files: List of dicts with 'path', 'content', 'folder_context' keys
            dockerfile_content: Optional Dockerfile content for context
            aiohttp_module: Pre-imported aiohttp module to avoid circular import
            
        Returns:
            Tuple of (script_docs, analysis_stats)
        """
        # Use pre-imported aiohttp module to avoid circular import during async execution
        if aiohttp_module is None:
            import aiohttp
            aiohttp_module = aiohttp
        self._aiohttp = aiohttp_module  # Store reference for use in async methods
        
        # Create semaphore in async context to ensure event loop exists
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        
        start_time = time.time()
        
        # Create analysis tasks
        tasks = []
        for script_file in script_files:
            task = self._analyze_single_script_async(
                script_file['path'],
                script_file['content'],
                script_file['folder_context'],
                dockerfile_content
            )
            tasks.append(task)
        
        # Execute tasks with concurrency control
        script_docs = []
        errors = []
        
        print(f"Analyzing {len(tasks)} scripts (parallel, max concurrent: {self.max_concurrent_requests})")
        
        # Use asyncio.gather with return_exceptions=True to handle failures gracefully
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_msg = f"Error analyzing {script_files[i]['path']}: {str(result)}"
                print(f"❌ {error_msg}")
                errors.append(error_msg)
                # Create fallback documentation
                script_docs.append({
                    'script_path': script_files[i]['path'],
                    'folder_context': script_files[i]['folder_context'],
                    'documentation': f"# {script_files[i]['path']}\n{script_files[i]['content'][:500]}...",
                    'size': len(script_files[i]['content']),
                    'analysis_failed': True
                })
            elif result:
                script_docs.append(result)
        
        end_time = time.time()
        analysis_stats = {
            'total_scripts': len(script_files),
            'successful_analyses': len([r for r in results if not isinstance(r, Exception) and r]),
            'failed_analyses': len(errors),
            'total_time_seconds': end_time - start_time,
            'average_time_per_script': (end_time - start_time) / len(script_files) if script_files else 0,
            'errors': errors
        }
        
        print(f"✅ Analysis completed in {analysis_stats['total_time_seconds']:.2f}s ({analysis_stats['successful_analyses']}/{analysis_stats['total_scripts']} scripts)")
        
        return script_docs, analysis_stats
    
    async def _analyze_single_script_async(self, script_path: str, script_content: str, 
                                         folder_context: str, dockerfile_content: str) -> Optional[Dict]:
        """Analyze a single script using async HTTP request"""
        async with self._semaphore:  # Limit concurrent requests
            try:
                # Load prompts from external files
                system_prompt, user_prompt = get_script_analysis_prompts(
                    script_path, script_content, folder_context, dockerfile_content
                )

                response_text = await self._make_llm_request_async(system_prompt, user_prompt)
                
                if response_text:
                    return {
                        'script_path': script_path,
                        'folder_context': folder_context,
                        'documentation': response_text,
                        'size': len(script_content)
                    }
                
            except Exception as e:
                print(f"⚠️ Error analyzing {script_path}: {str(e)}")
                raise e
        
        return None
    
    async def _make_llm_request_async(self, system_prompt: str, user_prompt: str, 
                                    max_tokens: int = 16384, temperature: float = 0.3) -> Optional[str]:
        """Make async HTTP request to Azure OpenAI API using centralized LLMClient"""
        # Use the aiohttp reference stored during analyze_scripts_parallel initialization
        aiohttp = self._aiohttp
        
        # Get configuration from LLMClient (supports both API Key and Azure AD)
        config = self.llm_client.config_manager.get_azure_openai_config()
        endpoint = config.get('endpoint_url')
        deployment = config.get('deployment_name')
        api_version = config.get('api_version', '2024-12-01-preview')
        
        if not endpoint or not deployment:
            raise Exception("Azure OpenAI endpoint or deployment not configured")
        
        # Build API URL - CAREFUL: no typos in URL construction!
        api_url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        
        # Get authentication headers from LLMClient (handles API Key or Azure AD)
        headers = self.llm_client.get_auth_headers()

        # Some Azure OpenAI models require max_completion_tokens instead of max_tokens.
        token_param_mode = self.llm_client.get_token_param_mode(endpoint, deployment, api_version)
        temperature_mode = self.llm_client.get_temperature_mode(endpoint, deployment, api_version)
        
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "top_p": 1,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "stream": False
        }

        # Apply token parameter based on detected capability (best-effort)
        try:
            self.llm_client.apply_token_param(payload, token_param_mode, max_tokens)
        except Exception:
            payload["max_tokens"] = max_tokens

        # Apply temperature based on detected capability (best-effort)
        try:
            self.llm_client.apply_temperature_param(payload, temperature_mode, temperature)
        except Exception:
            payload["temperature"] = temperature
        
        timeout = aiohttp.ClientTimeout(total=120)  # 2 minute timeout
        
        # Retry with capability detection
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            # Re-check capability on each attempt (another parallel request might have learned it)
            if attempt > 1:
                token_param_mode = self.llm_client.get_token_param_mode(endpoint, deployment, api_version)
                temperature_mode = self.llm_client.get_temperature_mode(endpoint, deployment, api_version)
                
                # Rebuild payload with updated capabilities
                payload.pop('max_tokens', None)
                payload.pop('max_completion_tokens', None)
                payload.pop('temperature', None)
                
                try:
                    self.llm_client.apply_token_param(payload, token_param_mode, max_tokens)
                except Exception:
                    payload["max_tokens"] = max_tokens
                
                try:
                    self.llm_client.apply_temperature_param(payload, temperature_mode, temperature)
                except Exception:
                    payload["temperature"] = temperature
            
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(api_url, headers=headers, json=payload) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            return self._parse_llm_response(response_data)
                        
                        # Handle unsupported parameter errors with retry
                        if response.status == 400 and attempt < max_attempts:
                            error_text = await response.text()
                            try:
                                error_json = json.loads(error_text)
                                err = error_json.get('error', {})
                                err_code = err.get('code')
                                err_param = err.get('param')
                                
                                if err_code == 'unsupported_parameter':
                                    if err_param == 'max_tokens':
                                        # Model requires max_completion_tokens instead
                                        print(f"⚠️ Learned: {deployment} requires max_completion_tokens")
                                        self.llm_client._remember_token_param_mode(
                                            endpoint, deployment, api_version,
                                            'max_completion_tokens',
                                            reason=f"unsupported_parameter: {err_param}"
                                        )
                                        continue  # Retry will rebuild payload with updated capability
                                    
                                    elif err_param == 'temperature':
                                        # Model doesn't support temperature parameter
                                        print(f"⚠️ Learned: {deployment} uses default temperature only")
                                        self.llm_client._remember_temperature_mode(
                                            endpoint, deployment, api_version,
                                            'default_only',
                                            reason=f"unsupported_parameter: {err_param}"
                                        )
                                        continue  # Retry will rebuild payload with updated capability
                                
                                # Check for unsupported_value errors
                                if err_code == 'unsupported_value' and err_param == 'temperature':
                                    print(f"⚠️ Learned: {deployment} requires default temperature")
                                    self.llm_client._remember_temperature_mode(
                                        endpoint, deployment, api_version,
                                        'default_only',
                                        reason=f"unsupported_value for temperature"
                                    )
                                    continue  # Retry will rebuild payload with updated capability
                            except Exception:
                                pass
                        
                        # Other errors or last attempt
                        error_text = await response.text()
                        print(f"⚠️ API Error ({response.status}): {error_text}")
                        raise Exception(f"API returned status {response.status}: {error_text}")
                            
            except asyncio.TimeoutError:
                raise Exception("Request timed out after 120 seconds")
            except Exception as e:
                if attempt >= max_attempts:
                    raise Exception(f"HTTP request failed: {str(e)}")
                # Otherwise continue to next attempt
        
        raise Exception("Request failed after retries")
    
    def _parse_llm_response(self, response_data: Dict) -> Optional[str]:
        """Parse Azure OpenAI response"""
        try:
            if 'choices' in response_data and response_data['choices']:
                choice = response_data['choices'][0]
                if 'message' in choice and 'content' in choice['message']:
                    return choice['message']['content']
        except Exception as e:
            print(f"Error parsing response: {e}")
        return None


class ThreadPoolScriptAnalyzer:
    """Alternative implementation using ThreadPoolExecutor for environments without asyncio support"""
    
    def __init__(self, api_url: str = None, api_key: str = None, max_workers: int = 10):
        # Legacy parameters kept for backward compatibility but not used
        # Now uses centralized LLMClient for authentication (API Key or Azure AD)
        self.llm_client = get_default_client()
        self.max_workers = max_workers
    
    def analyze_scripts_parallel_threads(self, script_files: List[Dict], dockerfile_content: str = "") -> Tuple[List[Dict], Dict]:
        """
        Analyze multiple scripts in parallel using ThreadPoolExecutor
        
        Args:
            script_files: List of dicts with 'path', 'content', 'folder_context' keys
            dockerfile_content: Optional Dockerfile content for context
            
        Returns:
            Tuple of (script_docs, analysis_stats)
        """
        start_time = time.time()
        script_docs = []
        errors = []
        
        print(f"🚀 Starting threaded analysis of {len(script_files)} scripts (max workers: {self.max_workers})")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_script = {}
            for script_file in script_files:
                future = executor.submit(
                    self._analyze_single_script_sync,
                    script_file['path'],
                    script_file['content'],
                    script_file['folder_context'],
                    dockerfile_content
                )
                future_to_script[future] = script_file
            
            # Collect results as they complete
            for future in as_completed(future_to_script):
                script_file = future_to_script[future]
                try:
                    result = future.result()
                    if result:
                        script_docs.append(result)
                    else:
                        errors.append(f"No result for {script_file['path']}")
                except Exception as e:
                    error_msg = f"Error analyzing {script_file['path']}: {str(e)}"
                    print(f"❌ {error_msg}")
                    errors.append(error_msg)
                    # Create fallback documentation
                    script_docs.append({
                        'script_path': script_file['path'],
                        'folder_context': script_file['folder_context'],
                        'documentation': f"# {script_file['path']}\n{script_file['content'][:500]}...",
                        'size': len(script_file['content']),
                        'analysis_failed': True
                    })
        
        end_time = time.time()
        analysis_stats = {
            'total_scripts': len(script_files),
            'successful_analyses': len([doc for doc in script_docs if not doc.get('analysis_failed', False)]),
            'failed_analyses': len(errors),
            'total_time_seconds': end_time - start_time,
            'average_time_per_script': (end_time - start_time) / len(script_files) if script_files else 0,
            'errors': errors
        }
        
        print(f"✅ Threaded analysis completed in {analysis_stats['total_time_seconds']:.2f}s")
        print(f"   Success: {analysis_stats['successful_analyses']}/{analysis_stats['total_scripts']}")
        
        return script_docs, analysis_stats
    
    def _analyze_single_script_sync(self, script_path: str, script_content: str, 
                                   folder_context: str, dockerfile_content: str) -> Optional[Dict]:
        """Analyze a single script using synchronous requests"""
        try:
            import requests
            from script_chunker import chunk_script_by_structure, merge_chunk_analyses, estimate_tokens
            from prompt_loader import get_script_analysis_prompts, get_script_chunk_analysis_prompts
            
            # Determine if chunking is needed - read from config for accurate limits
            max_chunk_tokens = 15000  # Conservative fallback
            try:
                from discovery_config_manager import get_global_config_manager
                config_manager = get_global_config_manager()
                conv_config = config_manager.get_conversation_config()
                if conv_config:
                    max_tokens = conv_config.get('max_tokens', 64000)
                    max_output = conv_config.get('max_output_tokens', 16384)
                    safety = conv_config.get('safety_fraction', 0.85)
                    
                    # Calculate: (max_tokens - max_output - overhead) * safety
                    available = max_tokens - max_output - 5000  # 5k overhead
                    max_chunk_tokens = int(available * safety)
                    max_chunk_tokens = max(10000, min(max_chunk_tokens, 40000))  # 10k-40k range
            except Exception as config_error:
                print(f"   ⚠️ Config read error for {script_path}: {config_error}")
                pass  # Use fallback
            
            chunks = chunk_script_by_structure(script_content, max_chunk_tokens, encoder=None)
            
            if len(chunks) == 1:
                # Single chunk - standard analysis
                system_prompt, user_prompt = get_script_analysis_prompts(
                    script_path, script_content, folder_context, dockerfile_content
                )
                
                response_text = self._make_llm_request_sync(system_prompt, user_prompt)
                
                if response_text:
                    return {
                        'script_path': script_path,
                        'folder_context': folder_context,
                        'documentation': response_text,
                        'size': len(script_content),
                        'chunks': 1
                    }
            else:
                # Multiple chunks - analyze each and merge
                print(f"   📄 Large script: {script_path} - analyzing in {len(chunks)} chunks")
                chunk_results = []
                
                for i, chunk in enumerate(chunks, 1):
                    system_prompt, user_prompt = get_script_chunk_analysis_prompts(
                        script_path, chunk['content'], i, len(chunks),
                        chunk['description'], folder_context, dockerfile_content
                    )
                    
                    chunk_response = self._make_llm_request_sync(system_prompt, user_prompt)
                    if chunk_response:
                        chunk_results.append(chunk_response)
                
                # Merge chunk results
                merged_doc = merge_chunk_analyses(chunk_results, script_path)
                
                return {
                    'script_path': script_path,
                    'folder_context': folder_context,
                    'documentation': merged_doc,
                    'size': len(script_content),
                    'chunks': len(chunks)
                }
            
        except Exception as e:
            print(f"⚠️ Error analyzing {script_path}: {str(e)}")
            raise e
        
        return None
    
    def _make_llm_request_sync(self, system_prompt: str, user_prompt: str, 
                                max_tokens: int = 16384, temperature: float = 0.1) -> Optional[str]:
        """Make synchronous HTTP request to Azure OpenAI API using centralized LLMClient with retry logic"""
        import requests
        
        # Get configuration and authentication from LLMClient
        config = self.llm_client.config_manager.get_azure_openai_config()
        endpoint = config.get('endpoint_url')
        deployment = config.get('deployment_name')
        api_version = config.get('api_version', '2024-12-01-preview')
        
        if not endpoint or not deployment:
            raise Exception("Azure OpenAI endpoint or deployment not configured")
        
        # Build API URL
        api_url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        
        # Get authentication headers from LLMClient (handles API Key or Azure AD)
        headers = self.llm_client.get_auth_headers()
        
        # Get initial capability settings
        token_param_mode = self.llm_client.get_token_param_mode(endpoint, deployment, api_version)
        temperature_mode = self.llm_client.get_temperature_mode(endpoint, deployment, api_version)
        
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "top_p": 1,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "stream": False
        }
        
        # Apply token parameter based on detected capability
        try:
            self.llm_client.apply_token_param(payload, token_param_mode, max_tokens)
        except Exception:
            payload["max_tokens"] = max_tokens
        
        # Apply temperature based on detected capability
        try:
            self.llm_client.apply_temperature_param(payload, temperature_mode, temperature)
        except Exception:
            payload["temperature"] = temperature
        
        # Retry with capability detection
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            # Re-check capability on each attempt (another parallel request might have learned it)
            if attempt > 1:
                token_param_mode = self.llm_client.get_token_param_mode(endpoint, deployment, api_version)
                temperature_mode = self.llm_client.get_temperature_mode(endpoint, deployment, api_version)
                
                # Rebuild payload with updated capabilities
                payload.pop('max_tokens', None)
                payload.pop('max_completion_tokens', None)
                payload.pop('temperature', None)
                
                try:
                    self.llm_client.apply_token_param(payload, token_param_mode, max_tokens)
                except Exception:
                    payload["max_tokens"] = max_tokens
                
                try:
                    self.llm_client.apply_temperature_param(payload, temperature_mode, temperature)
                except Exception:
                    payload["temperature"] = temperature
            
            try:
                response = requests.post(api_url, headers=headers, json=payload, timeout=120)
                
                if response.status_code == 200:
                    response_data = response.json()
                    response_text = self._parse_llm_response(response_data)
                    return response_text
                
                # Handle unsupported parameter errors with retry
                if response.status_code == 400 and attempt < max_attempts:
                    try:
                        error_json = response.json()
                        err = error_json.get('error', {})
                        err_code = err.get('code')
                        err_param = err.get('param')
                        
                        if err_code == 'unsupported_parameter':
                            if err_param == 'max_tokens':
                                # Model requires max_completion_tokens instead
                                print(f"⚠️ Learned: {deployment} requires max_completion_tokens")
                                self.llm_client._remember_token_param_mode(
                                    endpoint, deployment, api_version,
                                    'max_completion_tokens',
                                    reason=f"unsupported_parameter: {err_param}"
                                )
                                continue  # Retry will rebuild payload with updated capability
                            
                            elif err_param == 'temperature':
                                # Model doesn't support temperature parameter
                                print(f"⚠️ Learned: {deployment} uses default temperature only")
                                self.llm_client._remember_temperature_mode(
                                    endpoint, deployment, api_version,
                                    'default_only',
                                    reason=f"unsupported_parameter: {err_param}"
                                )
                                continue  # Retry will rebuild payload with updated capability
                        
                        # Check for unsupported_value errors
                        if err_code == 'unsupported_value' and err_param == 'temperature':
                            print(f"⚠️ Learned: {deployment} requires default temperature")
                            self.llm_client._remember_temperature_mode(
                                endpoint, deployment, api_version,
                                'default_only',
                                reason=f"unsupported_value for temperature"
                            )
                            continue  # Retry will rebuild payload with updated capability
                    except Exception:
                        pass
                
                # Other errors or last attempt
                print(f"⚠️ API Error ({response.status_code}): {response.text}")
                raise Exception(f"API returned status {response.status_code}: {response.text}")
                
            except requests.exceptions.Timeout:
                if attempt >= max_attempts:
                    raise Exception("Request timed out after 120 seconds")
            except Exception as e:
                if attempt >= max_attempts:
                    print(f"⚠️ Error in LLM request: {str(e)}")
                    raise e
        
        raise Exception("Request failed after retries")
    
    def _parse_llm_response(self, response_data: Dict) -> Optional[str]:
        """Parse Azure OpenAI response"""
        try:
            if 'choices' in response_data and response_data['choices']:
                choice = response_data['choices'][0]
                if 'message' in choice and 'content' in choice['message']:
                    return choice['message']['content']
        except Exception as e:
            print(f"Error parsing response: {e}")
        return None


def create_script_analyzer(api_url: str = None, api_key: str = None, max_concurrent: int = 10, use_async: bool = True):
    """Factory function to create the appropriate script analyzer
    
    Note: api_url and api_key parameters are deprecated and ignored.
    Authentication is now handled via centralized LLMClient (supports API Key or Azure AD).
    """
    if use_async:
        return ParallelScriptAnalyzer(max_concurrent_requests=max_concurrent)
    else:
        return ThreadPoolScriptAnalyzer(max_workers=max_concurrent)
