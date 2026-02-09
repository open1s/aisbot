import asyncio
from typing import Any, Dict, List

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession


async def fetch_mcp_tools_stdio(
    command: str,
    args: list[str],
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Fetch tool metadata from an MCP stdio server.
    Normalized + safe for LLM guidance usage.
    """
    tools_info: List[Dict[str, Any]] = []

    params = StdioServerParameters(
        command=command,
        args=args,
    )

    try:
        async with asyncio.timeout(timeout):
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()

                    for item in tools:
                        # MCP SDK returns (name, tool_schema)
                        if isinstance(item, tuple):
                            name, tool = item
                        else:
                            name = getattr(item, "name", "<unknown>")
                            tool = item

                        tools_info.append({
                            "name": name,
                            "description": getattr(tool, "description", "") or "",
                            # MCP uses input_schema, not parameters
                            "parameters": getattr(tool, "input_schema", {}) or {},
                            "common_usage": getattr(tool, "common_usage", None),
                        })

    except TimeoutError:
        return [{
            "error": "timeout",
            "message": "MCP server did not respond in time",
        }]
    except Exception as e:
        return [{
            "error": "connection_failed",
            "message": str(e),
        }]

    return tools_info

import asyncio
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def main():
    params = StdioServerParameters(
        command="python",
        args=["-m", "aisbot.mcp_server"],
    )

    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()

            user_tools = []
            for name, tool in tools:
                # Skip internal MCP commands
                if name == "tools":
                    for t in tool:
                        info = {
                            "name": t.name,
                            "description": getattr(t, "description", {}),
                            "parameters": getattr(t, "inputSchema", {}),
                            "output": getattr(t, "outputSchema", {}),
                            "usage": getattr(t, "meta", {}).get("usage"),
                        }
                        user_tools.append(info)

    print("Available user MCP tools:")
    for t in user_tools:
        print(t)

if __name__ == "__main__":
    asyncio.run(main())
