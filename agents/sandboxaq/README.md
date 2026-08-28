# SandboxAQ Foundry Model Agent

This agent invokes a SandboxAQ model that your organization has subscribed to
through Azure AI Foundry. It uses a Discovery-managed tool to call the
OpenAI-compatible Foundry chat-completions endpoint.

## Configuration

Configure these values on the deployed tool; do not commit them to the catalog:

| Environment variable | Required | Description |
|---|---:|---|
| `FOUNDRY_ENDPOINT` | Yes | Azure AI Foundry endpoint, including the `/openai` API base |
| `FOUNDRY_API_KEY` | Yes | Secret for the subscribed deployment |
| `FOUNDRY_DEPLOYMENT` | Yes | SandboxAQ model deployment name |
| `FOUNDRY_API_VERSION` | No | API version; defaults to `2024-10-21` |

The endpoint must be reachable from the Discovery tool container. Use the
Foundry deployment's supported API version and authentication method if it
differs from this default.

## Example requests

- "Run the SandboxAQ model on this prompt and return the result as JSON."
- "Summarize this HR policy using the subscribed SandboxAQ deployment."

For sensitive HR data, apply your organization's privacy, access-control, and
human-review requirements. This agent does not make employment decisions.
