"""Reusable async Python client for the Microsoft Discovery agent *data-plane* API.

This drives the same workspace data-plane endpoints the Discovery experience
uses:

  PUT  /projects/<project>/investigations/<inv>?api-version=<ver>
  POST /conversations?api-version=<ver>&investigationName=<inv>
  POST /conversations/<conv>/openai/v1/responses
  GET  /conversations/<conv>/openai/v1/responses[/<id>]

The captured ``output[]`` is a WELL-FORMED OpenAI Responses object: every
``function_call`` and its ``function_call_output`` share the same ``call_id``.

The client is asyncio-based (backed by ``aiohttp``) so callers can invoke many
queries concurrently -- the workload is I/O-bound on the network round-trips and
the response polling, so a single event loop drives high throughput without
threads. Manage the underlying HTTP session with ``async with`` (or call
``aclose`` explicitly).

Auth: the data-plane requires the audience
``https://discovery.azure.com/.default``. Either pass a raw bearer
token, or let ``get_token`` use ``DefaultAzureCredential`` (az login / managed
identity). If the CLI path fails with 'Please run az login', run:
    az login --scope https://discovery.azure.com/.default

Example:
    import asyncio
    from discovery_client import DiscoveryAgentClient

    async def main():
        async with DiscoveryAgentClient(
            "https://<your-workspace>.workspace.discovery.azure.com"
        ) as client:
            await client.create_investigation("Literature-Research", "eval-001")
            response, conv = await client.invoke(
                "Literature-Research", "eval-001", "LiteratureAgent",
                "Summarize recent findings on solid-state battery electrolytes.",
            )

    asyncio.run(main())
"""

import asyncio
import json
import os
import sys
import time
import urllib.parse

import aiohttp

DEFAULT_API_VERSION = "2026-06-01"
DEFAULT_SCOPE = "https://discovery.azure.com/.default"
TERMINAL_STATUSES = {"completed", "failed", "incomplete", "cancelled", "canceled"}


def get_token() -> str:
    """Acquire a bearer token, preferring an explicit one from the environment.

    Honors the DISCOVERY_TOKEN environment variable, else falls back to
    DefaultAzureCredential (az login / managed identity).
    """
    env_token = os.environ.get("DISCOVERY_TOKEN")
    if env_token:
        return env_token.replace("Bearer ", "").strip()
    try:
        from azure_credential import get_credential
    except ImportError:
        sys.exit(
            "azure-identity is required for token auth. Install the 'evaluation' extra "
            "or pass a token explicitly / via DISCOVERY_TOKEN."
        )
    return get_credential().get_token(DEFAULT_SCOPE).token


class DiscoveryAgentClient:
    """Thin async client over the Discovery agent data-plane.

    One client targets a single workspace data-plane base URL. Methods cover the
    full investigation -> conversation -> response lifecycle plus a convenience
    ``invoke`` that runs one query end to end and polls to a terminal status.

    The client owns an ``aiohttp.ClientSession`` created lazily on first use.
    Use it as an async context manager (``async with DiscoveryAgentClient(...)``)
    or call ``aclose`` when done to release the session. Concurrent calls are
    safe: each ``invoke`` opens its own conversation and only reads immutable
    client state.
    """

    def __init__(self, endpoint: str, token: str | None = None, *,
                 api_version: str = DEFAULT_API_VERSION):
        if not endpoint:
            raise ValueError("endpoint is required")
        self.base = endpoint.rstrip("/")
        self.api_version = api_version
        self.token = (token or "").replace("Bearer ", "").strip() or get_token()
        self._session: aiohttp.ClientSession | None = None

    # -- session lifecycle --------------------------------------------------
    async def __aenter__(self) -> "DiscoveryAgentClient":
        await self._ensure_session()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Return the shared session, creating it inside the running loop."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        """Close the underlying HTTP session (idempotent)."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    # -- low-level HTTP -----------------------------------------------------
    def _url(self, *segments: object, query: dict | None = None) -> str:
        """Build a data-plane URL from path segments and query params.

        Each path segment is percent-encoded (``safe=""`` so values such as
        project/investigation/conversation names cannot inject extra path or
        query structure) and the query string is built with ``urlencode`` rather
        than manual string formatting.
        """
        parts = urllib.parse.urlsplit(self.base)
        encoded = "/".join(
            urllib.parse.quote(str(seg), safe="") for seg in segments)
        path = f"{parts.path.rstrip('/')}/{encoded}"
        return urllib.parse.urlunsplit((
            parts.scheme,
            parts.netloc,
            path,
            urllib.parse.urlencode(query) if query else "",
            "",
        ))

    async def _request(self, method: str, url: str,
                       body: dict | None = None) -> tuple[int, dict]:
        # Guard against non-HTTPS schemes (e.g. file://) reaching the session:
        # the Discovery data-plane is always addressed over HTTPS.
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError(f"refusing non-https request URL: {url}")
        session = await self._ensure_session()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            async with session.request(method, url, data=data, headers=headers) as resp:
                raw = await resp.text()
                if resp.status >= 400:
                    raise SystemExit(
                        f"HTTP {resp.status} on {method} {url}\n{raw}\n"
                        "(If 401/403, pass a token. If 404, check "
                        "endpoint / project / investigation / api-version.)"
                    )
                return resp.status, (json.loads(raw) if raw else {})
        except aiohttp.ClientError as exc:
            raise SystemExit(f"Network error on {method} {url}: {exc}") from exc

    # -- lifecycle operations ----------------------------------------------
    async def create_investigation(self, project: str, investigation: str, *,
                                   display_name: str | None = None,
                                   description: str | None = None) -> str:
        """PUT-create (idempotent) a Discovery investigation. Returns its id."""
        url = self._url(
            "projects", project, "investigations", investigation,
            query={"api-version": self.api_version})
        body = {
            "displayName": display_name or investigation,
            "description": description or "Automated agent evaluation run",
        }
        status, _ = await self._request("PUT", url, body)
        print(f"  investigation: {investigation} (created, status {status})")
        return investigation

    async def create_conversation(self, project: str, investigation: str, *,
                                  display_name: str | None = None,
                                  label: str = "") -> str:
        """Open a conversation inside an investigation. Returns its id."""
        inv_name = f"/projects/{project}/investigations/{investigation}"
        url = self._url(
            "conversations",
            query={"api-version": self.api_version, "investigationName": inv_name})
        body = {
            "investigationName": inv_name,
            "displayName": display_name or investigation,
            "projectName": project,
        }
        status, payload = await self._request("POST", url, body)
        conv_id = payload.get("name")
        if not conv_id:
            raise SystemExit(f"Conversation create returned no 'name' (status {status}): {payload}")
        pfx = f"{label} " if label else ""
        print(f"  {pfx}conversation: {conv_id}")
        return conv_id

    async def create_response(self, conversation: str, agent: str, query: str, *,
                              label: str = "") -> str:
        """Send one user message to the agent. Returns the response id."""
        # The /openai/v1/ route is GA and rejects the api-version query param.
        url = self._url(
            "conversations", conversation, "openai", "v1", "responses")
        body = {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": query}],
                }
            ],
            "agent": {"type": "agent_reference", "name": agent},
        }
        status, payload = await self._request("POST", url, body)
        resp_id = payload.get("id")
        if not resp_id:
            raise SystemExit(f"Response create returned no 'id' (status {status}): {payload}")
        pfx = f"{label} " if label else ""
        print(f"  {pfx}response:     {resp_id} (status {status})")
        return resp_id

    async def get_response(self, conversation: str, response_id: str) -> dict | None:
        """Fetch a response by id, falling back to the list endpoint."""
        by_id = self._url(
            "conversations", conversation, "openai", "v1", "responses", response_id)
        try:
            status, payload = await self._request("GET", by_id)
            if status == 200 and payload.get("id") == response_id:
                return payload
        except SystemExit:
            pass  # fall back to list
        for item in await self.list_responses(conversation):
            if item.get("id") == response_id:
                return item
        return None

    async def list_responses(self, conversation: str, *, limit: int = 100) -> list[dict]:
        """List responses in a conversation (most-recent first)."""
        url = self._url(
            "conversations", conversation, "openai", "v1", "responses",
            query={"limit": limit})
        _, payload = await self._request("GET", url)
        return payload.get("data", []) or []

    async def poll_response(self, conversation: str, response_id: str, *,
                            timeout: int = 600, poll_interval: int = 3,
                            label: str = "") -> dict:
        """Poll a response until it reaches a terminal status (or timeout)."""
        deadline = time.time() + timeout
        last_status = None
        pfx = f"{label} " if label else ""
        while time.time() < deadline:
            response = await self.get_response(conversation, response_id)
            status = (response or {}).get("status")
            if status != last_status:
                print(f"  {pfx}polling...    status={status}")
                last_status = status
            if response is not None and status in TERMINAL_STATUSES:
                return response
            await asyncio.sleep(poll_interval)
        raise SystemExit(
            f"Timed out after {timeout}s waiting for response {response_id} "
            f"(last status: {last_status})."
        )

    async def invoke(self, project: str, investigation: str, agent: str, query: str, *,
                     display_name: str | None = None, conversation: str | None = None,
                     timeout: int = 600, poll_interval: int = 3,
                     label: str = "") -> tuple[dict, str]:
        """Invoke the agent for one query and poll. Returns (response, conv_id).

        The returned ``response`` is the well-formed OpenAI Responses object
        (with ``output[]`` carrying matched ``call_id`` pairs). Reuse an existing
        conversation via ``conversation`` to keep multi-turn context. ``label``
        prefixes this invocation's log lines so concurrent runs stay traceable.
        """
        conv_id = conversation or await self.create_conversation(
            project, investigation, display_name=display_name, label=label)
        resp_id = await self.create_response(conv_id, agent, query, label=label)
        response = await self.poll_response(
            conv_id, resp_id, timeout=timeout, poll_interval=poll_interval,
            label=label)
        return response, conv_id
