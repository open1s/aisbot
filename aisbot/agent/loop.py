"""Agent loop: the core processing engine."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from aisbot.bus.events import InboundMessage, OutboundMessage
from aisbot.bus.squeue import MessageBus
from aisbot.providers.base import BaseProvider
from aisbot.agent.context import ContextBuilder
from aisbot.agent.tools.registry import ToolRegistry
from aisbot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from aisbot.agent.tools.shell import ExecTool
from aisbot.agent.tools.web import WebSearchTool, WebFetchTool
from aisbot.agent.tools.message import MessageTool
from aisbot.agent.tools.spawn import SpawnTool
from aisbot.agent.tools.cron import CronTool
from aisbot.agent.subagent import SubagentManager
from aisbot.session.manager import SessionManager


class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: BaseProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from aisbot.config.schema import ExecToolConfig
        from aisbot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        
        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )
        
        self._running = False
        self._register_default_tools_sync()

    async def initialize(self) -> None:
        """Initialize the agent loop. Register MCP tools for LLM access."""
        await self._register_mcp_tools_async()

    def _register_default_tools_sync(self) -> None:
        """Register the default set of tools (synchronous part)."""
        # File tools (restrict to workspace if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(allowed_dir=allowed_dir))

        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))

        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())

        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)

        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)

        # Cron tool (for scheduling)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

        # Load MCP proxy tool (synchronous)
        mcp_config_env = os.environ.get("AISBOT_MCP_CONFIG")
        mcp_config_candidates = []
        if mcp_config_env:
            mcp_config_candidates.append(Path(mcp_config_env).expanduser())
        
        mcp_config_candidates.extend(
            [
                self.workspace / "config.yaml",
                Path.cwd() / "config.yaml",
                Path.home() / ".aisbot" / "config.yaml",
            ]
        )

        for mcp_config_file in mcp_config_candidates:
            if not mcp_config_file.exists():
                continue
            try:
                from aisbot.agent.mcpproxy import MCPProxyTool

                mcp_proxy = MCPProxyTool(config_file=mcp_config_file)
                self.tools.register(mcp_proxy)
                logger.info(f"Loaded MCP tools from {mcp_config_file}")
                break
            except Exception as e:
                logger.error(f"Failed to load MCP tools from {mcp_config_file}: {e}")

    async def _register_mcp_tools_async(self) -> None:
        """Register individual MCP tools for direct LLM access (asynchronous)."""
        mcp_proxy = self.tools.get("mcp_proxy")
        if not mcp_proxy:
            return

        from aisbot.agent.mcpproxy import MCPProxyTool

        if not isinstance(mcp_proxy, MCPProxyTool):
            return

        # Check if MCP tools are already registered to avoid redundant work
        # Look for any tool with "mcp" source field
        mcp_tools_already_registered = any(
            getattr(tool, "source", None) == "mcp"
            for tool in self.tools._tools.values()
        )
        if mcp_tools_already_registered:
            logger.debug("MCP tools already registered, skipping re-registration")
            return

        await self._register_mcp_tools(mcp_proxy)

    async def _execute_mcp_tool(self, tool_call: Any, tool: Any) -> str:
        """
        Execute an MCP tool call with function verification.

        Args:
            tool_call: Tool call request with name and arguments.
            tool: The MCP tool wrapper object.

        Returns:
            Tool execution result as string.
        """
        from aisbot.agent.mcpproxy import MCPProxyTool

        # Get MCP metadata from tool
        server_name = getattr(tool, "_server_name", None)
        mcp_tool_name = getattr(tool, "_mcp_tool_name", None)
        transport = getattr(tool, "_transport", None)

        if not server_name or not mcp_tool_name or not transport:
            return f"Error: Invalid MCP tool metadata for '{tool_call.name}'"

        # Get MCP proxy tool
        mcp_proxy = self.tools.get("mcp_proxy")
        if not isinstance(mcp_proxy, MCPProxyTool):
            return "Error: MCP proxy tool not available"

        # Verify server exists
        if server_name not in mcp_proxy.servers:
            available_servers = ", ".join(mcp_proxy.servers.keys())
            return f"Error: MCP server '{server_name}' not found. Available servers: {available_servers}"

        # Verify tool exists on server
        if server_name not in mcp_proxy._tool_info_cache:
            # Fetch tools if not cached
            cfg = mcp_proxy.servers[server_name]
            mcp_proxy._tool_info_cache[server_name] = await mcp_proxy._fetch_tools(cfg)

        server_tools = mcp_proxy._tool_info_cache.get(server_name, [])
        tool_info = None
        for t in server_tools:
            if t.get("name") == mcp_tool_name:
                tool_info = t
                break

        if not tool_info:
            available_tools = ", ".join(t.get("name", "?") for t in server_tools)
            return f"Error: Tool '{mcp_tool_name}' not found on server '{server_name}'. Available tools: {available_tools}"

        # Verify parameters against tool schema
        params_schema = tool_info.get("parameters", {})
        validation_errors = self._validate_mcp_params(tool_call.arguments, params_schema)
        if validation_errors:
            return f"Error: Parameter validation failed for '{mcp_tool_name}': " + "; ".join(validation_errors)

        # Execute the MCP tool
        try:
            if transport == "stdio":
                result = await mcp_proxy._call_stdio(
                    mcp_proxy.servers[server_name],
                    mcp_tool_name,
                    tool_call.arguments
                )
            elif transport == "http":
                result = await mcp_proxy._call_http(
                    mcp_proxy.servers[server_name],
                    mcp_tool_name,
                    tool_call.arguments
                )
            else:
                return f"Error: Unsupported transport '{transport}'"
            return result
        except Exception as e:
            return f"Error executing MCP tool '{mcp_tool_name}': {str(e)}"

    def _validate_mcp_params(
        self,
        params: dict[str, Any],
        schema: dict[str, Any]
    ) -> list[str]:
        """
        Validate parameters against MCP tool schema.

        Args:
            params: Parameters to validate.
            schema: JSON Schema for parameters.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []

        if not schema or schema.get("type") != "object":
            return errors

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        # Check required parameters
        for req in required:
            if req not in params:
                errors.append(f"Missing required parameter: '{req}'")

        # Check parameter types
        for param_name, param_value in params.items():
            if param_name not in properties:
                errors.append(f"Unknown parameter: '{param_name}'")
                continue

            param_schema = properties[param_name]
            param_type = param_schema.get("type")

            if param_type == "string":
                if not isinstance(param_value, str):
                    errors.append(f"Parameter '{param_name}' must be string, got {type(param_value).__name__}")
            elif param_type == "number":
                if not isinstance(param_value, (int, float)):
                    errors.append(f"Parameter '{param_name}' must be number, got {type(param_value).__name__}")
            elif param_type == "integer":
                if not isinstance(param_value, int):
                    errors.append(f"Parameter '{param_name}' must be integer, got {type(param_value).__name__}")
            elif param_type == "boolean":
                if not isinstance(param_value, bool):
                    errors.append(f"Parameter '{param_name}' must be boolean, got {type(param_value).__name__}")
            elif param_type == "array":
                if not isinstance(param_value, list):
                    errors.append(f"Parameter '{param_name}' must be array, got {type(param_value).__name__}")
            elif param_type == "object":
                if not isinstance(param_value, dict):
                    errors.append(f"Parameter '{param_name}' must be object, got {type(param_value).__name__}")

        return errors

    async def _register_mcp_tools(self, mcp_proxy: Any) -> None:
        """
        Register individual MCP tools for direct LLM access.

        Each MCP tool is registered with its original name from the MCP server.
        The source field is used to identify MCP tools.

        Args:
            mcp_proxy: The MCPProxyTool instance.
        """
        for server_name, cfg in mcp_proxy.servers.items():
            transport = cfg.get("transport", "stdio")

            # Fetch tools from server
            if server_name not in mcp_proxy._tool_info_cache:
                mcp_proxy._tool_info_cache[server_name] = await mcp_proxy._fetch_tools(cfg)

            tools = mcp_proxy._tool_info_cache.get(server_name, [])

            for tool in tools:
                tool_name = tool.get("name")
                if not tool_name:
                    continue

                # Use the original tool name from MCP server
                # Add prefix if tool name conflicts with local tools
                full_tool_name = f"{server_name}_{tool_name}"
                if self.tools.has(full_tool_name):
                    # Tool already registered, skip to avoid conflicts
                    logger.debug(f"MCP tool already registered: {full_tool_name} (from {server_name})")
                    continue

                # Register as a wrapper tool
                self.tools.register(_MCPToolWrapper(
                    name=full_tool_name,
                    description=tool.get("description", ""),
                    parameters=tool.get("parameters", {}),
                    mcp_proxy=mcp_proxy,
                    server_name=server_name,
                    mcp_tool_name=tool_name,
                    transport=transport,
                ))
                logger.info(f"Registered MCP tool: {full_tool_name} (from {server_name})")

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")

        # Register MCP tools if not already initialized
        # For optimal performance, call initialize() before run()
        mcp_tools_already_registered = any(
            getattr(tool, "source", None) == "mcp"
            for tool in self.tools._tools.values()
        )
        if not mcp_tools_already_registered:
            logger.debug("MCP tools not initialized, registering now")
            await self._register_mcp_tools_async()

        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.
        
        Args:
            msg: The inbound message to process.
        
        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}: {preview}")
        
        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)
        
        # Build initial messages (use get_history for LLM-formatted messages)
        tools_summary = self.context.build_tools_summary(self.tools)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            tools_summary=tools_summary,
        )
        
        # Agent loop
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")

                    # Check if tool is MCP tool via source field
                    tool = self.tools.get(tool_call.name)
                    if tool and getattr(tool, "source", None) == "mcp":
                        result = await self._execute_mcp_tool(tool_call, tool)
                    else:
                        result = await self.tools.execute(tool_call.name, tool_call.arguments)

                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "I've completed processing but have no response to give."
        
        # Log response preview
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info(f"Response to {msg.channel}:{msg.sender_id}: {preview}")
        
        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content
        )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)
        
        # Build messages with the announce content
        tools_summary = self.context.build_tools_summary(self.tools)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
            tools_summary=tools_summary,
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")

                    # Check if tool is MCP tool via source field
                    tool = self.tools.get(tool_call.name)
                    if tool and getattr(tool, "source", None) == "mcp":
                        result = await self._execute_mcp_tool(tool_call, tool)
                    else:
                        result = await self.tools.execute(tool_call.name, tool_call.arguments)

                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).

        Note: MCP tools should be registered once during startup, not here.
        See AgentLoop.run() or CLI initialization for MCP registration.

        Args:
            content: The message content.
            session_key: Session identifier.
            channel: Source channel (for context).
            chat_id: Source chat ID (for context).

        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )

        response = await self._process_message(msg)
        return response.content if response else ""


class _MCPToolWrapper:
    """
    Wrapper for individual MCP tools to expose them to the LLM.

    Each wrapper represents a single tool from an MCP server and provides
    the standard Tool interface. The source field identifies MCP tools.
    """

    source = "mcp"  # Field to identify MCP tools

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        mcp_proxy: Any,
        server_name: str,
        mcp_tool_name: str,
        transport: str,
    ):
        self._name = name
        self._description = description
        self._parameters = parameters
        self._mcp_proxy = mcp_proxy
        self._server_name = server_name
        self._mcp_tool_name = mcp_tool_name
        self._transport = transport

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    def to_schema(self) -> dict[str, Any]:
        """Convert to OpenAI tool schema format."""
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self._description,
                "parameters": self._parameters,
            },
        }

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate parameters against the tool schema."""
        errors = []

        if not self._parameters or self._parameters.get("type") != "object":
            return errors

        properties = self._parameters.get("properties", {})
        required = set(self._parameters.get("required", []))

        # Check required parameters
        for req in required:
            if req not in params:
                errors.append(f"Missing required parameter: '{req}'")

        # Check parameter types
        for param_name, param_value in params.items():
            if param_name not in properties:
                errors.append(f"Unknown parameter: '{param_name}'")
                continue

            param_schema = properties[param_name]
            param_type = param_schema.get("type")

            if param_type == "string":
                if not isinstance(param_value, str):
                    errors.append(f"Parameter '{param_name}' must be string, got {type(param_value).__name__}")
            elif param_type == "number":
                if not isinstance(param_value, (int, float)):
                    errors.append(f"Parameter '{param_name}' must be number, got {type(param_value).__name__}")
            elif param_type == "integer":
                if not isinstance(param_value, int):
                    errors.append(f"Parameter '{param_name}' must be integer, got {type(param_value).__name__}")
            elif param_type == "boolean":
                if not isinstance(param_value, bool):
                    errors.append(f"Parameter '{param_name}' must be boolean, got {type(param_value).__name__}")
            elif param_type == "array":
                if not isinstance(param_value, list):
                    errors.append(f"Parameter '{param_name}' must be array, got {type(param_value).__name__}")
            elif param_type == "object":
                if not isinstance(param_value, dict):
                    errors.append(f"Parameter '{param_name}' must be object, got {type(param_value).__name__}")

        return errors

    async def execute(self, **kwargs: Any) -> str:
        """Execute the MCP tool."""
        try:
            if self._transport == "stdio":
                result = await self._mcp_proxy._call_stdio(
                    self._mcp_proxy.servers[self._server_name],
                    self._mcp_tool_name,
                    kwargs
                )
            elif self._transport == "http":
                result = await self._mcp_proxy._call_http(
                    self._mcp_proxy.servers[self._server_name],
                    self._mcp_tool_name,
                    kwargs
                )
            else:
                return f"Error: Unsupported transport '{self._transport}'"
            return result
        except Exception as e:
            return f"Error executing MCP tool '{self._mcp_tool_name}': {str(e)}"

