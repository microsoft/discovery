"""
Quiet Azure auth helpers for the agent-workbench server.

Provides helpers for Azure authentication:
- get_token_default_credential(scope, server_traces, purpose='') -> Optional[str]
  Returns an access token string or None and appends concise traces to server_traces.
- get_quiet_default_credential(server_traces=None, purpose='') -> Optional[Credential]
  Returns a DefaultAzureCredential instance or None; suppresses verbose azure.identity output.
- get_token_for_tenant(scope, tenant_id, server_traces, purpose='') -> Optional[str]
  Returns a token for a specific tenant using appropriate credential chain.
  Credentials are cached per tenant to enable token refresh without re-authentication.
- azure_rest_call(method, url, subscription_id=None, tenant_id=None, body=None, server_traces=None, timeout=60) -> dict
  Makes authenticated REST API calls to Azure Management API, handling token acquisition automatically.
- get_subscription_tenant(subscription_id, server_traces=None, use_cache=True) -> Optional[str]
  Auto-detects tenant ID from a subscription ID. Results are cached in memory.
- clear_tenant_cache(subscription_id=None) -> None
  Clears cached tenant information for a subscription or all subscriptions.
- clear_credential_cache(tenant_id=None) -> None
  Clears cached credential objects for a tenant or all tenants.

These helpers centralize the logic used across the codebase to avoid verbose SDK diagnostics
in server contexts and to standardize error handling. Credential caching enables token refresh
without requiring user re-authentication (especially important for InteractiveBrowserCredential).
"""
from typing import Optional, List, Dict
import contextlib
import io
import json
import logging
import hashlib
import os
import requests
import threading
import time

# Import SSE tracing utilities
try:
    from sse_streaming import trace_system, auth_operation, Operation
except ImportError:
    # Fallback if SSE module is not available
    def trace_system(message, level='info', metadata=None, details=None):
        pass
    auth_operation = None
    Operation = None

_LOG = logging.getLogger(__name__)

# Debug flag - set to False to suppress debug output to stderr
_DEBUG_AUTH = os.getenv('DEBUG_AUTH', 'false').lower() in ('true', '1', 'yes')

def _debug_print(msg: str):
    """Print debug message only if _DEBUG_AUTH is enabled."""
    if _DEBUG_AUTH:
        print(msg)


def _env_flag(name: str, default: bool = False) -> bool:
    """Return True/False based on common truthy strings in environment variables."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


_IS_CODESPACES = os.getenv('CODESPACES', '').lower() == 'true'
_ENABLE_AZ_CLI_CREDENTIAL = _env_flag('AGENT_WORKBENCH_ENABLE_AZURE_CLI', False)
_FORCE_NON_INTERACTIVE = _env_flag('AGENT_WORKBENCH_REQUIRE_NON_INTERACTIVE_AUTH', False)
_INTERACTIVE_DISABLED = _env_flag('AGENT_WORKBENCH_DISABLE_INTERACTIVE_AUTH', False) or _FORCE_NON_INTERACTIVE
_ALLOW_INTERACTIVE = not _INTERACTIVE_DISABLED
_ALLOW_DEVICE_CODE = _ALLOW_INTERACTIVE and not _env_flag('AGENT_WORKBENCH_DISABLE_DEVICE_CODE', False)


# Cache for auto-detected tenants to avoid repeated discovery
# Maps subscription_id -> tenant_id
_TENANT_CACHE: Dict[str, str] = {}

# Cache for tokens with expiration times
# Maps (scope, tenant_id) -> (token_string, expiration_timestamp)
_TOKEN_CACHE: Dict[tuple, tuple] = {}

# Cache for credential objects to enable token refresh without re-authentication
# Maps (credential_type, tenant_id) -> credential_object
_CREDENTIAL_CACHE: Dict[tuple, any] = {}

# Global authentication lock to prevent concurrent authentication flows
# This prevents multiple device code prompts from appearing simultaneously
_AUTH_LOCK = threading.RLock()

# Track active authentication requests to prevent duplicates
# Maps tenant_id -> (timestamp, thread_id)
_ACTIVE_AUTH_REQUESTS: Dict[str, tuple] = {}


def _managed_identity_available() -> bool:
    """Best-effort detection of managed identity availability to avoid long timeouts."""
    for key in (
        'MSI_ENDPOINT',
        'MSI_SECRET',
        'IDENTITY_ENDPOINT',
        'IDENTITY_HEADER',
        'IMDS_ENDPOINT',
        'WEBSITE_SITE_NAME'
    ):
        if os.getenv(key):
            return True
    return False


def _device_code_prompt(*args, **kwargs):
    """Lightweight device-code prompt compatible with Azure Identity callback signature.

    Accepts variable arguments to handle different Azure SDK versions:
    - Newer versions: single dict argument with device code info
    - Older versions: multiple positional arguments
    """
    # Handle both single dict argument and multiple positional arguments
    if len(args) == 1 and isinstance(args[0], dict):
        device_code = args[0]
    elif len(args) >= 1:
        # Try to extract from first argument if it's a dict-like object
        device_code = args[0] if isinstance(args[0], dict) else {}
    else:
        device_code = {}

    # Azure Identity passes a dict with standard keys
    message = None
    if isinstance(device_code, dict):
        message = device_code.get('message')
        verification_uri = device_code.get('verification_uri') or device_code.get('verificationUri')
        user_code = device_code.get('user_code') or device_code.get('userCode')
        expires_on = device_code.get('expires_on') or device_code.get('expiresOn')
    else:
        verification_uri = None
        user_code = None
        expires_on = None

    if message:
        _debug_print(message)
        # Send to frontend via SSE
        trace_system(
            message,
            level='warning',
            metadata={'context': 'Device Code Authentication'}
        )
        return

    if verification_uri and user_code:
        prompt_text = f"Device Code Authentication Required:\n1. Open: {verification_uri}\n2. Enter code: {user_code}"
        if expires_on:
            prompt_text += f"\nCode expires: {expires_on}"

        _debug_print("\n============================================")
        _debug_print(" Device Code Authentication Required")
        _debug_print("============================================")
        _debug_print(f"1. Open: {verification_uri}")
        _debug_print(f"2. Enter code: {user_code}")
        if expires_on:
            _debug_print(f"Code expires: {expires_on}")
        _debug_print("Waiting for authentication...")
        _debug_print("============================================\n")

        # Send to frontend via SSE so user sees it in the UI
        trace_system(
            "Azure Device Code Authentication Required",
            level='warning',
            metadata={'context': 'Authentication'},
            details=json.dumps({
                'verification_uri': verification_uri,
                'user_code': user_code,
                'expires_on': expires_on,
                'instructions': f'Open {verification_uri} and enter code: {user_code}'
            }, indent=2)
        )


def clear_tenant_cache(subscription_id: Optional[str] = None):
    """Clear cached tenant information.
    
    Args:
        subscription_id: If provided, clear only this subscription's cached tenant.
                        If None, clear entire cache.
    """
    global _TENANT_CACHE
    if subscription_id:
        if subscription_id in _TENANT_CACHE:
            del _TENANT_CACHE[subscription_id]
            _debug_print(f"🗑️ Cleared cached tenant for subscription {subscription_id[:8]}...")
    else:
        _TENANT_CACHE.clear()
        _debug_print("🗑️ Cleared all cached tenants")


def clear_token_cache(tenant_id: Optional[str] = None):
    """Clear cached tokens.
    
    Args:
        tenant_id: If provided, clear only tokens for this tenant.
                  If None, clear entire token cache.
    """
    global _TOKEN_CACHE
    if tenant_id:
        keys_to_delete = [k for k in _TOKEN_CACHE.keys() if k[1] == tenant_id]
        for key in keys_to_delete:
            del _TOKEN_CACHE[key]
        if keys_to_delete:
            _debug_print(f"🗑️ Cleared cached tokens for tenant {tenant_id[:8]}...")
    else:
        _TOKEN_CACHE.clear()
        _debug_print("🗑️ Cleared all cached tokens")


def clear_credential_cache(tenant_id: Optional[str] = None):
    """Clear cached credential objects.
    
    Args:
        tenant_id: If provided, clear only credentials for this tenant.
                  If None, clear entire credential cache.
    """
    global _CREDENTIAL_CACHE
    if tenant_id:
        keys_to_delete = [k for k in _CREDENTIAL_CACHE.keys() if k[1] == tenant_id]
        for key in keys_to_delete:
            del _CREDENTIAL_CACHE[key]
        if keys_to_delete:
            _debug_print(f"🗑️ Cleared cached credentials for tenant {tenant_id[:8]}...")
    else:
        _CREDENTIAL_CACHE.clear()
        _debug_print("🗑️ Cleared all cached credentials")


def azure_rest_call(method: str, url: str, subscription_id: str = None, tenant_id: str = None, 
                   body: dict = None, server_traces: List[str] = None, timeout: int = 60) -> dict:
    """Make an authenticated REST API call to Azure Management API.
    
    Args:
        method: HTTP method (GET, PUT, PATCH, POST, DELETE)
        url: Full Azure Management API URL
        subscription_id: Azure subscription ID (for auto-detecting tenant if tenant_id not provided)
        tenant_id: Specific tenant ID to authenticate against (optional, will auto-detect if not provided)
        body: Request body as dictionary (will be JSON serialized)
        server_traces: List to append trace messages (optional)
        timeout: Request timeout in seconds
        
    Returns:
        Dict with keys:
        - success (bool): Whether the request succeeded
        - status_code (int): HTTP status code
        - data (dict): Response JSON (if successful and JSON response)
        - error (str): Error message (if failed)
    """
    if server_traces is None:
        server_traces = []
    
    try:
        # Get access token
        scope = 'https://management.azure.com/.default'
        
        # If tenant_id not provided, try to obtain it from the server configuration
        if not tenant_id:
            try:
                # Import here to avoid circular imports at module load
                from discovery_config_manager import DiscoveryConfigManager
                cfg_mgr = DiscoveryConfigManager()
                azure_cfg = cfg_mgr.get_azure_config()
                tenant_from_cfg = azure_cfg.get('tenant_id', '').strip()
                if tenant_from_cfg:
                    tenant_id = tenant_from_cfg
                    server_traces.append(f"Using tenant_id from DiscoveryConfigManager: {tenant_id[:8]}...")
            except Exception:
                # If config manager isn't available or fails, do not attempt to guess tenant
                server_traces.append('! DiscoveryConfigManager unavailable for tenant fallback')
                tenant_id = tenant_id
        # Get token (require tenant-aware token if tenant_id known)
        if tenant_id:
            token = get_token_for_tenant(scope, tenant_id, server_traces, purpose=f'{method} {url[:80]}...')
        else:
            # Do not attempt to auto-detect tenant from subscription; fail token acquisition gracefully
            server_traces.append('X No tenant_id available for azure_rest_call; aborting to avoid tenant guessing')
            return {
                'success': False,
                'error': 'No tenant_id available for authentication',
                'status_code': None
            }
        
        if not token:
            return {
                'success': False,
                'error': 'Failed to acquire Azure access token',
                'status_code': None
            }
        
        # Make the REST API call
        headers = {
            'Authorization': f'Bearer {token}',
        }
        
        # Only set Content-Type for methods that carry a request body
        if method.upper() in ('POST', 'PUT', 'PATCH'):
            headers['Content-Type'] = 'application/json'
        
        # Guard: GET/HEAD must not have a body per HTTP specification
        if method.upper() in ('GET', 'HEAD') and body is not None:
            raise ValueError(
                f"HTTP {method.upper()} requests must not include a body. URL: {url[:100]}"
            )
        
        server_traces.append(f"{method} {url[:100]}...")
        
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=body if method.upper() in ('POST', 'PUT', 'PATCH') else None,
            timeout=timeout
        )
        
        # Parse response
        if response.status_code >= 200 and response.status_code < 300:
            server_traces.append(f"{method} succeeded: HTTP {response.status_code}")
            
            # Try to parse JSON response
            try:
                if response.text and response.text.strip():
                    data = response.json()
                    return {
                        'success': True,
                        'status_code': response.status_code,
                        'data': data
                    }
                else:
                    return {
                        'success': True,
                        'status_code': response.status_code,
                        'data': None
                    }
            except Exception as e:
                server_traces.append(f"! Response not JSON: {str(e)[:100]}")
                return {
                    'success': True,
                    'status_code': response.status_code,
                    'data': response.text
                }
        else:
            error_msg = f"HTTP {response.status_code}: {response.text[:500]}"
            server_traces.append(f"X {method} failed: {error_msg[:150]}")
            return {
                'success': False,
                'status_code': response.status_code,
                'error': error_msg
            }
            
    except requests.Timeout:
        error_msg = f"Request timed out after {timeout} seconds"
        server_traces.append(f"X {error_msg}")
        return {
            'success': False,
            'error': error_msg,
            'status_code': None
        }
    except Exception as e:
        error_msg = f"REST API call failed: {str(e)}"
        server_traces.append(f"X {error_msg[:200]}")
        return {
            'success': False,
            'error': error_msg,
            'status_code': None
        }


def _suppress_azure_identity_logs():
    # Set azure.* loggers to CRITICAL to suppress verbose diagnostic output in server logs.
    # Using CRITICAL instead of WARNING to fully suppress the detailed credential chain failures.
    for name in [
        'azure.core.pipeline.policies.http_logging_policy',
        'azure.identity',
        'azure.core.pipeline.transport',
        'azure.identity._credentials.chained',
        'azure.identity._credentials.default',
        'azure.identity._internal.decorators',
    ]:
        logging.getLogger(name).setLevel(logging.CRITICAL)


def get_quiet_default_credential(server_traces: Optional[List[str]] = None, purpose: str = ''):
    """Return a DefaultAzureCredential instance quietly, or None if unavailable.

    server_traces: list to append concise trace information to (optional).
    purpose: human-friendly label for traces.
    """
    _suppress_azure_identity_logs()
    try:
        from azure.identity import (
            AzureCliCredential,
            ChainedTokenCredential,
            DeviceCodeCredential,
            EnvironmentCredential,
            InteractiveBrowserCredential,
            ManagedIdentityCredential,
            VisualStudioCodeCredential
        )
    except Exception:
        if server_traces is not None:
            server_traces.append(f"azure_identity: SDK unavailable for {purpose}")
        return None

    credential_chain = []

    def _maybe_add(label: str, factory):
        try:
            credential = factory()
            if credential:
                credential_chain.append(credential)
                if server_traces is not None:
                    server_traces.append(f"azure_identity: enabled {label}")
        except Exception as exc:  # pylint: disable=broad-except
            if server_traces is not None:
                server_traces.append(f"azure_identity: {label} unavailable: {str(exc)[:120]}")

    _maybe_add('EnvironmentCredential', lambda: EnvironmentCredential())

    if _managed_identity_available():
        _maybe_add('ManagedIdentityCredential', lambda: ManagedIdentityCredential())
    else:
        if server_traces is not None:
            server_traces.append('azure_identity: managed identity not detected, skipping')

    _maybe_add('VisualStudioCodeCredential', lambda: VisualStudioCodeCredential())

    if _ENABLE_AZ_CLI_CREDENTIAL:
        _maybe_add('AzureCliCredential', lambda: AzureCliCredential())

    if _ALLOW_INTERACTIVE and not _IS_CODESPACES:
        _maybe_add('InteractiveBrowserCredential', lambda: InteractiveBrowserCredential(additionally_allowed_tenants=['*']))
    elif not _ALLOW_INTERACTIVE and server_traces is not None:
        server_traces.append('azure_identity: interactive browser auth disabled by configuration')

    if _ALLOW_DEVICE_CODE:
        _maybe_add('DeviceCodeCredential', lambda: DeviceCodeCredential(prompt_callback=_device_code_prompt, timeout=300))
    elif server_traces is not None:
        server_traces.append('azure_identity: device code auth disabled by configuration')

    if not credential_chain:
        if server_traces is not None:
            server_traces.append(f"azure_identity: no credential chain available for {purpose}")
        return None

    # Capture noisy stdout/stderr produced during instantiation of ChainedTokenCredential
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            cred = ChainedTokenCredential(*credential_chain)
    except Exception as exc:  # pylint: disable=broad-except
        msg = buf.getvalue().strip()
        if server_traces is not None:
            server_traces.append(f"azure_identity: chained credential init failed for {purpose}: {exc}")
            if msg:
                server_traces.append(f"azure_identity: details: {msg.splitlines()[-1]}")
        _LOG.debug("ChainedTokenCredential init failed", exc_info=True)
        return None

    if server_traces is not None:
        server_traces.append(f"azure_identity: chained credential ready for {purpose}")
    return cred


def get_token_default_credential(scope: str, server_traces: List[str], purpose: str = '') -> Optional[str]:
    """Return an access token string for scope or None and append concise traces.

    This helper prefers DefaultAzureCredential and returns the raw token (str) usable in
    Authorization headers.
    """
    cred = get_quiet_default_credential(server_traces, purpose)
    if cred is None:
        return None

    try:
        token = cred.get_token(scope)
        if token is None:
            server_traces.append(f"azure_identity: get_token returned no token for {purpose}")
            return None
        return token.token
    except Exception as exc:  # pylint: disable=broad-except
        server_traces.append(f"azure_identity: get_token failed for {purpose}: {exc}")
        _LOG.debug("get_token failed", exc_info=True)
        return None


def get_subscription_tenant(subscription_id: str, server_traces: Optional[List[str]] = None, use_cache: bool = True) -> Optional[str]:
    """Auto-detect the tenant ID for a given subscription.
    
    Uses the Azure Management API to query subscription details and extract tenant ID.
    This function specifically handles 401 tenant mismatch errors to extract the correct tenant.
    Results are cached in memory to avoid repeated discovery.
    
    Args:
        subscription_id: Azure subscription ID
        server_traces: Optional list to append trace messages
        use_cache: Whether to use cached tenant (default True)
        
    Returns:
        Tenant ID string or None if detection fails
    """
    if server_traces is None:
        server_traces = []
    
    # Check cache first
    if use_cache and subscription_id in _TENANT_CACHE:
        cached_tenant = _TENANT_CACHE[subscription_id]
        _debug_print(f"  Using cached tenant {cached_tenant[:8]}... for subscription {subscription_id[:8]}...")
        server_traces.append(f"  Using cached tenant {cached_tenant[:8]}...")
        
        # Add SSE trace for cached tenant
        trace_system(
            f"Using cached tenant for subscription",
            level='debug',
            metadata={'context': 'Authentication'},
            details=json.dumps({
                'subscription_id': subscription_id[:8] + '...',
                'tenant_id': cached_tenant[:8] + '...',
                'cache_status': 'hit'
            }, indent=2)
        )
        return cached_tenant
    
    # Try to get a token with DefaultAzureCredential (may fail with wrong tenant)
    temp_traces = []
    token = get_token_default_credential('https://management.azure.com/.default', temp_traces, purpose='tenant-detection')
    
    # If token acquisition failed, we cannot auto-detect tenant
    if not token:
        server_traces.append(f"! Cannot get token for tenant detection - token acquisition failed")
        server_traces.append(f"X Cannot detect tenant for subscription {subscription_id}: no auth method available")
        return None
    
    # Query subscription details to get tenant ID using REST API
    url = f"https://management.azure.com/subscriptions/{subscription_id}?api-version=2022-12-01"
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            tenant_id = data.get('tenantId')
            if tenant_id:
                server_traces.append(f"Detected tenant {tenant_id} for subscription {subscription_id}")
                # Cache the result
                _TENANT_CACHE[subscription_id] = tenant_id
                
                # Add SSE trace for tenant detection
                trace_system(
                    f"Detected Azure tenant for subscription",
                    level='info',
                    metadata={'context': 'Authentication'},
                    details=json.dumps({
                        'subscription_id': subscription_id[:8] + '...',
                        'tenant_id': tenant_id[:8] + '...',
                        'detection_method': 'Azure Management API'
                    }, indent=2)
                )
                return tenant_id
        elif resp.status_code == 401:
            # Likely tenant mismatch - extract expected tenant from error
            try:
                error_data = resp.json()
                error_msg = error_data.get('error', {}).get('message', '')
                # Parse tenant from error message like "...tenant 'https://sts.windows.net/TENANT_ID/'"
                import re
                match = re.search(r'tenant.*?([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', error_msg, re.IGNORECASE)
                if match:
                    tenant_id = match.group(1)
                    server_traces.append(f"Extracted tenant {tenant_id} from 401 error for subscription {subscription_id}")
                    # Cache the result
                    _TENANT_CACHE[subscription_id] = tenant_id
                    
                    # Add SSE trace for tenant extraction
                    trace_system(
                        f"Detected Azure tenant from error response",
                        level='info',
                        metadata={'context': 'Authentication'},
                        details=json.dumps({
                            'subscription_id': subscription_id[:8] + '...',
                            'tenant_id': tenant_id[:8] + '...',
                            'detection_method': '401 error message parsing'
                        }, indent=2)
                    )
                    return tenant_id
            except Exception:
                pass
        
        server_traces.append(f"X Failed to detect tenant: HTTP {resp.status_code}")
        return None
    except Exception as e:
        server_traces.append(f"X Exception detecting tenant: {e}")
        return None


def get_token_for_tenant(scope: str, tenant_id: str, server_traces: List[str], purpose: str = '') -> Optional[str]:
    """Get an access token for a specific tenant.
    
    Follows Azure SDK best practices with optimized credential chain for CodeSpaces/VS Code:
    1. EnvironmentCredential (service principal via env vars - production)
    2. ManagedIdentityCredential (Azure-hosted resources - VM/App Service)
    3. VisualStudioCodeCredential (VS Code signed-in user - CodeSpaces/VS Code)
    4. InteractiveBrowserCredential (browser popup - desktop environments)
    5. DeviceCodeCredential (device code flow - remote/headless environments)
    
    Note: No subprocess CLI calls - uses native Azure Identity SDK only.
    Tokens are cached with 5-minute safety buffer before expiration.
    
    Args:
        scope: OAuth scope (e.g., 'https://management.azure.com/.default')
        tenant_id: Specific tenant ID to authenticate against
        server_traces: List to append trace messages
        purpose: Human-readable purpose label
        
    Returns:
        Access token string or None
    """
    _suppress_azure_identity_logs()
    
    global _TOKEN_CACHE, _AUTH_LOCK, _ACTIVE_AUTH_REQUESTS
    
    # Check if we have a cached token that's still valid (outside lock for performance)
    cache_key = (scope, tenant_id)
    if cache_key in _TOKEN_CACHE:
        cached_token, expiration_time = _TOKEN_CACHE[cache_key]
        current_time = time.time()
        
        # Use token if it has at least 5 minutes (300 seconds) remaining
        if expiration_time > current_time + 300:
            remaining = int(expiration_time - current_time)
            return cached_token
        else:
            # Token expired or about to expire, remove from cache
            del _TOKEN_CACHE[cache_key]
    
    # Acquire lock to prevent concurrent authentication attempts
    with _AUTH_LOCK:
        # Double-check token cache after acquiring lock (another thread might have refreshed it)
        if cache_key in _TOKEN_CACHE:
            cached_token, expiration_time = _TOKEN_CACHE[cache_key]
            current_time = time.time()
            if expiration_time > current_time + 300:
                remaining = int(expiration_time - current_time)
                _debug_print(f"  Another thread refreshed token for {tenant_id[:8]}... (expires in {remaining}s)")
                server_traces.append(f"  Token refreshed by another thread")
                return cached_token
        
        # Check if another request is already authenticating for this tenant
        if tenant_id in _ACTIVE_AUTH_REQUESTS:
            auth_start_time, auth_thread_id = _ACTIVE_AUTH_REQUESTS[tenant_id]
            elapsed = time.time() - auth_start_time
            
            # If authentication has been running for less than 5 minutes and it's a different thread
            if elapsed < 300 and auth_thread_id != threading.get_ident():
                _debug_print(f"⏸️ Authentication already in progress for tenant {tenant_id[:8]}... (started {int(elapsed)}s ago)")
                server_traces.append(f"⏸️ Waiting for ongoing authentication to complete...")
                
                # Wait up to 30 seconds for the other authentication to complete
                wait_start = time.time()
                while tenant_id in _ACTIVE_AUTH_REQUESTS and (time.time() - wait_start) < 30:
                    time.sleep(1)
                    # Check if token is now available
                    if cache_key in _TOKEN_CACHE:
                        cached_token, expiration_time = _TOKEN_CACHE[cache_key]
                        if expiration_time > time.time() + 300:
                            _debug_print(f"Authentication completed by other thread")
                            server_traces.append(f"Using token from completed authentication")
                            return cached_token
                
                # If we're still here, either auth failed or timed out
                if tenant_id in _ACTIVE_AUTH_REQUESTS:
                    _debug_print(f"! Other authentication timed out, starting new attempt")
                    server_traces.append(f"! Previous authentication timed out, retrying")
                    del _ACTIVE_AUTH_REQUESTS[tenant_id]
        
        # Mark this authentication as active
        _ACTIVE_AUTH_REQUESTS[tenant_id] = (time.time(), threading.get_ident())
        _debug_print(f"  Starting authentication for tenant {tenant_id[:8]}... - {purpose}")

        # Create consolidated operation for authentication
        auth_op = None
        if auth_operation:
            try:
                auth_op = auth_operation(purpose or 'Azure operation', tenant_id)
                auth_op.start(f"Authenticating to tenant {tenant_id[:8]}...")
            except Exception:
                pass

        try:
            # Perform the actual authentication
            token = _perform_authentication(scope, tenant_id, server_traces, purpose, auth_op)
            return token
        finally:
            # Always clean up the active auth marker
            if tenant_id in _ACTIVE_AUTH_REQUESTS:
                del _ACTIVE_AUTH_REQUESTS[tenant_id]


def _perform_authentication(scope: str, tenant_id: str, server_traces: List[str], purpose: str, auth_op=None) -> Optional[str]:
    """Internal helper that performs the actual authentication logic.

    This is separated from get_token_for_tenant to allow proper lock handling.
    Should only be called while holding _AUTH_LOCK.

    Args:
        auth_op: Optional Operation object for consolidated event updates
    """
    global _TOKEN_CACHE, _CREDENTIAL_CACHE
    
    cache_key = (scope, tenant_id)
    
    # Import Azure Identity SDK
    try:
        from azure.identity import (
            EnvironmentCredential, 
            ManagedIdentityCredential,
            VisualStudioCodeCredential,
            InteractiveBrowserCredential,
            DeviceCodeCredential,
            AzureCliCredential
        )
    except ImportError:
        server_traces.append(f"X azure-identity library unavailable for tenant-specific auth ({purpose})")
        return None
    
    global _CREDENTIAL_CACHE
    
    # Try 0: Check if we have a multi-tenant credential already cached from initial auth
    # This is crucial for CodeSpaces - reuse the credential from the Azure Configuration tab
    multitenant_keys = [
        ('interactive_browser_multitenant', 'organizations'),
        ('device_code_multitenant', 'organizations')
    ]
    
    for mt_key in multitenant_keys:
        if mt_key in _CREDENTIAL_CACHE:
            try:
                cached_cred = _CREDENTIAL_CACHE[mt_key]
                server_traces.append(f"Using cached multi-tenant credential from initial auth...")
                _debug_print(f"Reusing multi-tenant credential (no re-authentication needed) for {purpose}")
                
                # Try to get token for this specific tenant using the multi-tenant credential
                token = cached_cred.get_token(scope, tenant_id=tenant_id)
                if token:
                    server_traces.append(f"Got token via cached multi-tenant credential (tenant {tenant_id[:8]}...)")
                    _debug_print(f"Successfully reused cached credential for tenant {tenant_id[:8]}...")

                    # Update operation as successful
                    if auth_op:
                        try:
                            auth_op.complete("Authenticated (cached credential)")
                        except Exception:
                            pass
                    # Cache the token with its expiration
                    _TOKEN_CACHE[cache_key] = (token.token, token.expires_on)
                    return token.token
            except Exception as e:
                server_traces.append(f"! Cached multi-tenant credential failed for tenant {tenant_id[:8]}...: {str(e)[:100]}")
                # Don't remove from cache - it might work for other tenants
    
    # Try 1: EnvironmentCredential (AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET)
    # Best for production/automation with service principals
    if auth_op:
        auth_op.step("Trying EnvironmentCredential...")
    try:
        cred_cache_key = ('environment', tenant_id)

        if cred_cache_key in _CREDENTIAL_CACHE:
            env_cred = _CREDENTIAL_CACHE[cred_cache_key]
        else:
            env_cred = EnvironmentCredential(tenant_id=tenant_id)
            _CREDENTIAL_CACHE[cred_cache_key] = env_cred

        token = env_cred.get_token(scope)
        if token:
            # Cache the token with its expiration
            _TOKEN_CACHE[cache_key] = (token.token, token.expires_on)

            # Update operation as successful
            if auth_op:
                try:
                    auth_op.complete("Authenticated (service principal)")
                except Exception:
                    pass
            return token.token
    except Exception as e:
        # Remove from cache if it failed
        cred_key_to_remove = ('environment', tenant_id)
        if cred_key_to_remove in _CREDENTIAL_CACHE:
            del _CREDENTIAL_CACHE[cred_key_to_remove]
    
    # Try 2: ManagedIdentityCredential (Azure VM, App Service, Container Instances)
    # Most secure for Azure-hosted resources
    if auth_op:
        auth_op.step("Trying ManagedIdentityCredential...")
    try:
        cred_cache_key = ('managed_identity', tenant_id)

        if cred_cache_key in _CREDENTIAL_CACHE:
            mi_cred = _CREDENTIAL_CACHE[cred_cache_key]
        else:
            mi_cred = ManagedIdentityCredential()
            _CREDENTIAL_CACHE[cred_cache_key] = mi_cred

        token = mi_cred.get_token(scope)
        if token:
            # Cache the token with its expiration
            _TOKEN_CACHE[cache_key] = (token.token, token.expires_on)

            # Update operation as successful
            if auth_op:
                try:
                    auth_op.complete("Authenticated (managed identity)")
                except Exception:
                    pass
            return token.token
    except Exception as e:
        server_traces.append(f"! ManagedIdentityCredential failed: {str(e)[:100]}")
        # Remove from cache if it failed
        cred_key_to_remove = ('managed_identity', tenant_id)
        if cred_key_to_remove in _CREDENTIAL_CACHE:
            del _CREDENTIAL_CACHE[cred_key_to_remove]
    
    # Try 2.5: VisualStudioCodeCredential (VS Code / CodeSpaces environments)
    # Works if user is signed in via VS Code Azure extension
    # This is particularly useful in CodeSpaces where VS Code is the primary environment
    if auth_op:
        auth_op.step("Trying VisualStudioCodeCredential...")
    try:
        cred_cache_key = ('vscode', tenant_id)

        if cred_cache_key in _CREDENTIAL_CACHE:
            vscode_cred = _CREDENTIAL_CACHE[cred_cache_key]
        else:
            # Don't require tenant_id parameter - let it discover automatically
            vscode_cred = VisualStudioCodeCredential()
            _CREDENTIAL_CACHE[cred_cache_key] = vscode_cred

        token = vscode_cred.get_token(scope, tenant_id=tenant_id)
        if token:
            # Cache the token with its expiration
            _TOKEN_CACHE[cache_key] = (token.token, token.expires_on)

            # Update operation as successful
            if auth_op:
                try:
                    auth_op.complete("Authenticated (VS Code)")
                except Exception:
                    pass
            return token.token
    except Exception as e:
        error_msg = str(e)
        # Provide helpful diagnostic message for VS Code auth issues
        if "azure-identity-broker" in error_msg.lower():
            server_traces.append(f"! VisualStudioCodeCredential: Azure Account extension not installed or not signed in")
        elif "not signed in" in error_msg.lower():
            server_traces.append(f"! VisualStudioCodeCredential: Not signed in to Azure in VS Code")
        else:
            server_traces.append(f"! VisualStudioCodeCredential failed: {error_msg[:100]}")
        # Remove from cache if it failed
        cred_key_to_remove = ('vscode', tenant_id)
        if cred_key_to_remove in _CREDENTIAL_CACHE:
            del _CREDENTIAL_CACHE[cred_key_to_remove]

    # Try 2.6: AzureCliCredential (optional opt-in)
    if _ENABLE_AZ_CLI_CREDENTIAL:
        if auth_op:
            auth_op.step("Trying AzureCliCredential...")
        try:
            cred_cache_key = ('azure_cli', tenant_id)

            if cred_cache_key in _CREDENTIAL_CACHE:
                cli_cred = _CREDENTIAL_CACHE[cred_cache_key]
            else:
                cli_cred = AzureCliCredential()
                _CREDENTIAL_CACHE[cred_cache_key] = cli_cred

            token = cli_cred.get_token(scope, tenant_id=tenant_id)
            if token:
                _TOKEN_CACHE[cache_key] = (token.token, token.expires_on)

                # Update operation as successful
                if auth_op:
                    try:
                        auth_op.complete("Authenticated (Azure CLI)")
                    except Exception:
                        pass
                return token.token
        except Exception as e:
            server_traces.append(f"! AzureCliCredential failed: {str(e)[:100]}")
            cred_key_to_remove = ('azure_cli', tenant_id)
            if cred_key_to_remove in _CREDENTIAL_CACHE:
                del _CREDENTIAL_CACHE[cred_key_to_remove]
    else:
        if server_traces is not None:
            server_traces.append('AzureCliCredential disabled (set AGENT_WORKBENCH_ENABLE_AZURE_CLI=1 to enable)')
    
    # Try 3: InteractiveBrowserCredential (opens browser, user authenticates)
    # Skip in CodeSpaces/remote environments as it fails with "state mismatch" due to port forwarding
    # In CodeSpaces, go directly to DeviceCodeCredential for better user experience
    # Detect desktop environments: Windows (os.name == 'nt'), macOS (sys.platform == 'darwin'), or Linux with DISPLAY
    import sys
    is_desktop = (os.name == 'nt' or sys.platform == 'darwin' or os.environ.get('DISPLAY'))
    if _ALLOW_INTERACTIVE and not _IS_CODESPACES and is_desktop:  # Desktop only
        if auth_op:
            auth_op.step("Trying InteractiveBrowserCredential...")
        try:
            cred_cache_key = ('interactive_browser', tenant_id)

            # First check if there's a multi-tenant credential available (from tenant discovery)
            multitenant_key = ('interactive_browser_multitenant', 'organizations')
            if multitenant_key in _CREDENTIAL_CACHE:
                _debug_print(f" Using cached multi-tenant InteractiveBrowserCredential for tenant {tenant_id[:8]}...")
                server_traces.append(f"Using cached multi-tenant InteractiveBrowserCredential for tenant {tenant_id[:8]}...")
                browser_cred = _CREDENTIAL_CACHE[multitenant_key]
            elif cred_cache_key in _CREDENTIAL_CACHE:
                browser_cred = _CREDENTIAL_CACHE[cred_cache_key]
            else:
                server_traces.append(f"Trying InteractiveBrowserCredential for tenant {tenant_id[:8]}...")
                _debug_print(f"🌐 Opening browser for authentication (tenant {tenant_id[:8]}...)")
                if auth_op:
                    auth_op.step("Opening browser for Azure authentication...")
                browser_cred = InteractiveBrowserCredential(tenant_id=tenant_id, additionally_allowed_tenants=['*'])
                _CREDENTIAL_CACHE[cred_cache_key] = browser_cred

            token = browser_cred.get_token(scope, tenant_id=tenant_id)
            if token:
                if cred_cache_key in _CREDENTIAL_CACHE or multitenant_key in _CREDENTIAL_CACHE:
                    _debug_print(f"Got token via cached InteractiveBrowserCredential (no browser popup) for {purpose}")
                    server_traces.append(f"Got token via cached InteractiveBrowserCredential (no browser popup)")
                else:
                    server_traces.append(f"Got token via InteractiveBrowserCredential (user login)")
                # Cache the token with its expiration
                _TOKEN_CACHE[cache_key] = (token.token, token.expires_on)

                # Update operation as successful
                if auth_op:
                    try:
                        auth_op.complete("Authenticated (interactive browser)")
                    except Exception:
                        pass
                return token.token
        except Exception as e:
            error_msg = str(e)
            server_traces.append(f"! InteractiveBrowserCredential failed: {error_msg[:100]}")
            # Remove from cache if it failed
            cred_key_to_remove = ('interactive_browser', tenant_id)
            if cred_key_to_remove in _CREDENTIAL_CACHE:
                del _CREDENTIAL_CACHE[cred_key_to_remove]
    else:
        if _IS_CODESPACES:
            server_traces.append("CodeSpaces detected - skipping InteractiveBrowserCredential")
            _debug_print("CodeSpaces environment detected - skipping InteractiveBrowserCredential")
        elif not _ALLOW_INTERACTIVE:
            server_traces.append('Interactive browser authentication disabled by configuration')
        elif not is_desktop:
            import sys
            server_traces.append(f'Interactive browser authentication unavailable (os.name={os.name}, sys.platform={sys.platform}, DISPLAY={os.environ.get("DISPLAY", "not set")})')
            _debug_print(f"Desktop environment not detected - skipping InteractiveBrowserCredential")
        else:
            server_traces.append('Interactive browser authentication unavailable on this host')
    
    # Try 4: DeviceCodeCredential (shows code on screen, user authenticates via browser)
    # Most reliable for remote/headless environments like CodeSpaces
    # Works even when port forwarding causes issues with interactive browser auth
    if _ALLOW_DEVICE_CODE:
        if auth_op:
            auth_op.step("Trying DeviceCodeCredential...")
        try:
            cred_cache_key = ('device_code', tenant_id)

            if cred_cache_key in _CREDENTIAL_CACHE:
                device_cred = _CREDENTIAL_CACHE[cred_cache_key]
                server_traces.append(f"Using cached DeviceCodeCredential for tenant {tenant_id[:8]}...")
                _debug_print(f"Using cached device code credential for tenant {tenant_id[:8]}...")
            else:
                server_traces.append(f"Trying DeviceCodeCredential for tenant {tenant_id[:8]}...")
                _debug_print(f"\n{'='*60}")
                _debug_print(f"  Device Code Authentication Required")
                _debug_print(f"{'='*60}")
                _debug_print(f"!  WARNING: You have 5 minutes to complete authentication")
                _debug_print(f"           The web request will timeout, but you can retry after authenticating")

                device_cred = DeviceCodeCredential(
                    tenant_id=tenant_id,
                    prompt_callback=_device_code_prompt,
                    timeout=300
                )
                _CREDENTIAL_CACHE[cred_cache_key] = device_cred

            token = device_cred.get_token(scope)
            if token:
                _debug_print(f"Successfully authenticated via device code for {purpose}")
                server_traces.append(f"Got token via DeviceCodeCredential (device code flow)")
                # Cache the token with its expiration
                _TOKEN_CACHE[cache_key] = (token.token, token.expires_on)

                # Update operation as successful
                if auth_op:
                    try:
                        auth_op.complete("Authenticated (device code)")
                    except Exception:
                        pass
                return token.token
        except Exception as e:
            error_msg = str(e)
            server_traces.append(f"! DeviceCodeCredential failed: {error_msg[:100]}")
            if "timeout" not in error_msg.lower():
                cred_key_to_remove = ('device_code', tenant_id)
                if cred_key_to_remove in _CREDENTIAL_CACHE:
                    del _CREDENTIAL_CACHE[cred_key_to_remove]
    else:
        server_traces.append('DeviceCodeCredential disabled by configuration')

    server_traces.append(f"X All credential methods failed for tenant {tenant_id[:8]}")

    # Update operation as failed
    if auth_op:
        try:
            auth_op.fail("All authentication methods exhausted")
        except Exception:
            pass
    return None





def get_credential_for_tenant(tenant_id: str, purpose: str = ''):
    """
    Get a tenant-aware credential object for services like Azure Storage.
    Returns a credential object that can be used directly with Azure SDK clients.
    
    Args:
        tenant_id: The Azure AD tenant ID
        purpose: Optional description for logging
    
    Returns:
        A credential object (EnvironmentCredential, ManagedIdentityCredential, or InteractiveBrowserCredential)
        or None if authentication fails
    """
    from azure.identity import (
        EnvironmentCredential, 
        ManagedIdentityCredential,
        InteractiveBrowserCredential
    )
    
    _debug_print(f"  Getting credential for tenant {tenant_id[:8]}... ({purpose})")
    
    # Priority 1: Check if we have a working cached credential (any type)
    # Check in order of preference: browser > environment > managed identity
    multitenant_key = ('interactive_browser_multitenant', 'organizations')
    if multitenant_key in _CREDENTIAL_CACHE:
        _debug_print(f"Using cached multi-tenant InteractiveBrowserCredential")
        return _CREDENTIAL_CACHE[multitenant_key]
    
    browser_key = ('interactive_browser', tenant_id)
    if browser_key in _CREDENTIAL_CACHE:
        _debug_print(f"Using cached InteractiveBrowserCredential")
        return _CREDENTIAL_CACHE[browser_key]
    
    env_key = ('environment', tenant_id)
    if env_key in _CREDENTIAL_CACHE:
        _debug_print(f"Using cached EnvironmentCredential")
        return _CREDENTIAL_CACHE[env_key]
    
    mi_key = ('managed_identity', tenant_id)
    if mi_key in _CREDENTIAL_CACHE:
        _debug_print(f"Using cached ManagedIdentityCredential")
        return _CREDENTIAL_CACHE[mi_key]
    
    # No cached credential found - try each method
    # Try 1: EnvironmentCredential (service principal via environment variables)
    try:
        env_cred = EnvironmentCredential(
            authority='https://login.microsoftonline.com',
            tenant_id=tenant_id
        )
        # Test the credential by getting a token for storage
        test_token = env_cred.get_token('https://storage.azure.com/.default')
        if test_token:
            _CREDENTIAL_CACHE[env_key] = env_cred
            _debug_print(f"EnvironmentCredential succeeded (service principal)")
            return env_cred
    except Exception as e:
        _debug_print(f"! EnvironmentCredential failed: {str(e)[:100]}")
    
    # Try 2: ManagedIdentityCredential (Azure VM, App Service, Container Instances)
    try:
        mi_cred = ManagedIdentityCredential()
        # Test the credential
        test_token = mi_cred.get_token('https://storage.azure.com/.default')
        if test_token:
            _CREDENTIAL_CACHE[mi_key] = mi_cred
            _debug_print(f"ManagedIdentityCredential succeeded (Azure-hosted)")
            return mi_cred
    except Exception as e:
        _debug_print(f"! ManagedIdentityCredential failed: {str(e)[:100]}")
        # Don't cache failed credentials
    
    # Try 3: InteractiveBrowserCredential (browser popup)
    try:
        # Check if we have a cached multi-tenant credential first
        multitenant_key = ('interactive_browser_multitenant', 'organizations')
        if multitenant_key in _CREDENTIAL_CACHE:
            _debug_print(f"Using cached multi-tenant InteractiveBrowserCredential")
            return _CREDENTIAL_CACHE[multitenant_key]
        
        # Otherwise create tenant-specific credential
        cred_cache_key = ('interactive_browser', tenant_id)
        
        if cred_cache_key in _CREDENTIAL_CACHE:
            return _CREDENTIAL_CACHE[cred_cache_key]
        
        _debug_print(f"Using InteractiveBrowserCredential for tenant {tenant_id[:8]}...")
        browser_cred = InteractiveBrowserCredential(
            tenant_id=tenant_id,
            additionally_allowed_tenants=['*']
        )
        _CREDENTIAL_CACHE[cred_cache_key] = browser_cred
        _debug_print(f"Using InteractiveBrowserCredential")
        return browser_cred
    except Exception as e:
        _debug_print(f"X InteractiveBrowserCredential failed: {str(e)[:100]}")
    
    _debug_print(f"X All credential methods failed for {purpose}")
    return None
