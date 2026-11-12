import importlib.util
import contextlib
import io
import http.client
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "probe_microchip", Path(__file__).resolve().parents[1] / "probe_microchip.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def action():
    return {
        "name": probe.ACTION,
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        },
    }


def payload():
    return {"success": True, "data": {"documents": [{"content": probe.HANDBOOK}]}}


class FakeTransport:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
        self.protocol = None

    def send(self, method, params=None, notification=False):
        self.calls.append((method, params, notification))
        return next(self.replies)


class ProbeTests(unittest.TestCase):
    def test_complete_protocol_is_not_specialist_activation(self):
        transport = FakeTransport([
            {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}},
            None,
            {"tools": [action()]},
            {"content": [{"type": "text", "text": json.dumps(payload())}]},
        ])
        result = probe.probe(transport)
        self.assertEqual(result["status"], "endpoint_pass")
        self.assertFalse(result["handbook_downloaded_or_read"])
        self.assertEqual([c[0] for c in transport.calls],
                         ["initialize", "notifications/initialized", "tools/list", "tools/call"])
        self.assertEqual(transport.calls[-1][1]["arguments"], probe.QUERY)

    def test_json_and_sse_responses(self):
        message = {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}
        encoded = json.dumps(message).encode()
        self.assertEqual(probe.decode_response(encoded, "application/json", 7), {"tools": []})
        sse = b": keepalive\r\nevent: message\r\ndata: " + encoded + b"\r\n\r\n"
        self.assertEqual(probe.decode_response(sse, "text/event-stream; charset=utf-8", 7),
                         {"tools": []})

    def test_protocol_errors_fail_closed(self):
        for message in (
            {"jsonrpc": "2.0", "id": 2, "result": {}},
            {"jsonrpc": "2.0", "id": True, "result": {}},
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -1}},
            {"id": 1, "result": {}},
            {"jsonrpc": "2.0", "id": 1, "result": None},
        ):
            with self.subTest(message=message), self.assertRaises(probe.ProbeError):
                probe.decode_response(json.dumps(message).encode(), "application/json", 1)

    def test_duplicate_sse_response_rejected(self):
        response = b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
        with self.assertRaises(probe.ProbeError):
            probe.decode_response(response * 2, "text/event-stream", 1)

    def test_pagination_completes_inventory(self):
        transport = FakeTransport([
            {"tools": [], "nextCursor": "next"},
            {"tools": [action()]},
        ])
        self.assertEqual(probe.find_action(transport)["name"], probe.ACTION)
        self.assertEqual(transport.calls[-1][1], {"cursor": "next"})

    def test_pagination_cycle_missing_and_duplicate_actions_rejected(self):
        for replies in (
            [{"tools": []}],
            [{"tools": [action(), action()]}],
            [{"tools": [], "nextCursor": "x"}, {"tools": [], "nextCursor": "x"}],
            [{"tools": {}, "nextCursor": None}],
        ):
            with self.subTest(replies=replies), self.assertRaises(probe.ProbeError):
                probe.find_action(FakeTransport(replies))

    def test_valid_schema(self):
        probe.check_schema(action())

    def test_changed_schema_rejected(self):
        for replacement in (
            {"type": "array"},
            {"type": "object", "required": [{}], "properties": {}},
            {"type": "object", "required": ["partNumber"], "properties": {}},
            {"type": "object", "properties": {"query": {"type": "number"}}},
            {"type": "object", "properties": {
                "query": {"type": "string"}, "limit": {"type": "integer", "maximum": 5}}},
        ):
            with self.subTest(schema=replacement), self.assertRaises(probe.ProbeError):
                probe.check_schema({"inputSchema": replacement})

    def test_application_failure_and_irrelevant_results_rejected(self):
        for result in (
            {"isError": True, "structuredContent": payload()},
            {"isError": "false", "structuredContent": payload()},
            {"structuredContent": {"success": False}},
            {"structuredContent": {"success": "true", "data": {"documents": []}}},
            {"structuredContent": {"success": True, "data": {"documents": []}}},
            {"structuredContent": {"success": True, "data": {"documents": [{"url": "https://example.com"}]}}},
            {"content": [{"type": "text", "text": "not JSON"}]},
        ):
            with self.subTest(result=result), self.assertRaises(probe.ProbeError):
                probe.application_result(result)

    def test_structured_application_success(self):
        self.assertEqual(probe.application_result({"structuredContent": payload()}), 1)

    def test_redirect_is_not_followed(self):
        with self.assertRaises(probe.ProbeError):
            probe.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")

    def test_existing_receipt_refused_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            receipt.write_text("retain", encoding="utf-8")
            with patch.object(probe, "Transport") as transport:
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                    probe.main(["--output", str(receipt)])
                transport.assert_not_called()
            self.assertEqual(receipt.read_text(encoding="utf-8"), "retain")

    def test_failure_receipt_is_persistent_and_not_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            with patch.object(probe, "probe", side_effect=probe.ProbeError("blocked")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(["--output", str(receipt)]), 2)
            result = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertFalse(result["workflow_ready"])
            self.assertEqual(result["specialist_activation"], "unverified")
            self.assertEqual(result["status"], "blocked")

    def test_truncated_chunked_http_response_saves_blocked_receipt(self):
        body = (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
            b"Content-Type: application/json\r\n\r\n5\r\nabc"
        )
        socket = SimpleNamespace(makefile=lambda *args: io.BytesIO(body))
        response = http.client.HTTPResponse(socket)
        response.begin()
        opener = SimpleNamespace(open=lambda *args, **kwargs: response)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "truncated.json"
            with patch.object(probe.urllib.request, "build_opener", return_value=opener), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(probe.main(["--output", str(receipt)]), 2)
            result = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "blocked")
            self.assertIn("IncompleteRead", result["error"])
            self.assertFalse(result["workflow_ready"])


if __name__ == "__main__":
    unittest.main()
