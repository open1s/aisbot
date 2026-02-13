# AGENTS.md

This file provides guidelines for agentic coding in the aisbot repository.

## Build / Lint / Test Commands

### Installation
```bash
uv sync
```

### Running Tests
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_squeue_consume_outbound.py

# Run with coverage
uv run pytest --cov=aisbot
```

### Linting and Formatting
```bash
# Check for errors
ruff check aisbot

# Format code
ruff format aisbot
```

## Code Style Guidelines

### Imports
- Group imports in order: standard library, third-party, local (aisbot)
- Use explicit imports: `from typing import Any` instead of `import typing`

```python
import asyncio
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel

from aisbot.bus.events import InboundMessage
from aisbot.providers.base import BaseProvider
```

### Type Hints
- Use Python 3.12+ Union syntax: `str | None`, `dict[str, Any]`, `list[str]`
- Forward references with quotes: `config: "ExecToolConfig | None" = None`

### Naming Conventions
- Classes: `PascalCase` - `AgentLoop`, `BaseProvider`
- Functions/methods: `snake_case` - `execute()`
- Variables: `snake_case` - `session_key`
- Constants: `UPPER_SNAKE_CASE` - `_GATEWAY_DEFAULTS`
- Private members: Leading underscore - `_allowed_dir`

### Classes and Data Structures
- Use `@dataclass` for simple data containers with `field(default_factory=list)`
- Use abstract base classes for interfaces: `class BaseProvider(ABC)`
- ContextBuilder accepts optional compressor parameter for context compression

```python
@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]
```

### Async/Await
- All I/O operations should use `async`/`await`
- Use `asyncio.TimeoutError` for timeout handling
- Use `asyncio.wait_for()` for timeout-based operations

### Error Handling
- Tool methods return error messages as strings for graceful handling
- Use `logger.error()` for logging errors

```python
async def execute(self, path: str, **kwargs: Any) -> str:
    try:
        file_path = _resolve_path(path, self._allowed_dir)
        if not file_path.exists():
            return f"Error: File not found: {path}"
        return file_path.read_text(encoding="utf-8")
    except PermissionError as e:
        return f"Error: {e}"
```

### Docstrings
- Classes: Multi-line docstring explaining purpose and usage
- Methods: Args/Returns style for public methods

```python
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

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).

        Args:
            content: The message content.
            session_key: Session identifier.

        Returns:
            The agent's response.
        """
```

### Logging
- Use `from loguru import logger`
- Log levels: `logger.info()`, `logger.error()`, `logger.debug()`

```python
logger.info("Agent loop started")
logger.error(f"Error processing message: {e}")
```

### Configuration
- Use `pydantic.BaseModel` for configuration schemas
- Use `pydantic.Field` with `default_factory` for mutable defaults
- Place config in `aisbot/config/schema.py`

### Tools
- Extend `aisbot.agent.tools.base.Tool`
- Implement `name`, `description`, `parameters`, `execute` properties/methods
- Return results as strings

### Tool Source Field
The `source` field identifies where a tool comes from:
- `None` or `"local"`: Built-in local tools (filesystem, shell, web, etc.)
- `"mcp"`: MCP server tools
- `"skill"`: Tools from SKILLS directory

### MCP Tool Naming Convention
MCP tools use their original names from the MCP server. The `source` field is used to identify MCP tools.
- If a tool name conflicts with a local tool, the server name is prefixed: `<server>_<tool>`
- Example: `calculator` (from math server), `weather` (from weather server)
- Conflict example: `math_calculator` (if calculator already exists locally)

## Project Structure
```
aisbot/
├── agent/          # Core agent logic
│   ├── loop.py
│   ├── context.py
│   └── tools/      # Tool implementations
├── bus/            # Message routing
├── channels/       # Chat integrations
├── cli/            # CLI commands
├── config/         # Pydantic schemas
├── cron/           # Scheduled tasks
├── providers/      # LLM providers
└── session/        # Session management
```
