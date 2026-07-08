"""Reusable Python client for the Microsoft Discovery agent *data-plane* API.

This drives the same workspace data-plane endpoints the Discovery experience
uses:

  PUT  /projects/<project>/investigations/<inv>?api-version=<ver>
  POST /conversations?api-version=<ver>&investigationName=<inv>
  POST /conversations/<conv>/openai/v1/responses
  GET  /conversations/<conv>/openai/v1/responses[/<id>]

The captured ``output[]`` is a WELL-FORMED OpenAI Responses object: every
``function_call`` and its ``function_call_output`` share the same ``call_id``.

Auth: the data-plane requires the audience
``https://discovery.azure.com/.default``. Either pass a raw bearer
token, or let ``get_token`` use ``DefaultAzureCredential`` (az login / managed
identity). If the CLI path fails with 'Please run az login', run:
    az login --scope https://discovery.azure.com/.default

Example:
    from discovery_client import DiscoveryAgentClient
    client = DiscoveryAgentClient("https://ws-<id>.workspace.discovery.azure.com")
    client.create_investigation("Literature-Research", "eval-001")
    response, conv = client.invoke(
        "Literature-Research", "eval-001", "LiteratureAgent",
        "Summarize recent findings on solid-state battery electrolytes.",
    )
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API_VERSION = "2026-06-01"
DEFAULT_SCOPE = "https://discovery.azure.com/.default"
TERMINAL_STATUSES = {"completed", "failed", "incomplete", "cancelled", "canceled"}


def get_token(scope: str = DEFAULT_SCOPE) -> str:
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
    return get_credential().get_token(scope).token


class DiscoveryAgentClient:
    """Thin, dependency-light client over the Discovery agent data-plane.

    One client targets a single workspace data-plane base URL. Methods cover the
    full investigation -> conversation -> response lifecycle plus a convenience
    ``invoke`` that runs one query end to end and polls to a terminal status.
    """

    def __init__(self, endpoint: str, token: str | None = None, *,
                 scope: str = DEFAULT_SCOPE,
                 api_version: str = DEFAULT_API_VERSION):
        if not endpoint:
            raise ValueError("endpoint is required")
        self.base = endpoint.rstrip("/")
        self.api_version = api_version
        self.scope = scope
        self.token = (token or "").replace("Bearer ", "").strip() or get_token(scope)

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

    def _request(self, method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        # Guard against non-HTTPS schemes (e.g. file://) reaching urlopen: the
        # Discovery data-plane is always addressed over HTTPS.
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError(f"refusing non-https request URL: {url}")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(
                f"HTTP {exc.code} on {method} {url}\n{detail}\n"
                "(If 401/403, try a different scope or pass a token. If 404, check "
                "endpoint / project / investigation / api-version.)"
            ) from exc

    # -- lifecycle operations ----------------------------------------------
    def create_investigation(self, project: str, investigation: str, *,
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
        status, _ = self._request("PUT", url, body)
        print(f"  investigation: {investigation} (created, status {status})")
        return investigation

    def create_conversation(self, project: str, investigation: str, *,
                            display_name: str | None = None) -> str:
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
        status, payload = self._request("POST", url, body)
        conv_id = payload.get("name")
        if not conv_id:
            raise SystemExit(f"Conversation create returned no 'name' (status {status}): {payload}")
        print(f"  conversation: {conv_id}")
        return conv_id

    def create_response(self, conversation: str, agent: str, query: str) -> str:
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
        status, payload = self._request("POST", url, body)
        resp_id = payload.get("id")
        if not resp_id:
            raise SystemExit(f"Response create returned no 'id' (status {status}): {payload}")
        print(f"  response:     {resp_id} (status {status})")
        return resp_id

    def get_response(self, conversation: str, response_id: str) -> dict | None:
        """Fetch a response by id, falling back to the list endpoint."""
        by_id = self._url(
            "conversations", conversation, "openai", "v1", "responses", response_id)
        try:
            status, payload = self._request("GET", by_id)
            if status == 200 and payload.get("id") == response_id:
                return payload
        except SystemExit:
            pass  # fall back to list
        for item in self.list_responses(conversation):
            if item.get("id") == response_id:
                return item
        return None

    def list_responses(self, conversation: str, *, limit: int = 100) -> list[dict]:
        """List responses in a conversation (most-recent first)."""
        url = self._url(
            "conversations", conversation, "openai", "v1", "responses",
            query={"limit": limit})
        _, payload = self._request("GET", url)
        return payload.get("data", []) or []

    def poll_response(self, conversation: str, response_id: str, *,
                      poll_seconds: int = 600, poll_interval: int = 3) -> dict:
        """Poll a response until it reaches a terminal status (or timeout)."""
        deadline = time.time() + poll_seconds
        last_status = None
        while time.time() < deadline:
            response = self.get_response(conversation, response_id)
            status = (response or {}).get("status")
            if status != last_status:
                print(f"  polling...    status={status}")
                last_status = status
            if response is not None and status in TERMINAL_STATUSES:
                return response
            time.sleep(poll_interval)
        raise SystemExit(
            f"Timed out after {poll_seconds}s waiting for response {response_id} "
            f"(last status: {last_status})."
        )

    def invoke(self, project: str, investigation: str, agent: str, query: str, *,
               display_name: str | None = None, conversation: str | None = None,
               poll_seconds: int = 600, poll_interval: int = 3) -> tuple[dict, str]:
        """Invoke the agent for one query and poll. Returns (response, conv_id).

        The returned ``response`` is the well-formed OpenAI Responses object
        (with ``output[]`` carrying matched ``call_id`` pairs). Reuse an existing
        conversation via ``conversation`` to keep multi-turn context.
        """
        conv_id = conversation or self.create_conversation(
            project, investigation, display_name=display_name)
        resp_id = self.create_response(conv_id, agent, query)
        response = self.poll_response(
            conv_id, resp_id, poll_seconds=poll_seconds, poll_interval=poll_interval)
        return response, conv_id
