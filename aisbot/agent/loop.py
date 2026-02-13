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
from aisbot.agent.compression import CompressionConfig, ContextCompressor
from aisbot.agent.tools.registry import ToolRegistry
from aisbot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from aisbot.agent.tools.shell import ExecTool
from aisbot.agent.tools.web import WebSearchTool, WebFetchTool
from aisbot.agent.tools.message import MessageTool
from aisbot.agent.tools.spawn import SpawnTool
from aisbot.agent.tools.cron import CronTool
from aisbot.agent.subagent import SubagentManager
from aisbot.agent.mcpproxy import MCPProxyTool
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
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        # Initialize compression from config if available
        self.compressor = None
        if provider:
            try:
                from aisbot.config.loader import load_config
                config = load_config()
                compression_config = config.tools.compression
                self.compressor = ContextCompressor(provider, compression_config)
            except Exception as e:
                logger.warning(f"Failed to load compression config: {e}")
                # Fallback to default config
                compression_config = CompressionConfig()
                self.compressor = ContextCompressor(provider, compression_config)

        self.context = ContextBuilder(workspace, self.compressor)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )
        
        self._running = False
        self._mcp_proxy: MCPProxyTool | None = None
        self._register_default_tools_sync()
        self._load_mcp_proxy_sync()

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
        self.tools.register(WebSearchTool(api_key=None))
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

    def _load_mcp_proxy_sync(self) -> None:
        """Load MCP proxy tool synchronously (config loading only, no server connection)."""
        # Find MCP config file
        mcp_config_env = os.environ.get("AISBOT_MCP_CONFIG")
        mcp_config_candidates = []
        if mcp_config_env:
            mcp_config_candidates.append(Path(mcp_config_env).expanduser())

        mcp_config_candidates.extend([
            self.workspace / "config.yaml",
            Path.cwd() / "config.yaml",
            Path.home() / ".aisbot" / "config.yaml",
        ])

        for mcp_config_file in mcp_config_candidates:
            if not mcp_config_file.exists():
                continue
            try:
                self._mcp_proxy = MCPProxyTool(config_file=mcp_config_file)
                self.tools.register(self._mcp_proxy)
                break
            except Exception as e:
                logger.error(f"Failed to load MCP from {mcp_config_file}: {e}")

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")

        # Preload MCP tools info
        if self._mcp_proxy:
            await self._mcp_proxy.preload_tools()

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

        # Log before compression
        history = session.get_history()
        if self.compressor and self.compressor.config.enabled:
            original_tokens = self.compressor._estimate_tokens(history) if history else 0
        messages, compression_stats = await self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            tools_summary=tools_summary,
            provider=self.provider,
            model=self.model
        )

        # Log compression stats in detail
        if compression_stats:
            original = compression_stats.get("original_tokens", 0)
            if compression_stats.get("compressed"):
                final = compression_stats.get("final_tokens", 0)
                reduction = compression_stats.get("reduction", 0)
                percent = compression_stats.get("reduction_percent", 0)
                logger.info(
                    f"[Compression] After: {original} -> {final} tokens "
                    f"(saved {reduction}, {percent:.1f}% reduction)"
                )
            else:
                reason = compression_stats.get("reason", "unknown")
        else:
            logger.info("[Compression] No stats returned (compressor may be disabled)")
        
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

                    result = await self.tools.execute(tool_call.name, tool_call.arguments)

                    # Compress long tool results
                    if len(result) > 1000 and self.compressor:
                        original_len = len(result)
                        result = await self.context.compress_tool_result(result, self.provider)
                        logger.info(
                            f"[Compression] Tool result '{tool_call.name}': "
                            f"{original_len} -> {len(result)} chars "
                            f"({(1 - len(result)/original_len)*100:.1f}% reduction)"
                        )

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
        messages, _ = await self.context.build_messages(
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
        # Preload MCP tools if not done yet
        if self._mcp_proxy and not self._mcp_proxy._tool_info_cache:
            await self._mcp_proxy.preload_tools()

        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )

        response = await self._process_message(msg)
        return response.content if response else ""

