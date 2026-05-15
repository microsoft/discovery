# The base URL of the MCP server
DEFAULT_SERVER_URL = "http://server:80"

# example MCP client utilities
import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.sse import sse_client
import httpx  # Required for SSE client transport


@asynccontextmanager
async def open_session(server_url: str):
    """Async context manager that yields an initialized ClientSession connected to the MCP server.

    Usage:
        async with open_session(url) as session:
            await session.list_tools()
    """
    async with sse_client(server_url.rstrip("/") + "/sse") as (read, write):
        async with ClientSession(read, write) as session:
            # Ensure session is initialized before returning it to callers
            await session.initialize()
            try:
                yield session
            finally:
                # Any cleanup (ClientSession and sse_client contexts handle closing)
                pass


# Helper: JSON normalization ------------------------------------------------
def _to_jsonable(obj: Any) -> Any:
    """Convert various kinds of objects into JSON-serializable Python primitives.

    - Preserves dicts, lists, tuples, primitives
    - Calls common conversion helpers like to_dict()/dict()
    - Falls back to vars(obj) for objects with attributes
    - As a last resort, coerces to a JSON string representation
    """
    # Primitives
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    # Mapping
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    # Sequences
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]
    # Objects with explicit conversion
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            return _to_jsonable(obj.to_dict())
        except Exception:
            pass
    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return _to_jsonable(obj.dict())
        except Exception:
            pass
    # Generic object -> vars
    if hasattr(obj, "__dict__"):
        try:
            return _to_jsonable(vars(obj))
        except Exception:
            pass
    # Try JSON roundtrip with default=str to coerce unknown objects into strings
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return str(obj)


# Async functions -------------------------------------------------------------
async def list_tools_async(server_url: str) -> List[Dict[str, Any]]:
    async with open_session(server_url) as session:
        tools = await session.list_tools()
        # tools.tools is expected to be a list-like object
        return [_to_jsonable(t) for t in tools.tools]


async def list_resources_async(server_url: str) -> List[Dict[str, Any]]:
    async with open_session(server_url) as session:
        resources = await session.list_resources()
        return [_to_jsonable(r) for r in resources.resources]


async def list_resource_templates_async(server_url: str) -> List[Dict[str, Any]]:
    async with open_session(server_url) as session:
        templates = await session.list_resource_templates()
        return [_to_jsonable(t) for t in templates.resourceTemplates]


async def list_prompts_async(server_url: str) -> List[Dict[str, Any]]:
    async with open_session(server_url) as session:
        prompts = await session.list_prompts()
        return [_to_jsonable(p) for p in prompts.prompts]


async def call_tool_async(server_url: str, tool_name: str, args: Optional[Dict[str, Any]] = None) -> Any:
    """Call a named tool on the MCP server with optional JSON-serializable args.

    Returns the raw response from the MCP session call_tool method converted into
    JSON-serializable Python primitives (dicts/lists/primitives).
    """
    args = args or {}
    async with open_session(server_url) as session:
        result = await session.call_tool(tool_name, args)
        return _to_jsonable(result)


async def read_resource_async(server_url: str, resource_id: str) -> Any:
    async with open_session(server_url) as session:
        result = await session.read_resource(resource_id)
        return _to_jsonable(result)


# Synchronous wrappers so functions can be invoked from regular scripts/CLI ----
def list_tools(server_url: str = DEFAULT_SERVER_URL) -> List[Dict[str, Any]]:
    return asyncio.run(list_tools_async(server_url))


def list_resources(server_url: str = DEFAULT_SERVER_URL) -> List[Dict[str, Any]]:
    return asyncio.run(list_resources_async(server_url))


def list_resource_templates(server_url: str = DEFAULT_SERVER_URL) -> List[Dict[str, Any]]:
    return asyncio.run(list_resource_templates_async(server_url))


def list_prompts(server_url: str = DEFAULT_SERVER_URL) -> List[Dict[str, Any]]:
    return asyncio.run(list_prompts_async(server_url))


def call_tool(server_url: str, tool_name: str, args: Optional[Dict[str, Any]] = None) -> Any:
    return asyncio.run(call_tool_async(server_url, tool_name, args))


def read_resource(server_url: str, resource_id: str) -> Any:
    return asyncio.run(read_resource_async(server_url, resource_id))


# Helper: parse args from CLI
def parse_kv_or_json(s: Optional[str]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    s = s.strip()
    # If it looks like JSON, parse it
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON provided for args")
    # Otherwise parse simple key=value pairs separated by commas
    result: Dict[str, Any] = {}
    for part in s.split(","):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            v = v.strip()
            # Try to interpret v as JSON (numbers, booleans, null, arrays, objects)
            try:
                parsed = json.loads(v)
            except Exception:
                parsed = v
            result[k] = parsed
        else:
            # Positional values are given incrementally
            result[part.strip()] = True
    return result


def pretty_print(obj: Any) -> None:
    try:
        print(json.dumps(obj, indent=2, default=str))
    except Exception:
        print(str(obj))


# Command-line interface -----------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MCP example client: generalized helpers and CLI")
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER_URL, help="Base URL of MCP server")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-tools", help="List available tools on the MCP server")
    subparsers.add_parser("list-resources", help="List available resources on the MCP server")
    subparsers.add_parser("list-resource-templates", help="List resource templates on the MCP server")
    subparsers.add_parser("list-prompts", help="List prompts on the MCP server")

    call_tool_p = subparsers.add_parser("call-tool", help="Call a tool by name")
    call_tool_p.add_argument("tool_name", help="Name of the tool to call")
    call_tool_p.add_argument("--args", help="Tool arguments as JSON or comma-separated key=value list")

    read_res_p = subparsers.add_parser("read-resource", help="Read a resource by id")
    read_res_p.add_argument("resource_id", help="Resource identifier (e.g. greeting://Doug)")

    return parser


def main_cli(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    ns = parser.parse_args(argv)

    server = ns.server

    try:
        if ns.command == "list-tools":
            tools = list_tools(server)
            pretty_print(tools)

        elif ns.command == "list-resources":
            resources = list_resources(server)
            pretty_print(resources)

        elif ns.command == "list-resource-templates":
            templates = list_resource_templates(server)
            pretty_print(templates)

        elif ns.command == "list-prompts":
            prompts = list_prompts(server)
            pretty_print(prompts)

        elif ns.command == "call-tool":
            args = parse_kv_or_json(ns.args)
            result = call_tool(server, ns.tool_name, args)
            # The MCP result objects often contain a content/contents field
            pretty_print(result)

        elif ns.command == "read-resource":
            result = read_resource(server, ns.resource_id)
            pretty_print(result)

        else:
            parser.print_help()

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main_cli()