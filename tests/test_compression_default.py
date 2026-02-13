"""Test that compression is enabled by default."""

from aisbot.agent.compression import CompressionConfig, ContextCompressor
from aisbot.config.schema import ToolsConfig


def test_compression_config_default_enabled():
    """Test that CompressionConfig enables compression by default."""
    config = CompressionConfig()

    assert config.enabled is True, "Compression should be enabled by default"
    assert config.strategy == "semantic", "Default strategy should be 'semantic'"
    assert config.max_context_tokens == 16000
    assert config.target_context_tokens == 12000
    assert config.recent_messages_keep == 10


def test_tools_config_default_compression():
    """Test that ToolsConfig includes compression enabled by default."""
    tools_config = ToolsConfig()

    assert tools_config.compression.enabled is True, "ToolsConfig should have compression enabled by default"
    assert tools_config.compression.strategy == "semantic"


def test_compression_can_be_disabled():
    """Test that compression can be explicitly disabled."""
    config = CompressionConfig(enabled=False)

    assert config.enabled is False, "Compression should be disableable"


def test_compression_config_from_dict():
    """Test loading compression config from dictionary."""
    data = {
        "enabled": True,
        "strategy": "truncation",
        "max_context_tokens": 8000,
        "recent_messages_keep": 5
    }

    config = CompressionConfig(**data)

    assert config.enabled is True
    assert config.strategy == "truncation"
    assert config.max_context_tokens == 8000
    assert config.recent_messages_keep == 5


if __name__ == "__main__":
    test_compression_config_default_enabled()
    test_tools_config_default_compression()
    test_compression_can_be_disabled()
    test_compression_config_from_dict()
    print("All default compression tests passed!")
