"""Tests for context compression functionality."""

import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock

import pytest

from aisbot.agent.compression import (
    ContextCompressor,
    CompressionConfig,
    SummaryStrategy,
    TruncationStrategy,
    SemanticStrategy,
    SystemPromptCache,
)


class MockProvider:
    """Mock LLM provider for testing."""

    def __init__(self, response_content: str = "Mock summary"):
        self.response_content = response_content
        self.chat_call_count = 0

    async def chat(self, **kwargs):
        self.chat_call_count += 1
        mock_response = MagicMock()
        mock_response.content = self.response_content
        return mock_response


class TestCompressionStrategies:
    """Test compression strategies."""

    @pytest.mark.asyncio
    async def test_truncation_strategy(self):
        """Test truncation strategy."""
        strategy = TruncationStrategy()

        # Test normal truncation
        content = "This is a test. " * 50
        compressed = await strategy.compress(content, target_ratio=0.5)

        assert len(compressed) < len(content)
        assert compressed.endswith("...")

        # Test short content (should not compress) - under 100 chars
        short_content = "Short"
        compressed_short = await strategy.compress(short_content, target_ratio=0.5)
        assert compressed_short == short_content

        # Test token estimation
        tokens = strategy.estimate_tokens(content)
        assert tokens > 0

    @pytest.mark.asyncio
    async def test_semantic_strategy(self):
        """Test semantic compression strategy."""
        strategy = SemanticStrategy(preserve_code=True)

        # Create sufficiently long content with sections (over 500 chars)
        content = ("# Header 1\n" + "This is important content. " * 50 + "\n\n" +
                  "# Header 2\n" + "This is also important. " * 50 + "\n\n" +
                  "# Header 3\n" + "This is less important filler text that goes on and on. " * 50)
        compressed = await strategy.compress(content, target_ratio=0.6)

        assert len(compressed) < len(content)
        # Should preserve headers
        assert "# Header" in compressed

        # Test code preservation
        content_with_code = """
Normal text here.

```python
def test():
    return "code"
```

More text.
""" * 5
        strategy_with_code = SemanticStrategy(preserve_code=True)
        compressed_with_code = await strategy_with_code.compress(content_with_code, target_ratio=0.8)

        assert "```python" in compressed_with_code

    @pytest.mark.asyncio
    async def test_summary_strategy(self):
        """Test summary strategy."""
        provider = MockProvider()
        strategy = SummaryStrategy(provider)

        content = "This is a long piece of content that needs summarization. " * 50
        compressed = await strategy.compress(content, target_ratio=0.5)

        # Should call provider
        assert compressed == "Mock summary"

        # Test short content (no compression) - under 400 chars
        short_content = "Short"
        compressed_short = await strategy.compress(short_content, target_ratio=0.5)
        assert compressed_short == short_content


class TestSystemPromptCache:
    """Test system prompt cache."""

    def test_cache_hit(self):
        """Test cache hit scenario."""
        cache = SystemPromptCache()

        content = "test content"
        prompt = "test prompt"

        # Cache miss
        result = cache.get("key1", content)
        assert result is None

        # Set cache
        cache.set("key1", prompt, content)

        # Cache hit
        result = cache.get("key1", content)
        assert result == prompt

        # Cache miss with different content
        result = cache.get("key1", "different content")
        assert result is None

    def test_cache_clear(self):
        """Test clearing cache."""
        cache = SystemPromptCache()

        cache.set("key1", "prompt1", "content1")
        cache.set("key2", "prompt2", "content2")

        cache.clear()

        assert cache.get("key1", "content1") is None
        assert cache.get("key2", "content2") is None


class TestContextCompressor:
    """Test context compressor."""

    @pytest.mark.asyncio
    async def test_compressor_disabled(self):
        """Test compressor when disabled."""
        provider = MockProvider()
        config = CompressionConfig(enabled=False)
        compressor = ContextCompressor(provider, config)

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ]

        compressed, stats = await compressor.compress_messages(messages)

        assert compressed == messages
        assert stats["compressed"] is False
        assert stats["reason"] == "disabled"

    @pytest.mark.asyncio
    async def test_compressor_under_limit(self):
        """Test compressor when under token limit."""
        provider = MockProvider()
        config = CompressionConfig(
            enabled=True,
            max_context_tokens=10000,
            target_context_tokens=8000
        )
        compressor = ContextCompressor(provider, config)

        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
        ]

        compressed, stats = await compressor.compress_messages(messages)

        assert compressed == messages
        assert stats["compressed"] is False
        assert stats["reason"] == "under_limit"

    @pytest.mark.asyncio
    async def test_compressor_history_compression(self):
        """Test history message compression."""
        provider = MockProvider()
        config = CompressionConfig(
            enabled=True,
            max_context_tokens=100,
            target_context_tokens=80,
            recent_messages_keep=2,
            strategy="truncation"
        )
        compressor = ContextCompressor(provider, config)

        # Create messages with older content that should be compressed
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Old message 1. " * 50},
            {"role": "assistant", "content": "Old response 1. " * 50},
            {"role": "user", "content": "Old message 2. " * 50},
            {"role": "assistant", "content": "Old response 2. " * 50},
            {"role": "user", "content": "Recent message"},
            {"role": "assistant", "content": "Recent response"},
        ]

        compressed, stats = await compressor.compress_messages(messages)

        assert stats["compressed"] is True
        assert stats["reduction"] > 0

        # Should keep recent messages
        assert len(compressed) == len(messages)
        assert compressed[-1]["content"] == "Recent response"
        assert compressed[-2]["content"] == "Recent message"

        # Older messages should be marked as compressed
        compressed_old = [m for m in compressed if m.get("_compressed")]
        assert len(compressed_old) > 0

    @pytest.mark.asyncio
    async def test_compress_system_prompt_cache(self):
        """Test system prompt caching."""
        provider = MockProvider()
        config = CompressionConfig(preserve_system_prompt_cache=True)
        compressor = ContextCompressor(provider, config)

        content_sources = {
            "identity": "test identity",
            "bootstrap": "test bootstrap"
        }

        system_prompt = "Full system prompt content"

        # First call - cache miss
        result1 = await compressor.compress_system_prompt(system_prompt, content_sources)
        assert result1 == system_prompt

        # Second call - cache hit
        result2 = await compressor.compress_system_prompt(system_prompt, content_sources)
        assert result2 == system_prompt

    def test_estimate_tokens(self):
        """Test token estimation."""
        provider = MockProvider()
        compressor = ContextCompressor(provider)

        messages = [
            {"role": "system", "content": "a" * 400},  # ~100 tokens
            {"role": "user", "content": "b" * 800},  # ~200 tokens
        ]

        tokens = compressor._estimate_tokens(messages)
        assert tokens == 300  # Rough estimate


class TestCompressionIntegration:
    """Test compression integration with ContextBuilder."""

    @pytest.mark.asyncio
    async def test_context_builder_with_compression(self):
        """Test ContextBuilder integration with compressor."""
        from aisbot.agent.context import ContextBuilder

        provider = MockProvider()
        compressor = ContextCompressor(provider)
        workspace = Path("/tmp/test_workspace")

        builder = ContextBuilder(workspace, compressor)

        # Test system prompt building with compression
        tools_summary = "Available tools: read_file, write_file"
        system_prompt = await builder.build_system_prompt(
            skill_names=None,
            tools_summary=tools_summary,
            provider=provider
        )

        assert "aisbot" in system_prompt
        assert "Available tools" in system_prompt

        # Test message building with compression
        history = [
            {"role": "user", "content": "Old message. " * 100},
            {"role": "assistant", "content": "Old response. " * 100},
        ]

        messages, stats = await builder.build_messages(
            history=history,
            current_message="Current message",
            tools_summary=tools_summary,
            provider=provider
        )

        assert len(messages) > 0
        assert messages[0]["role"] == "system"

    @pytest.mark.asyncio
    async def test_tool_result_compression(self):
        """Test tool result compression."""
        from aisbot.agent.context import ContextBuilder

        provider = MockProvider()
        compressor = ContextCompressor(provider)
        workspace = Path("/tmp/test_workspace")

        builder = ContextBuilder(workspace, compressor)

        # Test compressing long tool result (needs to be over 1000 chars)
        long_result = "Tool output. " * 200
        compressed = await builder.compress_tool_result(long_result, provider)

        assert len(compressed) < len(long_result)

        # Short result should not be compressed
        short_result = "Short output"
        not_compressed = await builder.compress_tool_result(short_result, provider)
        assert not_compressed == short_result


@pytest.mark.asyncio
async def test_compression_end_to_end():
    """End-to-end compression test."""
    provider = MockProvider("End-to-end test summary")

    # Create realistic message history with lots of content to trigger compression
    messages = [{"role": "system", "content": "System prompt with identity and tools. " * 50}]

    # Add many old messages with substantial content
    for i in range(20):
        messages.append({
            "role": "user",
            "content": f"Message {i}. " * 100  # More content to increase tokens
        })
        messages.append({
            "role": "assistant",
            "content": f"Response {i}. " * 100
        })

    # Add recent messages
    messages.append({"role": "user", "content": "Recent question?"})
    messages.append({"role": "assistant", "content": "Recent answer."})

    # Adjust config to force compression with lower threshold
    config = CompressionConfig(
        enabled=True,
        max_context_tokens=1000,  # Very low threshold to force compression
        target_context_tokens=800,
        recent_messages_keep=3,
        strategy="truncation"
    )
    compressor = ContextCompressor(provider, config)

    # Compress
    compressed, stats = await compressor.compress_messages(messages)

    assert stats["compressed"] is True
    assert stats["reduction"] > 0
    assert stats["reduction_percent"] > 0

    # Verify structure preserved
    assert compressed[0]["role"] == "system"
    assert compressed[-1]["content"] == "Recent answer."
    assert compressed[-2]["content"] == "Recent question?"
