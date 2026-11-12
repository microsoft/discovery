#!/usr/bin/env python3
"""Diagnose the public MCP endpoint, not Discovery specialist activation."""

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://api.microchip.com/mcp/resources"
ACTION = "search_microchip_product_documents"
QUERY = {"query": "CoreSPI HB0089 handbook 5.2", "limit": 10}
HANDBOOK = (
    "https://ww1.microchip.com/downloads/aemDocuments/documents/FPGA/"
    "ProductDocuments/UserGuides/ip_cores/directcores/CoreSPI_HB.pdf"
)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOOL_PAGES = 10


class ProbeError(Exception):
    """A failed protocol or application-level readiness check."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("MCP redirect refused; verify the official endpoint.")


def decode_response(body, content_type, request_id):
    try:
        text = body.decode("utf-8-sig")
        if content_type.split(";", 1)[0].strip().lower() == "text/event-stream":
            responses = []
            data = []
            for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") + [""]:
                if line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
                elif not line and data:
                    message = json.loads("\n".join(data))
                    data = []
                    if isinstance(message, dict) and message.get("id") == request_id:
                        responses.append(message)
            if len(responses) != 1:
                raise ProbeError("Expected exactly one matching MCP SSE response.")
            message = responses[0]
        else:
            message = json.loads(text)
    except (UnicodeError, ValueError) as error:
        raise ProbeError("MCP returned invalid UTF-8/JSON.") from error
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise ProbeError("MCP response is not a JSON-RPC 2.0 object.")
    if type(message.get("id")) is not int or message["id"] != request_id:
        raise ProbeError("MCP response ID does not match the request.")
    if "error" in message:
        raise ProbeError("MCP returned a JSON-RPC error; no readiness PASS.")
    result = message.get("result")
    if not isinstance(result, dict):
        raise ProbeError("MCP response has no object result.")
    return result


class Transport:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(NoRedirect())
        self.session_id = None
        self.protocol = None
        self.request_id = 0

    def send(self, method, params=None, notification=False):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.request_id += 1
            message["id"] = self.request_id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        request = urllib.request.Request(
            ENDPOINT, json.dumps(message).encode("utf-8"), headers, method="POST"
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                if notification:
                    if response.status not in (200, 202, 204):
                        raise ProbeError("MCP initialization notification was not accepted.")
                    return None
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ProbeError("MCP response exceeds the diagnostic size limit.")
                return decode_response(
                    body, response.headers.get("Content-Type", ""), self.request_id
                )
        except urllib.error.HTTPError as error:
            raise ProbeError(f"MCP HTTP status {error.code}; no readiness PASS.") from error
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as error:
            raise ProbeError(f"MCP transport failed ({type(error).__name__}).") from error


def find_action(transport):
    cursor = None
    seen = set()
    found = None
    for _ in range(MAX_TOOL_PAGES):
        result = transport.send("tools/list", {"cursor": cursor} if cursor else {})
        tools = result.get("tools")
        if not isinstance(tools, list) or not all(isinstance(t, dict) for t in tools):
            raise ProbeError("MCP tools/list returned an invalid tool inventory.")
        for tool in tools:
            if tool.get("name") == ACTION:
                if found is not None:
                    raise ProbeError("Documentation action is duplicated in the inventory.")
                found = tool
        cursor = result.get("nextCursor")
        if cursor is None:
            if found is None:
                raise ProbeError("Required documentation action is absent.")
            return found
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ProbeError("MCP tool pagination is invalid or cyclic.")
        seen.add(cursor)
    raise ProbeError("MCP tool inventory exceeds the bounded pagination limit.")


def check_schema(tool):
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ProbeError("Documentation action has an unsupported input schema.")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if (not isinstance(properties, dict) or not isinstance(required, list)
            or not all(isinstance(key, str) for key in required)):
        raise ProbeError("Documentation action input schema is malformed.")
    if any(key not in QUERY for key in required):
        raise ProbeError("Documentation action requires unsupported arguments.")
    for name, kind in (("query", "string"), ("limit", "integer")):
        item = properties.get(name)
        if not isinstance(item, dict) or item.get("type") != kind:
            raise ProbeError(f"Documentation action schema changed for {name}.")
    limit = properties["limit"]
    for key, comparison in (("minimum", lambda v: v > 10), ("maximum", lambda v: v < 10)):
        if key in limit:
            value = limit[key]
            if type(value) not in (int, float) or comparison(value):
                raise ProbeError("Requested result limit is not accepted by the live schema.")


def application_result(result):
    if "isError" in result and result["isError"] is not False:
        raise ProbeError("Documentation tool returned a failure or invalid isError flag.")
    payload = result.get("structuredContent")
    if payload is None:
        content = result.get("content")
        if not isinstance(content, list):
            raise ProbeError("Documentation tool has no structured or text result.")
        texts = [
            item.get("text") for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if len(texts) != 1 or not isinstance(texts[0], str):
            raise ProbeError("Documentation tool has no unambiguous JSON text result.")
        try:
            payload = json.loads(texts[0])
        except ValueError as error:
            raise ProbeError("Documentation tool text is not application JSON.") from error
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ProbeError("Documentation application response did not report success=true.")
    data = payload.get("data")
    documents = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(documents, list) or not documents:
        raise ProbeError("Successful response contains no documentation results.")
    if not any(
        isinstance(doc, dict)
        and any(HANDBOOK in doc.get(key, "") for key in ("url", "content")
                if isinstance(doc.get(key), str))
        for doc in documents
    ):
        raise ProbeError("No exact official CoreSPI handbook link was returned.")
    return len(documents)


def probe(transport):
    initialization = transport.send("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "discovery-siphy-endpoint-diagnostic", "version": "1.0"},
    })
    if initialization.get("protocolVersion") != "2025-03-26":
        raise ProbeError("Server selected an unsupported MCP protocol version.")
    capabilities = initialization.get("capabilities")
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get("tools"), dict):
        raise ProbeError("MCP server did not advertise tools capability.")
    transport.protocol = initialization["protocolVersion"]
    transport.send("notifications/initialized", notification=True)
    check_schema(find_action(transport))
    count = application_result(transport.send(
        "tools/call", {"name": ACTION, "arguments": dict(QUERY)}
    ))
    return {
        "status": "endpoint_pass",
        "protocol_version": transport.protocol,
        "documentation_action": ACTION,
        "arguments": QUERY,
        "document_count": count,
        "official_handbook_url": HANDBOOK,
        "handbook_downloaded_or_read": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New JSON receipt; existing files are refused.")
    args = parser.parse_args(argv)
    if args.output and (args.output.exists() or args.output.is_symlink()):
        parser.error("Output already exists; choose a fresh receipt path.")
    started = time.monotonic()
    receipt = {
        "endpoint": ENDPOINT,
        "executor": "standalone host diagnostic; NOT hardware-spec-dev",
        "specialist_activation": "unverified",
        "workflow_ready": False,
        "authorization_header_supplied": False,
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        receipt.update(probe(Transport()))
        exit_code = 0
    except ProbeError as error:
        receipt.update(status="blocked", error=str(error))
        exit_code = 2
    receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
    rendered = json.dumps(receipt, indent=2) + "\n"
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(rendered)
        except OSError as error:
            print(f"Cannot save receipt: {error}", file=sys.stderr)
            return 1
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
