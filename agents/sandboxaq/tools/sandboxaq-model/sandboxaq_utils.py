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


def invoke_model(
    prompt,
    system_prompt="",
    temperature=0,
    max_tokens=4096,
    timeout=DEFAULT_TIMEOUT_SECONDS,
):
    """Send a prompt to the configured SandboxAQ deployment.

    Returns a dict with `model`, `content`, `usage`, and `raw_response`.
    Raises RuntimeError if the deployment is not configured or returns no
    choices, and requests.RequestException on transport/HTTP failures.
    """
    endpoint = required_env("FOUNDRY_ENDPOINT").rstrip("/")
    deployment = required_env("FOUNDRY_DEPLOYMENT")
    api_key = required_env("FOUNDRY_API_KEY")
    api_version = os.environ.get("FOUNDRY_API_VERSION", DEFAULT_API_VERSION)
    url = (
        f"{endpoint}/deployments/{deployment}/chat/completions"
        f"?api-version={api_version}"
    )
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    response = requests.post(
        url,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        json={
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices")
    if not choices:
        raise RuntimeError("Foundry response did not contain any choices")
    return {
        "model": payload.get("model", deployment),
        "content": choices[0].get("message", {}).get("content", ""),
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
