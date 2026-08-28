import argparse
import json
import os
import sys

import requests


def required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


def invoke_model(prompt, system_prompt, temperature, max_tokens):
    endpoint = required_env("FOUNDRY_ENDPOINT").rstrip("/")
    deployment = required_env("FOUNDRY_DEPLOYMENT")
    api_key = required_env("FOUNDRY_API_KEY")
    api_version = os.environ.get("FOUNDRY_API_VERSION", "2024-10-21")
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
        timeout=300,
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system", default="")
    parser.add_argument("--temperature", default="0")
    parser.add_argument("--max-tokens", default="4096")
    args = parser.parse_args()
    if args.action != "invoke_model":
        raise ValueError(f"Unsupported action: {args.action}")
    result = invoke_model(
        args.prompt,
        args.system,
        float(args.temperature),
        int(args.max_tokens),
    )
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, requests.RequestException) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
