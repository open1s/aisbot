# 🤖 aisbot: Lightweight AI Assistant with MCP Integration

**aisbot** is a **lightweight** AI assistant with multi-provider LLM support and MCP (Model Context Protocol) integration. Inspired by [Nanobot](https://github.com/HKUDS/nanobot) ⚡️

## Key Features

🪶 **Lightweight**: Clean, readable codebase that's easy to understand, modify, and extend.

🔌 **MCP Integration**: Full support for Model Context Protocol tools with both HTTP and stdio transports.

🤖 **Multi-Provider LLM**: Flexible provider architecture supporting OpenAI, Anthropic, NVIDIA, DeepSeek, and custom endpoints through LiteLLM.

📱 **Multi-Channel**: Support for Telegram, Discord, WhatsApp, and Feishu.

🛠️ **Extensible Tools**: Built-in filesystem, shell, web search, MCP proxy, and spawn tools.

💾 **Context Compression**: Automatic token usage reduction for longer conversations.

⏰ **Cron Tasks**: Scheduled task execution for automation.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Chat Channels                           │
│     Telegram │ Discord │ WhatsApp │ Feishu │ CLI           │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Message Bus (DBus + SQLite)               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     Agent Loop                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Context   │──│     LLM     │──│   Tool Execution    │  │
│  │   Builder   │  │  Providers  │  │   (MCP + Built-in)  │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 📦 Install

**Install from source** (recommended for development):

```bash
git clone https://github.com/yourusername/aisbot.git
cd aisbot
uv sync
```

**Install with pip**:

```bash
pip install -e .
```

## 🚀 Quick Start

> [!TIP]
> Set your API key in `~/.aisbot/config.yaml`.
> Get API keys: [OpenAI](https://platform.openai.com) · [Anthropic](https://console.anthropic.com) · [OpenRouter](https://openrouter.ai)

**1. Configure** (`~/.aisbot/config.yaml`)

```yaml
providers:
  openai:
    api_key: "sk-..."

agents:
  defaults:
    model: gpt-4
```

**2. Chat**

```bash
# Single message
uv run python -m aisbot agent -m "Hello, world!"

# Interactive mode
uv run python -m aisbot agent
```

That's it! You have a working AI assistant.

## 🖥️ Local Models (vLLM)

Run aisbot with your own local models using vLLM or any OpenAI-compatible server.

**1. Start your vLLM server**

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000
```

**2. Configure** (`~/.aisbot/config.yaml`)

```yaml
providers:
  vllm:
    api_key: "dummy"
    api_base: "http://localhost:8000/v1"

agents:
  defaults:
    model: "meta-llama/Llama-3.1-8B-Instruct"
```

## 💬 Chat Apps

Talk to your aisbot through Telegram, Discord, WhatsApp, or Feishu — anytime, anywhere.

| Channel | Setup |
|---------|-------|
| **Telegram** | Easy (just a token) |
| **Discord** | Easy (bot token + intents) |
| **WhatsApp** | Medium (scan QR) |
| **Feishu** | Medium (app credentials) |

### Telegram (Recommended)

**1. Create a bot**
- Open Telegram, search `@BotFather`
- Send `/newbot`, follow prompts
- Copy the token

**2. Configure**

```yaml
channels:
  telegram:
    enabled: true
    token: "YOUR_BOT_TOKEN"
    allow_from:
      - "YOUR_USER_ID"
```

**3. Run**

```bash
uv run python -m aisbot gateway
```

### Discord

**1. Create a bot**
- Go to https://discord.com/developers/applications
- Create an application → Bot → Add Bot
- Copy the bot token
- Enable **MESSAGE CONTENT INTENT**

**2. Configure**

```yaml
channels:
  discord:
    enabled: true
    token: "YOUR_BOT_TOKEN"
    allow_from:
      - "YOUR_USER_ID"
```

**3. Run**

```bash
uv run python -m aisbot gateway
```

### WhatsApp

Requires **Node.js ≥18**.

**1. Link device**

```bash
uv run python -m aisbot channels login
# Scan QR with WhatsApp → Settings → Linked Devices
```

**2. Configure**

```yaml
channels:
  whatsapp:
    enabled: true
    allow_from:
      - "+1234567890"
```

### Feishu (飞书)

Uses **WebSocket** long connection — no public IP required.

**1. Create a Feishu bot**
- Visit [Feishu Open Platform](https://open.feishu.cn/app)
- Create a new app → Enable **Bot** capability
- Get **App ID** and **App Secret**

**2. Configure**

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "allowFrom": []
    }
  }
}
```

## 🔌 MCP Integration

aisbot integrates MCP via a built-in `mcp_proxy` tool.

### MCP Config (`config.yaml`)

The agent loads MCP servers from (in order):
1. `AISBOT_MCP_CONFIG` (explicit path)
2. `<workspace>/config.yaml`
3. `./config.yaml` (current working directory)
4. `~/.aisbot/config.yaml`

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

```json
{
  "action": "call",
  "server": "local_math",
  "tool_name": "add",
  "arguments": { "a": 1, "b": 2 }
}
```

## ⚙️ Configuration

Config file: `~/.aisbot/config.json`

### Providers

| Provider | Purpose | Get API Key |
|----------|---------|-------------|
| `openai` | LLM (GPT) | [platform.openai.com](https://platform.openai.com) |
| `anthropic` | LLM (Claude) | [console.anthropic.com](https://console.anthropic.com) |
| `openrouter` | LLM (all models) | [openrouter.ai](https://openrouter.ai) |
| `deepseek` | LLM (DeepSeek) | [platform.deepseek.com](https://platform.deepseek.com) |
| `nvidia` | LLM (NVIDIA NIM) | [build.nvidia.com](https://build.nvidia.com) |
| `vllm` | LLM (local) | — |

### Security

| Option | Default | Description |
|--------|---------|-------------|
| `agents.restrictToWorkspace` | `false` | Restrict file tools to workspace directory |
| `tools.restrictToWorkspace` | `false` | Restrict exec tool to workspace |
| `channels.*.allowFrom` | `[]` | Whitelist of user IDs (empty = all) |

## 📋 CLI Reference

| Command | Description |
|---------|-------------|
| `python -m aisbot agent -m "..."` | Send single message |
| `python -m aisbot agent` | Interactive chat mode |
| `python -m aisbot gateway` | Start message gateway |
| `python -m aisbot status` | Show system status |
| `python -m aisbot channels login` | Link WhatsApp |

Interactive mode exits: `exit`, `quit`, `/exit`, `/quit`, `:q`, or `Ctrl+D`.

## 🛠️ Built-in Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `write_file` | Write file contents |
| `edit_file` | Edit file with diff |
| `list_dir` | List directory contents |
| `exec` | Execute shell commands |
| `web_search` | Search the web |
| `web_fetch` | Fetch web content |
| `message` | Send messages via channels |
| `spawn` | Create background subagent tasks |
| `cron` | Schedule tasks |
| `mcp_proxy` | Call MCP server tools |

## 🐳 Docker

```bash
# Build the image
docker build -t aisbot .

# Run agent
docker run -v ~/.aisbot:/root/.aisbot --rm aisbot agent -m "Hello!"

# Run gateway
docker run -v ~/.aisbot:/root/.aisbot -p 18790:18790 aisbot gateway
```

## 📁 Project Structure

```
aisbot/
├── agent/              # Core agent logic
│   ├── loop.py         # Agent loop (LLM ↔ tool execution)
│   ├── context.py      # Context builder
│   ├── compression.py  # Context compression
│   ├── subagent.py     # Background task execution
│   ├── mcpproxy.py     # MCP proxy tool
│   └── tools/          # Built-in tools
├── bus/                # Message routing (DBus + SQLite)
├── channels/           # Chat app integrations
├── cli/                # Command-line interface
├── config/             # Configuration management
├── cron/               # Scheduled tasks
├── heartbeat/          # Heartbeat service
├── providers/          # LLM providers
├── session/            # Conversation sessions
└── skills/             # External skills
```

## 🔧 Development

### Testing

```bash
# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=aisbot
```

### Linting

```bash
ruff check aisbot
ruff format aisbot
```

## 🤝 Contributing

PRs welcome! The codebase is intentionally clean and readable.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 🗺️ Roadmap

- [ ] Multi-modal support (images, voice, video)
- [ ] Long-term memory with vector database
- [ ] Advanced reasoning and multi-step planning
- [ ] More channel integrations (Slack, Email, Calendar)
- [ ] Self-improvement from feedback
- [ ] Streaming responses
- [ ] Tool result caching

## 🙏 Acknowledgments

This project is inspired by [Nanobot](https://github.com/HKUDS/nanobot) - an ultra-lightweight personal AI assistant (~4,000 lines of core code) with multi-channel support and MCP integration.

Key concepts adapted:
- Ultra-lightweight agent architecture
- Multi-provider LLM abstraction
- Message bus and session management
- Skill system format and metadata structure

## 📄 License

MIT License - see LICENSE file for details.
