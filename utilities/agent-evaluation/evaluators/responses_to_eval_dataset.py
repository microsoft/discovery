"""Convert a Microsoft Discovery agent response (OpenAI *Responses* API format,
e.g. the ``discovery.json`` captured from an investigation) into a well-formed
OFFLINE evaluation dataset that Foundry's tool-aware evaluators accept.

Why this exists (the workaround):
  Discovery's OTel trace projection drops the tool-call correlation id on
  ``tool_call_response`` parts and renames it to ``id`` on ``tool_call`` parts, so
  the native server-side *traces* evaluation errors on any trace with tool calls
  ("... must contain a 'tool_call_id' field"). The SOURCE Responses object,
  however, is well-formed: every ``function_call`` AND ``function_call_output``
  carries the same ``call_id``. This script reads that source object and emits a
  dataset whose tool messages carry ``tool_call_id``, so the OFFLINE runner
  (run_offline_eval.py) can score tool-using behavior today -- no upstream fix
  required.

Mapping (Responses -> evaluator schema):
  tools[]                         -> tool_definitions[] {name, description, parameters}
  output[type=function_call]      -> assistant message tool_call
                                       {type:tool_call, tool_call_id:<call_id>, name, arguments}
  output[type=function_call_output] -> tool message
                                       {role:tool, tool_call_id:<call_id>,
                                        content:[{type:tool_result, tool_result:<output>}]}
  output[type=message,role=assistant] -> final assistant text
  instructions                    -> system message (optional, --include-system)

Usage:
  python responses_to_eval_dataset.py \
      --input discovery.json \
      --query "Summarize recent findings on solid-state battery electrolytes." \
      --evaluators-config ../datasets/literature-agent/tool-calling-evaluators.json \
      --output ../datasets/literature-agent/captured-tool-calling.json
"""

import argparse
import json
import posixpath
from pathlib import Path
from urllib.parse import unquote, urlparse


def _unwrap(obj):
    """Accept either a bare Responses object or a {"data":[...]} list wrapper."""
    if isinstance(obj, dict) and "data" in obj and isinstance(obj["data"], list):
        if not obj["data"]:
            raise ValueError("input 'data' array is empty")
        return obj["data"][0]
    return obj


def _tool_definitions(response_obj):
    defs = []
    for tool in response_obj.get("tools", []) or []:
        if tool.get("type") != "function":
            continue
        defs.append(
            {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return defs


def _parse_arguments(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return {}


def _build_response_messages(response_obj):
    """Reconstruct an ordered assistant/tool message list with tool_call_id intact.

    Consecutive function_call items are grouped into a single assistant message
    (the agent can emit several in one turn); each is followed by its matching
    tool message keyed by call_id.
    """
    messages = []
    tool_calls_flat = []
    outputs_by_call = {}

    # First pass: index tool outputs by call_id.
    for item in response_obj.get("output", []) or []:
        if item.get("type") == "function_call_output":
            outputs_by_call[item.get("call_id")] = item.get("output")

    for item in response_obj.get("output", []) or []:
        itype = item.get("type")
        if itype == "function_call":
            call_id = item.get("call_id")
            tool_call = {
                "type": "tool_call",
                "tool_call_id": call_id,
                "name": item.get("name"),
                "arguments": _parse_arguments(item.get("arguments")),
            }
            tool_calls_flat.append(tool_call)
            messages.append({"role": "assistant", "content": [tool_call]})
            # Emit the paired tool result immediately after the call.
            if call_id in outputs_by_call:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_result": outputs_by_call[call_id],
                            }
                        ],
                    }
                )
        elif itype == "message" and item.get("role") == "assistant":
            text = _extract_text(item.get("content"))
            if text:
                messages.append(
                    {"role": "assistant", "content": [{"type": "text", "text": text}]}
                )

    return messages, tool_calls_flat


def _extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                parts.append(c.get("text", ""))
        return "\n".join(p for p in parts if p)
    return ""


def _citation_document_id(annotation):
    """Derive a ground-truth-comparable document id from a file_citation.

    Discovery's ``file_id`` is only a per-response ordinal ("1", "2", ...), which
    never matches a retrieval ground truth keyed by document name. The ``filename``
    is a (URL-encoded) blob URL whose basename IS the document name the datasets
    use (e.g. ``smith-2021-electrolytes.pdf``), so prefer the decoded basename and
    fall back to ``file_id`` only when no filename is present.
    """
    filename = annotation.get("filename")
    if filename:
        path = urlparse(str(filename)).path or str(filename)
        base = posixpath.basename(unquote(path))
        if base:
            return base
    file_id = annotation.get("file_id")
    return str(file_id) if file_id is not None else None


def _retrieved_documents(response_obj):
    """Extract retrieved documents from a captured Discovery response for the
    ``builtin.document_retrieval`` evaluator.

    Discovery surfaces retrieved sources as ``file_citation`` annotations under
    ``discoveryProperties.itemExtensions.<item_id>.annotations[]``. Each unique
    document (by decoded filename basename) becomes ``{document_id,
    relevance_score}``; ``relevance_score`` is assigned by citation order (earlier
    citation = higher score) because the runtime does not expose a numeric
    retrieval score.
    """
    extensions = (
        response_obj.get("discoveryProperties", {}).get("itemExtensions", {}) or {}
    )
    docs = []
    seen = set()
    for ext in extensions.values():
        if not isinstance(ext, dict):
            continue
        for ann in ext.get("annotations", []) or []:
            if ann.get("type") != "file_citation":
                continue
            doc_id = _citation_document_id(ann)
            if doc_id is None:
                continue
            if doc_id in seen:
                continue
            seen.add(doc_id)
            docs.append({"document_id": doc_id})
    total = len(docs)
    for idx, doc in enumerate(docs):
        doc["relevance_score"] = total - idx
    return docs


def response_to_row(response_obj, query, ground_truth=None):
    """Build a single well-formed offline-eval data row from a captured Responses
    object.

    ``query`` is the user goal for the turn (the Responses ``output`` does not
    contain the input message, so it must be supplied). ``ground_truth`` is an
    optional dict of extra fields carried through from the source dataset row
    (e.g. ``expected_result``, ``retrieval_ground_truth``, ``ground_truth``);
    they are added without overwriting the captured response fields.

    Reused by the evaluation pipeline to turn each live-captured response into
    an evaluable row with ``tool_call_id`` restored from ``call_id``.
    """
    response_obj = _unwrap(response_obj)
    tool_definitions = _tool_definitions(response_obj)
    messages, tool_calls = _build_response_messages(response_obj)
    row = {
        "query": query if query is not None else "(query not captured)",
        "response": messages,
        "tool_calls": tool_calls,
        "tool_definitions": tool_definitions,
    }
    retrieved_documents = _retrieved_documents(response_obj)
    if retrieved_documents:
        row["retrieved_documents"] = retrieved_documents
    if ground_truth:
        for key, value in ground_truth.items():
            row.setdefault(key, value)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Responses-format JSON (e.g. discovery.json).")
    ap.add_argument(
        "--query",
        default=None,
        help="The user query/goal for this conversation (Responses output does "
        "not contain the input message; supply it explicitly).",
    )
    ap.add_argument(
        "--evaluators-config",
        default=None,
        help="Optional dataset JSON to copy 'evaluators' (and 'evaluator_parameters') from.",
    )
    ap.add_argument("--include-system", action="store_true",
                    help="Include the agent 'instructions' as a system message in query.")
    ap.add_argument("--output", required=True, help="Output dataset JSON path.")
    args = ap.parse_args()

    response_obj = _unwrap(json.loads(Path(args.input).read_text(encoding="utf-8")))

    if not args.query:
        inv = response_obj.get("discoveryProperties", {}).get("investigationName", "")
        print(f"WARNING: no --query given; investigationName={inv!r}. "
              "Set --query for accurate intent/groundedness scoring.")

    query = args.query or "(query not captured)"
    if args.include_system and response_obj.get("instructions"):
        query = [
            {"role": "system", "content": response_obj["instructions"]},
            {"role": "user", "content": query},
        ]

    row = response_to_row(response_obj, query)
    tool_definitions = row["tool_definitions"]
    messages = row["response"]
    tool_calls = row["tool_calls"]

    evaluators = [
        "builtin.tool_call_accuracy",
        "builtin.tool_input_accuracy",
        "builtin.tool_output_utilization",
        "builtin.tool_call_success",
        "builtin.intent_resolution",
        "builtin.coherence",
    ]
    evaluator_parameters = {}
    if args.evaluators_config:
        cfg = json.loads(Path(args.evaluators_config).read_text(encoding="utf-8"))
        evaluators = cfg.get("evaluators", evaluators)
        evaluator_parameters = cfg.get("evaluator_parameters", {})

    dataset = {
        "name": "captured-tool-calling",
        "_source": "Converted from a Discovery Responses object; tool_call_id "
        "restored from call_id (offline workaround for the trace tool_call_id loss).",
        "evaluators": evaluators,
        "data_mapping": {
            "query": "{{item.query}}",
            "response": "{{item.response}}",
            "tool_calls": "{{item.tool_calls}}",
            "tool_definitions": "{{item.tool_definitions}}",
        },
        "data": [row],
    }
    if evaluator_parameters:
        dataset["evaluator_parameters"] = evaluator_parameters

    Path(args.output).write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")
    print(f"  tool_definitions: {len(tool_definitions)}")
    print(f"  tool_calls (with tool_call_id): {len(tool_calls)}")
    print(f"  response messages: {len(messages)}")
    print(f"  all tool_call_id present: "
          f"{all(tc.get('tool_call_id') for tc in tool_calls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
