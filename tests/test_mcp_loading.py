import sys
from pathlib import Path

import pytest

from aisbot.agent.loop import AgentLoop
from aisbot.providers.base import BaseProvider


class _DummyBus:
    async def publish_outbound(self, msg):  # noqa: ANN001
        return None

    async def publish_inbound(self, msg):  # noqa: ANN001
        return None


class _DummyProvider(BaseProvider):
    async def completions(self, **kwargs):  # noqa: ANN003
        raise NotImplementedError

    def get_default_model(self) -> str:
        return "dummy"


@pytest.mark.asyncio
async def test_agent_loop_loads_mcp_proxy_from_workspace_config(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "\n".join(
            [
                "mcp_servers:",
                "  math:",
                "    transport: stdio",
                "    command: " + sys.executable,
                "    args:",
                "      - -m",
                "      - aisbot.mcp_server",
                "",
            ]
        ),
        encoding="utf-8",
    )

    agent = AgentLoop(
        bus=_DummyBus(),  # type: ignore[arg-type]
        provider=_DummyProvider(),
        workspace=tmp_path,
    )

    assert agent.tools.has("mcp_proxy")

    result = await agent.tools.execute(
        "mcp_proxy",
        {
            "action": "call",
            "server": "math",
            "tool_name": "add",
            "arguments": {"a": 1, "b": 2},
        },
    )
    assert result.strip() == "3"

