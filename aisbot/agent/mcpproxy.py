import asyncio
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, List

import httpx
from loguru import logger
from aisbot.agent.tools.base import Tool

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession


def _create_http_client() -> httpx.AsyncClient:
    """Create an httpx client configured for MCP HTTP transport.

    Uses HTTP/1.1 only and explicitly disables proxies to avoid
    issues with system proxy settings (e.g., macOS network proxy).
    """
    return httpx.AsyncClient(
        http1=True,
        http2=False,
        follow_redirects=True,
        proxy=None,  # Explicitly disable proxy
    )


class MCPProxyTool(Tool):
    """
    MCP Proxy Tool
    - Loads MCP server configs from config.yaml
    - Can call any MCP server/tool dynamically
    - Fetches tool list + parameters + common usage for LLM guidance
    """

    def __init__(self, config_file: str | Path = "config.yaml"):
        self.config_file = Path(config_file)
        self.servers: Dict[str, Dict[str, Any]] = {}
        self._tool_info_cache: Dict[
            str, List[dict]
        ] = {}  # server_name -> list of tool info dicts
        self._load_config()

    @property
    def name(self) -> str:
        return "mcp_proxy"

    @property
    def description(self) -> str:
        return (
            "Proxy tool to call any MCP server/tool dynamically and provide "
            "full summary of tools (parameters, usage) to LLM."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["call", "summary"],
                    "description": "Call a tool or get summary for LLM",
                },
                "server": {"type": "string", "description": "MCP server name"},
                "tool_name": {"type": "string", "description": "Tool to call"},
                "arguments": {"type": "object", "description": "Tool arguments"},
            },
            "required": ["action"],
        }

    def _load_config(self):
        if not self.config_file.exists():
            raise FileNotFoundError(f"MCP config file not found: {self.config_file}")

        with open(self.config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.servers = data.get("mcp_servers", {})
        if not self.servers:
            raise ValueError("No MCP servers configured in config.yaml")

    async def execute(
        self,
        action: str,
        server: Optional[str] = None,
        tool_name: Optional[str] = None,
        arguments: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        if action == "summary":
            return await self._generate_summary()

        if action != "call":
            return f"Error: Unsupported action '{action}'"

        if not server or not tool_name:
            return "Error: 'server' and 'tool_name' are required for 'call'"

        if server not in self.servers:
            return f"Error: MCP server '{server}' not found"

        cfg = self.servers[server]
        transport = cfg.get("transport", "stdio")
        arguments = arguments or {}

        if transport == "stdio":
            return await self._call_stdio(cfg, tool_name, arguments)
        elif transport == "http":
            return await self._call_http(cfg, tool_name, arguments)
        else:
            return f"Error: Unsupported transport '{transport}'"

    async def _call_stdio(self, cfg: dict, tool_name: str, args: dict) -> str:
        try:
            from mcp.types import TextContent

            command = cfg.get("command", "mcp_binary")
            cmd_args = cfg.get("args", [])
            params = StdioServerParameters(command=command, args=cmd_args)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=args)
                    if result.content and isinstance(result.content[0], TextContent):
                        return result.content[0].text
                    elif result.content:
                        return str(result.content[0])
                    return "(no output)"
        except Exception as e:
            return f"STDIO MCP error: {str(e)}"

    async def _call_http(self, cfg: dict, tool_name: str, args: dict) -> str:
        try:
            from mcp.types import TextContent

            url = cfg["url"]
            client = _create_http_client()
            async with client:
                async with streamable_http_client(url=url, http_client=client) as (
                    reader,
                    writer,
                    _get_session_id,
                ):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        result = await session.call_tool(tool_name, arguments=args)
                        if result.content and isinstance(result.content[0], TextContent):
                            return result.content[0].text
                        elif result.content:
                            return str(result.content[0])
                        return "(no output)"
        except Exception as e:
            return f"HTTP MCP error: {str(e)}"

    async def _generate_summary(self) -> str:
        """
        Generate detailed summary of all MCP servers for LLM:
        - Server name, transport, description
        - Tool names
        - Tool parameters
        - Common usage
        """
        summaries = []

        for server_name, cfg in self.servers.items():
            transport = cfg.get("transport", "stdio")
            desc = cfg.get("description", "")
            summary = f"- {server_name} ({transport})"
            if desc:
                summary += f": {desc}"

            # Fetch tools and parameters
            if server_name not in self._tool_info_cache:
                self._tool_info_cache[server_name] = await self._fetch_tools(cfg)

            tools = self._tool_info_cache.get(server_name, [])
            tool_lines = []
            for tool in tools:
                line = f"    Tool: {tool.get('name')}"
                if tool.get("description"):
                    line += f"\n      Description: {tool['description']}"
                if tool.get("parameters"):
                    line += f"\n      Parameters: {tool['parameters']}"
                if tool.get("usage"):
                    line += f"\n      Common Usage: {tool['usage']}"
                tool_lines.append(line)

            if tool_lines:
                summary += "\n" + "\n".join(tool_lines)

            summaries.append(summary)

        return "Registered MCP servers & tools:\n" + "\n".join(summaries)

    async def _fetch_tools(self, cfg: dict) -> List[dict]:
        """
        Fetch list of tools from MCP server.
        Returns list of dicts with name, description, parameters, common usage.
        Fail gracefully if server is unreachable.
        """
        transport = cfg.get("transport", "stdio")
        tools_info = []

        try:
            if transport == "stdio":
                command = cfg.get("command", "mcp_binary")
                cmd_args = cfg.get("args", [])
                params = StdioServerParameters(command=command, args=cmd_args)
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        tools_result = await session.list_tools()
                        for t in tools_result.tools:
                            meta = getattr(t, "_meta", None) or {}
                            usage = meta.get("usage") if meta else None
                            tools_info.append(
                                {
                                    "name": t.name,
                                    "description": t.description or "",
                                    "parameters": t.inputSchema,
                                    "usage": usage,
                                }
                            )

            elif transport == "http":
                url = cfg["url"]
                logger.info(f"Connecting to HTTP MCP server at {url}")
                try:
                    client = _create_http_client()
                    async with client:
                        async with streamable_http_client(url=url, http_client=client) as (
                            reader,
                            writer,
                            _get_session_id,
                        ):
                            async with ClientSession(reader, writer) as session:
                                await session.initialize()
                                tools_result = await session.list_tools()
                                for t in tools_result.tools:
                                    meta = getattr(t, "_meta", None) or {}
                                    usage = meta.get("usage") if meta else None
                                    tools_info.append(
                                        {
                                            "name": t.name,
                                            "description": t.description or "",
                                            "parameters": t.inputSchema,
                                            "usage": usage,
                                        }
                                    )
                except Exception as e:
                    logger.error(f"HTTP MCP connection error: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    raise
        except Exception as e:
            # Fail gracefully; LLM can still see other servers
            if transport == "http":
                logger.error(f"Failed to fetch tools from HTTP MCP server: {e}")
            pass

        return tools_info
