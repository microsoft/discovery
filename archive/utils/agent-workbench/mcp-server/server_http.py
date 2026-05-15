#!/usr/bin/env python3
"""HTTP wrapper for the Discovery MCP Server to work in Codespaces/web environments.
This wraps the existing stdio-based server with an HTTP/SSE transport layer.
"""
import sys
import os
import logging
import json

# Add the workbench directory to the path
workbench_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, workbench_dir)

# Import the existing server
from server import DiscoveryMCPServer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MCP SDK HTTP server
try:
    from mcp.server import Server
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import Response
    import uvicorn
    import asyncio
    HAS_MCP_SDK = True
except ImportError as e:
    logger.error(f"Missing MCP SDK dependencies: {e}")
    logger.error("Install with: pip install mcp starlette uvicorn")
    HAS_MCP_SDK = False
    sys.exit(1)

# Create MCP server using SDK
mcp_server = Server("discovery-workbench")
discovery_server_instance = None

async def get_discovery_server():
    """Get or create the discovery server instance"""
    global discovery_server_instance
    if discovery_server_instance is None:
        discovery_server_instance = DiscoveryMCPServer()
        await discovery_server_instance._ensure_initialized()
    return discovery_server_instance

@mcp_server.list_tools()
async def list_tools():
    """List available tools"""
    ds = await get_discovery_server()
    return ds.tools

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Call a tool"""
    ds = await get_discovery_server()
    try:
        result = await ds._handle_tool_call(name, arguments)
        return [{"type": "text", "text": json.dumps(result, indent=2)}]
    except Exception as e:
        logger.error(f"Error calling tool {name}: {e}", exc_info=True)
        return [{"type": "text", "text": f"Error: {str(e)}"}]

# Create Starlette app with SSE endpoint
async def handle_sse(request):
    """Handle SSE connections"""
    from starlette.responses import StreamingResponse
    from sse_starlette import EventSourceResponse
    
    async def event_stream():
        async with SseServerTransport("/message") as transport:
            try:
                async with mcp_server.run_sse(transport) as streams:
                    async for message in streams[0]:
                        yield message
            except Exception as e:
                logger.error(f"SSE error: {e}", exc_info=True)
                yield {"event": "error", "data": str(e)}
    
    return EventSourceResponse(event_stream())

async def health_check(request):
    """Health check endpoint"""
    return Response(json.dumps({"status": "healthy", "server": "discovery-workbench"}), 
                   media_type="application/json")

app = Starlette(
    routes=[
        Route("/health", endpoint=health_check),
        Route("/sse", endpoint=handle_sse),
    ],
    debug=True
)

def main():
    """Start HTTP server"""
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    logger.info(f"Starting Discovery MCP HTTP server on {host}:{port}")
    logger.info(f"SSE endpoint: http://{host}:{port}/sse")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )

if __name__ == "__main__":
    main()
