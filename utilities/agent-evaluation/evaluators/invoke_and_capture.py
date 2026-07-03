"""Invoke a Microsoft Discovery agent through the workspace *data-plane* and
capture its full OpenAI *Responses* object for offline evaluation.

This is a thin CLI/wrapper over the reusable client in ``discovery_client.py``.
It drives the same endpoints the Discovery experience uses, NOT the Foundry
project endpoint:

  1. (optional) PUT  /projects/<project>/investigations/<inv>
  2. POST /conversations?api-version=<ver>&investigationName=<inv>  -> {name: conv}
  3. POST /conversations/<conv>/openai/v1/responses                 -> 202 {id: resp_...}
  4. GET  /conversations/<conv>/openai/v1/responses                 (poll until terminal)

Why this matters for evals:
  The captured `output[]` is a WELL-FORMED Responses object -- every
  `function_call` and its `function_call_output` carry the SAME `call_id`. That
  is exactly what responses_to_eval_dataset.py needs to restore `tool_call_id`,
  so it sidesteps BOTH the App Insights payload truncation AND the OTel
  trace-projection loss that breaks the native server-side traces evaluation.

Output: a bare Responses JSON object (the matched response, with its `output[]`),
ready to feed straight into:
    python responses_to_eval_dataset.py --input <this-output> --query "<query>" ...

For programmatic reuse, import the client directly:
    from discovery_client import DiscoveryAgentClient
"""

import argparse
import json
from pathlib import Path

from discovery_client import (
    DEFAULT_API_VERSION,
    DEFAULT_SCOPE,
    DiscoveryAgentClient,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", required=True,
                        help="Workspace data-plane base URL, "
                             "e.g. https://ws-<id>.workspace.discovery.azure.com")
    parser.add_argument("--project", required=True, help="Discovery project name")
    parser.add_argument("--investigation", required=True, help="Investigation name (id)")
    parser.add_argument("--agent", required=True, help="Agent name (agent_reference)")
    parser.add_argument("--query", required=True, help="User input text to send to the agent")
    parser.add_argument("--output", required=True, help="Path to write the captured Responses JSON")
    parser.add_argument("--api-version", default=DEFAULT_API_VERSION,
                        help=f"Data-plane API version (default {DEFAULT_API_VERSION})")
    parser.add_argument("--display-name", default=None,
                        help="Conversation display name (defaults to the investigation name)")
    parser.add_argument("--create-investigation", action="store_true",
                        help="PUT-create the investigation before opening the conversation "
                             "(use when the investigation does not already exist)")
    parser.add_argument("--conversation", default=None,
                        help="Reuse an existing conversation id instead of creating one")
    parser.add_argument("--scope", default=DEFAULT_SCOPE,
                        help=f"AAD token scope (default {DEFAULT_SCOPE})")
    parser.add_argument("--token", default=None,
                        help="Raw bearer token (overrides --scope / DISCOVERY_TOKEN)")
    parser.add_argument("--poll-seconds", type=int, default=600,
                        help="Max seconds to wait for a terminal response (default 600)")
    parser.add_argument("--poll-interval", type=int, default=3,
                        help="Seconds between polls (default 3)")
    args = parser.parse_args()

    client = DiscoveryAgentClient(
        args.endpoint, args.token, scope=args.scope, api_version=args.api_version)

    print("Invoking Discovery agent via data-plane:")
    if args.create_investigation:
        client.create_investigation(
            args.project, args.investigation, display_name=args.display_name)
    response, conv_id = client.invoke(
        args.project, args.investigation, args.agent, args.query,
        display_name=args.display_name, conversation=args.conversation,
        poll_seconds=args.poll_seconds, poll_interval=args.poll_interval,
    )

    status = response.get("status")
    output_types = [o.get("type") for o in response.get("output", []) or []]
    print(f"  done:         status={status}, output items={output_types}")
    if status != "completed":
        print(f"  WARNING: terminal status is '{status}', not 'completed'. "
              f"error={response.get('error')}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(response, indent=2), encoding="utf-8")
    print(f"\nCaptured response -> {out_path}")
    print("Next: convert to an offline eval dataset, e.g.")
    print(f"  python responses_to_eval_dataset.py --input {out_path} "
          f"--query \"{args.query}\" --evaluators-config <config.json> --output <dataset.json>")


if __name__ == "__main__":
    main()
