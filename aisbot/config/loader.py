"""Configuration loading utilities."""

from pathlib import Path
from typing import Any

import yaml
from aisbot.config.schema import Config


def get_config_path() -> Path:
    """Get the default configuration file path."""
    return Path.home() / ".aisbot" / "config.yaml"


def get_data_dir() -> Path:
    """Get the aisbot data directory."""
    from aisbot.utils.helpers import get_data_path

    return get_data_path()


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data = _migrate_config(data)
            return Config.model_validate(data)
        except (yaml.YAMLError, ValueError) as e:
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(exclude_none=True)

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


def generate_schema_yaml() -> str:
    """Generate YAML schema with comments from Config model."""
    schema = """# aisbot Configuration
# =====================

# Agent configuration
agents:
  defaults:
    workspace: ~/.aisbot/workspace  # Working directory for file operations
    model: anthropic/claude-opus-4-5  # Default LLM model
    max_tokens: 8192  # Maximum tokens in response
    temperature: 0.7  # Response randomness (0.0-1.0)
    max_tool_iterations: 20  # Maximum tool call iterations

# Channel configurations
channels:
  # WhatsApp channel (requires bridge)
  whatsapp:
    enabled: false
    bridge_url: ws://localhost:3001
    allow_from: []  # Allowed phone numbers

  # Telegram channel
  telegram:
    enabled: false
    token: ""  # Bot token from @BotFather
    allow_from: []  # Allowed user IDs or usernames
    proxy: null  # HTTP/SOCKS5 proxy, e.g. "http://127.0.0.1:7890"

  # Feishu/Lark channel
  feishu:
    enabled: false
    app_id: ""
    app_secret: ""
    encrypt_key: ""
    verification_token: ""
    allow_from: []  # Allowed user open_ids

  # Discord channel
  discord:
    enabled: false
    token: ""  # Bot token from Discord Developer Portal
    allow_from: []  # Allowed user IDs
    gateway_url: wss://gateway.discord.gg/?v=10&encoding=json
    intents: 37377  # GUILDS + GUILD_MESSAGES + DIRECT_MESSAGES + MESSAGE_CONTENT

# LLM Provider configurations
providers:
  anthropic:
    api_key: ""
    api_base: null
    extra_headers: null

  openai:
    api_key: ""
    api_base: null
    extra_headers: null

  openrouter:
    api_key: ""
    api_base: https://openrouter.ai/api/v1
    extra_headers: null

  deepseek:
    api_key: ""
    api_base: null
    extra_headers: null

  groq:
    api_key: ""
    api_base: null
    extra_headers: null

  zhipu:
    api_key: ""
    api_base: null
    extra_headers: null

  dashscope:  # 阿里云通义千问
    api_key: ""
    api_base: null
    extra_headers: null

  vllm:
    api_key: ""
    api_base: null
    extra_headers: null

  gemini:
    api_key: ""
    api_base: null
    extra_headers: null

  moonshot:
    api_key: ""
    api_base: null
    extra_headers: null

  aihubmix:  # AiHubMix API gateway
    api_key: ""
    api_base: https://aihubmix.com/v1
    extra_headers: null

# Gateway/server configuration
gateway:
  host: 0.0.0.0
  port: 18790

# Tools configuration
tools:
  web:
    search:
      api_key: ""  # Optional, DuckDuckGo doesn't require
      max_results: 5

  exec:
    timeout: 60  # Shell command timeout in seconds

  restrict_to_workspace: false  # Restrict file access to workspace

  compression:
    enabled: true
    max_context_tokens: 16000  # Start compressing above this
    target_context_tokens: 12000  # Target tokens after compression
    recent_messages_keep: 10  # Always keep recent messages
    history_compression_threshold: 20  # Start compressing beyond this
    strategy: semantic  # Options: "summary", "truncation", "semantic"
    min_content_length: 200  # Minimum content length to compress
    preserve_system_prompt_cache: true  # Cache system prompt
"""
    return schema


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrict_to_workspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrict_to_workspace" not in tools:
        tools["restrict_to_workspace"] = exec_cfg.pop("restrictToWorkspace")
    return data
