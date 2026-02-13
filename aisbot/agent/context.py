"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
from pathlib import Path
from typing import Any

from loguru import logger

from aisbot.agent.memory import MemoryStore
from aisbot.agent.skills import SkillsLoader
from aisbot.agent.compression import ContextCompressor, CompressionConfig


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.

    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(self, workspace: Path, compressor: ContextCompressor | None = None):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        self.compressor = compressor
    
    async def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        tools_summary: str | None = None,
        provider: Any | None = None
    ) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.

        Args:
            skill_names: Optional list of skills to include.
            tools_summary: Optional summary of available tools.
            provider: LLM provider for compression.

        Returns:
            Complete system prompt.
        """
        parts = []
        content_sources = {}

        # Core identity
        identity = self._get_identity()
        parts.append(identity)
        content_sources["identity"] = identity

        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
            content_sources["bootstrap"] = bootstrap

        # Tools summary
        if tools_summary:
            parts.append(tools_summary)
            content_sources["tools"] = tools_summary

        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            memory_section = f"# Memory\n\n{memory}"
            parts.append(memory_section)
            content_sources["memory"] = memory

        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                skills_section = f"# Active Skills\n\n{always_content}"
                parts.append(skills_section)
                content_sources["always_skills"] = always_content

        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary_section = self.skills.build_skills_summary()
        if skills_summary_section:
            available_skills_section = f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary_section}"""
            parts.append(available_skills_section)
            content_sources["skills_summary"] = skills_summary_section

        system_prompt = "\n\n---\n\n".join(parts)

        # Apply compression if configured
        if self.compressor and provider:
            system_prompt = await self.compressor.compress_system_prompt(
                system_prompt,
                content_sources
            )

        return system_prompt
    
    def _get_identity(self) -> str:
        """Get the core identity section."""
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        
        return f"""# aisbot 🐈

You are aisbot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
{now}

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []
        
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""

    def build_tools_summary(self, tools_registry: Any) -> str:
        """
        Build a summary of available tools organized by source.

        Args:
            tools_registry: The ToolRegistry instance.

        Returns:
            Formatted summary of available tools.
        """
        from collections import defaultdict

        # Group tools by source
        tools_by_source = defaultdict(list)
        mcp_proxy = None
        for tool_name, tool in tools_registry._tools.items():
            if tool_name == "mcp_proxy":
                mcp_proxy = tool
                continue  # Handle MCP proxy separately
            source = getattr(tool, "source", None) or "local"
            description = getattr(tool, "description", "")
            tools_by_source[source].append((tool_name, description))

        parts = ["# Available Tools\n"]

        # Local tools
        if "local" in tools_by_source:
            parts.append("## Local Tools\n")
            for tool_name, description in tools_by_source["local"]:
                parts.append(f"- **{tool_name}**: {description}")
            parts.append("")

        # MCP tools section (show cached info if available)
        if mcp_proxy:
            parts.append("## MCP Tools\n")
            # Check if we have cached tool info
            if mcp_proxy._tool_info_cache:
                for server_name, tools_info in mcp_proxy._tool_info_cache.items():
                    if tools_info:
                        parts.append(f"### {server_name}\n")
                        for t in tools_info:
                            desc = t.get("description", "")[:80]
                            parts.append(f"- **{t.get('name')}**: {desc}")
                        parts.append("")
            else:
                # No cache yet, show how to get MCP tools
                servers = list(getattr(mcp_proxy, "servers", {}).keys())
                if servers:
                    parts.append("MCP servers configured (tools not yet loaded):\n")
                    for s in servers:
                        parts.append(f"- {s}")
                    parts.append("\nUse `mcp_proxy` with action='summary' to list available MCP tools.\n")

        # MCP tools from registry (old style, if any)
        if "mcp" in tools_by_source:
            parts.append("## MCP Tools (Registered)\n")
            for tool_name, description in tools_by_source["mcp"]:
                parts.append(f"- **{tool_name}**: {description}")
            parts.append("")

        # Skill tools
        if "skill" in tools_by_source:
            parts.append("## Skill Tools\n")
            parts.append("Tools from skills directory:\n")
            for tool_name, description in tools_by_source["skill"]:
                parts.append(f"- **{tool_name}**: {description}")
            parts.append("")

        # Other sources
        for source in sorted(tools_by_source.keys()):
            if source not in ("local", "mcp", "skill"):
                parts.append(f"## {source.title()} Tools\n")
                for tool_name, description in tools_by_source[source]:
                    parts.append(f"- **{tool_name}**: {description}")
                parts.append("")

        return "\n".join(parts)

    async def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        tools_summary: str | None = None,
        provider: Any | None = None,
        model: str | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """
        Build the complete message list for an LLM call.

        Args:
            history: Previous conversation messages.
            current_message: The new user message.
            skill_names: Optional skills to include.
            media: Optional list of local file paths for images/media.
            channel: Current channel (telegram, feishu, etc.).
            chat_id: Current chat/user ID.
            tools_summary: Optional summary of available tools.
            provider: LLM provider for compression.
            model: Model name for token limit checks.

        Returns:
            Tuple of (messages, compression_stats).
        """
        messages = []

        # System prompt
        system_prompt = await self.build_system_prompt(skill_names, tools_summary, provider)
        if channel and chat_id:
            system_prompt += f"\n\n## Current Session\nChannel: {channel}\nChat ID: {chat_id}"
        messages.append({"role": "system", "content": system_prompt})

        # History
        messages.extend(history)

        # Current message (with optional image attachments)
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        # Apply compression if configured
        compression_stats = None
        if self.compressor:
            messages, compression_stats = await self.compressor.compress_messages(messages, model)

        return messages, compression_stats

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text
        
        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        
        if not images:
            return text
        return images + [{"type": "text", "text": text}]
    
    async def compress_tool_result(self, result: str, provider: Any | None = None) -> str:
        """
        Compress tool result if it's too long.

        Args:
            result: Tool execution result.
            provider: LLM provider for compression.

        Returns:
            Compressed result if needed.
        """
        if not self.compressor or not provider:
            return result

        # Only compress very long results
        if len(result) < 1000:
            return result

        strategy = self.compressor.get_strategy(self.compressor.config.strategy)
        if strategy:
            compressed = await strategy.compress(result, target_ratio=0.4)
            logger.debug(f"Tool result compressed: {len(result)} -> {len(compressed)} chars")
            return compressed

        return result

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        Add a tool result to the message list.

        Args:
            messages: Current message list.
            tool_call_id: ID of the tool call.
            tool_name: Name of the tool.
            result: Tool execution result.

        Returns:
            Updated message list.
        """
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages
    
    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        Add an assistant message to the message list.
        
        Args:
            messages: Current message list.
            content: Message content.
            tool_calls: Optional tool calls.
        
        Returns:
            Updated message list.
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        messages.append(msg)
        return messages
