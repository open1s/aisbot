# aisbot

A lightweight AI assistant with multi-provider LLM support and MCP (Model Context Protocol) integration.

## Features

- **Multi-Provider LLM Support**: Flexible provider architecture supporting OpenAI, Anthropic, NVIDIA, and custom endpoints through LiteLLM
- **MCP Integration**: Support for Model Context Protocol tools with both HTTP and stdio transports
- **Message Bus Architecture**: Async message routing system for scalable multi-channel communication
- **Tool Registry**: Extensible tool system with built-in filesystem, shell, web search, and MCP proxy tools
- **Session Management**: Persistent conversation sessions with history tracking
- **Cron Tasks**: Scheduled task execution for automation
- **Multiple Channels**: Support for Telegram, Discord, WhatsApp, and Feishu

## Architecture

```
aisbot/
├── agent/          # Core agent logic
│   ├── loop.py     # Agent loop (LLM ↔ tool execution)
│   ├── context.py  # Context builder
│   ├── mcpproxy.py # MCP proxy tool
│   └── tools/      # Built-in tools
├── bus/            # Message routing (DBus + SQlite)
│   ├── events.py   # Message types
│   ├── queue.py    # DBus message queue
│   └── squeue.py  # SQLite queue
├── channels/       # Chat app integrations
├── cli/            # Command-line interface
├── config/         # Configuration management
├── cron/           # Scheduled tasks
├── providers/      # LLM providers
│   ├── base.py          # Abstract base provider
│   ├── provider.py      # Provider factory
│   └── liteprovider.py # LiteLLM implementation
└── session/        # Conversation sessions
```

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd aisbot

# Install with uv (recommended)
uv sync

# Or install dependencies
pip install -e .
```

### Configuration

Create `~/.aisbot/config.json`:

```json
{
  "providers": {
    "openai": {
      "apiKey": "sk-...",
      "apiBase": "https://api.openai.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "gpt-4"
    }
  }
}
```

### Running the Agent

```bash
# Single message
uv run python -m aisbot agent -m "Hello, world!"

# Interactive mode
uv run python -m aisbot agent

# Start gateway
uv run python -m aisbot gateway
```

## Provider System

### Architecture

aisbot uses a flexible provider registration system:

1. **ProviderFactory**: Central factory that manages multiple LLM providers
2. **BaseProvider**: Abstract base class defining the provider interface
3. **Provider Registration**: Providers register themselves with a name and model matching logic

### Registering a New Provider

```python
from aisbot.providers.base import BaseProvider
from aisbot.providers.provider import ProviderFactory
from litellm import completion

class OpenAIProvider(BaseProvider):
    name = "openai"

    @classmethod
    def match_model(cls, model: str) -> bool:
        return model.startswith("gpt-")

    def get_default_model(self) -> str:
        return "gpt-4"

    async def completions(self, **kwargs):
        return completion(**kwargs)

# Register the provider
ProviderFactory.register_provider(OpenAIProvider)
```

### Supported Providers

| Provider | Model Pattern | Status |
|----------|---------------|--------|
| `litellm` | `nvidia/*`, `z-ai/*` | ✓ Built-in |
| `openai` | `gpt-*`, `o1-*` | Example |
| `anthropic` | `claude-*` | Example |
| `custom` | `custom/*` | Example |

### Custom API Endpoints

Use any OpenAI-compatible endpoint:

```json
{
  "providers": {
    "vllm": {
      "apiKey": "dummy",
      "apiBase": "http://localhost:8000/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "meta-llama/Llama-3.1-8B-Instruct"
    }
  }
}
```

## MCP (Model Context Protocol) Integration

aisbot integrates MCP via a single built-in tool: `mcp_proxy`.

### MCP Config (`config.yaml`)

The agent will try to load MCP servers from the first `config.yaml` it finds (in this order):

1. `AISBOT_MCP_CONFIG` (explicit path)
2. `<workspace>/config.yaml`
3. `./config.yaml` (current working directory)
4. `~/.aisbot/config.yaml`

File format:

```yaml
mcp_servers:
  local_math:
    transport: stdio
    description: Local demo MCP server
    command: python
    args:
      - -m
      - aisbot.mcp_server

  weather:
    transport: http
    description: Remote MCP server over HTTP/SSE
    url: http://localhost:3000/mcp
```

### Using `mcp_proxy`

`mcp_proxy` supports:

- `action: summary` to list available MCP servers/tools (best for giving the LLM context)
- `action: call` to call a specific tool on a configured server

Example call:

```json
{
  "action": "call",
  "server": "local_math",
  "tool_name": "add",
  "arguments": { "a": 1, "b": 2 }
}
```

### Running MCP Server

Create a simple MCP server:

```python
# aisbot/mcp_math.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("math")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers"""
    return a + b

if __name__ == "__main__":
    mcp.run()  # stdio mode
```

## CLI Commands

| Command | Description |
|----------|-------------|
| `uv run python -m aisbot agent -m "..."` | Send single message |
| `uv run python -m aisbot agent` | Interactive chat mode |
| `uv run python -m aisbot gateway` | Start message gateway |
| `uv run python -m aisbot status` | Show system status |

## Built-in Tools

- **File Tools**: `read_file`, `write_file`, `edit_file`, `list_dir`
- **Shell Tool**: `exec` - Execute shell commands
- **Web Tools**: `web_search`, `web_fetch`
- **Message Tool**: `message` - Send messages via channels
- **Spawn Tool**: `spawn` - Create background subagent tasks
- **Cron Tool**: `cron` - Schedule tasks
- **MCP Proxy Tool**: `mcp_proxy` - Call MCP server tools dynamically

## Configuration

### Config Location

`~/.aisbot/config.json`

### Provider Configuration

```json
{
  "providers": {
    "openai": {
      "apiKey": "sk-...",
      "apiBase": "https://api.openai.com/v1"
    },
    "anthropic": {
      "apiKey": "sk-ant-..."
    },
    "nvidia": {
      "apiKey": "nvapi-..."
    }
  }
}
```

### Agent Configuration

```json
{
  "agents": {
    "defaults": {
      "model": "gpt-4",
      "maxTokens": 4096,
      "temperature": 0.7
    },
    "restrictToWorkspace": false,
    "maxIterations": 20
  }
}
```

### Security Options

| Option | Default | Description |
|---------|---------|-------------|
| `agents.restrictToWorkspace` | `false` | Restrict file tools to workspace directory |
| `tools.restrictToWorkspace` | `false` | Restrict exec tool to workspace |
| `channels.*.allowFrom` | `[]` | Allow list of user IDs (empty = all) |

## Development

### Project Structure

```
aisbot/
├── agent/              # Core agent logic
│   ├── loop.py         # Main agent loop
│   ├── context.py      # Context builder
│   ├── tools/         # Tool implementations
│   │   ├── base.py         # Tool base class
│   │   ├── registry.py     # Tool registry
│   │   ├── filesystem.py   # File operations
│   │   ├── shell.py        # Shell execution
│   │   ├── web.py          # Web search/fetch
│   │   ├── message.py      # Message sending
│   │   ├── spawn.py       # Subagent spawning
│   │   └── cron.py        # Scheduled tasks
│   └── mcpproxy.py     # MCP proxy tool
├── bus/                # Message bus
│   ├── events.py       # Message dataclasses
│   ├── queue.py       # DBus queue
│   └── squeue.py      # SQLite queue
├── channels/           # Chat app integrations
├── cli/               # CLI commands
├── config/            # Configuration
├── cron/              # Cron service
├── heartbeat/          # Heartbeat service
├── providers/          # LLM providers
│   ├── base.py            # Abstract provider
│   ├── provider.py        # Provider factory
│   └── liteprovider.py    # LiteLLM provider
├── session/           # Session management
└── skills/            # External skills
```

### Testing

```bash
# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=aisbot

# Run specific test
uv run pytest tests/test_squeue_consume_outbound.py
```

### Linting

```bash
# Check for errors
ruff check aisbot

# Format code
ruff format aisbot
```

## Dependencies

- **Python**: >=3.12
- **LiteLLM**: Multi-provider LLM support
- **MCP**: Model Context Protocol client
- **Pydantic**: Data validation
- **Loguru**: Logging
- **Typer**: CLI framework
- **Rich**: Terminal formatting

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Roadmap

- [ ] Multi-modal support (images, voice, video)
- [ ] Long-term memory with vector database
- [ ] Advanced reasoning and multi-step planning
- [ ] More channel integrations (Slack, Email, Calendar)
- [ ] Self-improvement from feedback
- [ ] Streaming responses
- [ ] Tool result caching
