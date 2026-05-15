#!/usr/bin/env python3
"""
Script to list all tools and resources provided by the ai-infrastructure-mcp server.
"""
import asyncio

from ai_infrastructure_mcp.server import build_server


async def list_tools_and_resources():
    server = build_server()
    tools = await server.get_tools()

    print("AI Infrastructure MCP Server Tools")
    print("=" * 50)
    print(f"Total tools available: {len(tools)}")
    print()

    for i, (tool_name, tool_info) in enumerate(tools.items(), 1):
        print(f"{i}. {tool_name}")
        print(f"   Description: {tool_info.description}")
        print()


if __name__ == "__main__":
    asyncio.run(list_tools_and_resources())
