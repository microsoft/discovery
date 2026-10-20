"""Helpers for calling a subscribed SandboxAQ model through Azure AI Foundry.

Agent scripts import from this module rather than shelling out, so prompt text
is never interpreted by a shell:

    from sandboxaq_utils import invoke_model, save_json

    result = invoke_model("Summarize this policy")
    save_json(result, "/output/final_results.json")
"""

import json
import os

import requests

DEFAULT_API_VERSION = "2024-10-21"
DEFAULT_TIMEOUT_SECONDS = 300


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


def build_request(deployment):
    """Return the chat-completions URL and auth headers for the configured endpoint.

    FOUNDRY_API_STYLE selects the request shape:
      - `azure-openai` (default): {endpoint}/deployments/{deployment}/chat/completions
        with an `api-key` header. The endpoint includes the `/openai` API base.
      - `serverless`: {endpoint}/chat/completions with a Bearer token, for
        Foundry serverless / Foundry Models endpoints. The deployment, when
        set, is sent as the `model` field.
    """
    endpoint = required_env("FOUNDRY_ENDPOINT").rstrip("/")
    api_key = required_env("FOUNDRY_API_KEY")
    style = (os.environ.get("FOUNDRY_API_STYLE") or "azure-openai").strip().lower()
    if style == "azure-openai":
        if not deployment:
            raise RuntimeError(
                "Required environment variable is not set: FOUNDRY_DEPLOYMENT"
            )
        api_version = os.environ.get("FOUNDRY_API_VERSION") or DEFAULT_API_VERSION
        url = (
            f"{endpoint}/deployments/{deployment}/chat/completions"
            f"?api-version={api_version}"
        )
        auth = {"api-key": api_key}
    elif style == "serverless":
        api_version = os.environ.get("FOUNDRY_API_VERSION")
        url = f"{endpoint}/chat/completions"
        if api_version:
            url += f"?api-version={api_version}"
        auth = {"Authorization": f"Bearer {api_key}"}
    else:
        raise RuntimeError(
            "FOUNDRY_API_STYLE must be 'azure-openai' or 'serverless'"
        )
    return url, {**auth, "Content-Type": "application/json"}


def invoke_model(
    prompt,
    system_prompt="",
    temperature=0,
    max_tokens=4096,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Send a prompt to the configured SandboxAQ deployment.

    Returns a dict with `model`, `content`, `finish_reason`, `usage`, and
    `raw_response`. `content` is an empty string when the endpoint returns no
    text (for example a `content_filter` finish reason). Raises RuntimeError on
    missing configuration, transport or HTTP failures, and empty responses;
    error messages never include the endpoint URL or credential.
    """
    deployment = os.environ.get("FOUNDRY_DEPLOYMENT", "")
    url, headers = build_request(deployment)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    body = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if deployment and "Authorization" in headers:
        body["model"] = deployment
    try:
        response = requests.post(url, headers=headers, json=body, timeout=timeout)
    except requests.RequestException as error:
        # requests embeds the URL in its messages; report only the error type.
        raise RuntimeError(
            f"Could not reach the SandboxAQ deployment ({type(error).__name__})"
        ) from None
    if not response.ok:
        detail = response.text[:500] if response.text else ""
        raise RuntimeError(
            f"SandboxAQ deployment returned HTTP {response.status_code} "
            f"{response.reason}: {detail}"
        )
    payload = response.json()
    choices = payload.get("choices")
    if not choices:
        raise RuntimeError("Foundry response did not contain any choices")
    choice = choices[0] or {}
    message = choice.get("message") or {}
    return {
        "model": payload.get("model") or deployment,
        "content": message.get("content") or "",
        "finish_reason": choice.get("finish_reason"),
        "usage": payload.get("usage"),
        "raw_response": payload,
    }


def save_json(data, path):
    """Write `data` to `path` as UTF-8 JSON, creating parent directories."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    return path
