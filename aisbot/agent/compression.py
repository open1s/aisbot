"""Context compression engine for reducing token usage."""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger


class CompressionStrategy(ABC):
    """Abstract base class for compression strategies."""

    @abstractmethod
    async def compress(self, content: str, target_ratio: float = 0.5) -> str:
        """
        Compress content.

        Args:
            content: Content to compress.
            target_ratio: Target compression ratio (0.0-1.0).

        Returns:
            Compressed content.
        """
        pass

    @abstractmethod
    def estimate_tokens(self, content: str) -> int:
        """
        Estimate token count for content.

        Args:
            content: Content to estimate.

        Returns:
            Estimated token count.
        """
        pass


class SummaryStrategy(CompressionStrategy):
    """Uses LLM to generate summaries."""

    def __init__(self, provider: Any):
        """
        Initialize summary strategy.

        Args:
            provider: LLM provider for generating summaries.
        """
        self.provider = provider

    async def compress(self, content: str, target_ratio: float = 0.5) -> str:
        """Generate summary using LLM."""
        if not content or len(content) < 400:  # Only summarize sufficiently long content
            return content

        prompt = f"""请用简洁的语言总结以下内容，保留关键信息，长度约为原文的{int(target_ratio * 100)}%：

{content}

总结："""

        try:
            response = await self.provider.chat(
                messages=[{"role": "user", "content": prompt}],
                model=None  # Use default model
            )
            summary = response.content.strip()
            logger.debug(f"Summary generated: {len(content)} -> {len(summary)} chars")
            return summary or content
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            return content

    def estimate_tokens(self, content: str) -> int:
        """Estimate tokens using simple heuristic."""
        return len(content) // 4


class TruncationStrategy(CompressionStrategy):
    """Simple truncation strategy."""

    async def compress(self, content: str, target_ratio: float = 0.5) -> str:
        """Truncate content to target length."""
        if not content or len(content) < 200:  # Don't compress short content
            return content

        target_length = int(len(content) * target_ratio)
        if target_length >= len(content):
            return content

        # Try to truncate at sentence boundary
        truncated = content[:target_length]
        last_period = truncated.rfind('.')
        last_newline = truncated.rfind('\n')
        break_point = max(last_period, last_newline)

        if break_point > target_length * 0.7:  # Only if we found a good break point
            truncated = truncated[:break_point + 1]

        logger.debug(f"Truncated: {len(content)} -> {len(truncated)} chars")
        return truncated + "..." if len(truncated) < len(content) else truncated

    def estimate_tokens(self, content: str) -> int:
        """Estimate tokens using simple heuristic."""
        return len(content) // 4


class SemanticStrategy(CompressionStrategy):
    """Semantic compression based on importance."""

    def __init__(self, preserve_code: bool = True):
        """
        Initialize semantic strategy.

        Args:
            preserve_code: Whether to preserve code blocks.
        """
        self.preserve_code = preserve_code

    async def compress(self, content: str, target_ratio: float = 0.5) -> str:
        """Compress based on semantic importance."""
        if not content or len(content) <= 500:
            return content

        # Split into logical sections
        sections = self._split_sections(content)
        if len(sections) <= 1:
            return await TruncationStrategy().compress(content, target_ratio)

        # Calculate importance for each section
        importance_scores = [self._calculate_importance(section) for section in sections]
        total_importance = sum(importance_scores)

        if total_importance == 0:
            return await TruncationStrategy().compress(content, target_ratio)

        # Keep sections based on importance
        target_sections = max(1, int(len(sections) * target_ratio))
        indexed_scores = list(enumerate(importance_scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)

        keep_indices = {idx for idx, _ in indexed_scores[:target_sections]}
        keep_sections = [s for i, s in enumerate(sections) if i in keep_indices]

        # Sort by original order
        keep_sections.sort(key=lambda s: sections.index(s))

        compressed = "\n\n".join(keep_sections)
        logger.debug(f"Semantic compression: {len(sections)} -> {len(keep_sections)} sections")

        return compressed

    def _split_sections(self, content: str) -> list[str]:
        """Split content into logical sections."""
        # Split by double newlines or headers
        sections = content.split('\n\n')

        # Further split large sections
        result = []
        for section in sections:
            if len(section) > 2000:
                # Split by single newlines for large sections
                subsections = section.split('\n')
                # Group into chunks of ~1000 chars
                chunk = ""
                for sub in subsections:
                    if len(chunk) + len(sub) > 1000 and chunk:
                        result.append(chunk)
                        chunk = sub
                    else:
                        chunk += '\n' + sub if chunk else sub
                if chunk:
                    result.append(chunk)
            else:
                result.append(section)

        return result

    def _calculate_importance(self, section: str) -> float:
        """Calculate importance score for a section."""
        score = 1.0

        # Boost code blocks
        if '```' in section:
            score += 2.0

        # Boost headers
        if section.strip().startswith(('# ', '## ', '### ')):
            score += 1.5

        # Boost sections with key terms
        key_terms = ['error', 'exception', 'result', 'summary', 'conclusion', 'important', 'critical']
        lower = section.lower()
        for term in key_terms:
            if term in lower:
                score += 0.5

        # Penalize very short sections
        if len(section) < 100:
            score *= 0.5

        return score

    def estimate_tokens(self, content: str) -> int:
        """Estimate tokens using simple heuristic."""
        return len(content) // 4


@dataclass
class CompressionConfig:
    """Configuration for context compression."""

    enabled: bool = True
    max_context_tokens: int = 16000  # Maximum tokens before compression
    target_context_tokens: int = 12000  # Target tokens after compression
    recent_messages_keep: int = 10  # Always keep this many recent messages
    history_compression_threshold: int = 20  # Start compressing beyond this many messages
    strategy: str = "semantic"  # "summary", "truncation", "semantic"
    min_content_length: int = 200  # Minimum content length to compress
    preserve_system_prompt_cache: bool = True  # Cache system prompt


class SystemPromptCache:
    """Cache for system prompts."""

    def __init__(self):
        """Initialize cache."""
        self._cache: dict[str, tuple[str, str]] = {}  # key -> (prompt, hash)

    def get(self, key: str, content: str) -> str | None:
        """
        Get cached prompt if content hasn't changed.

        Args:
            key: Cache key.
            content: Current content to check.

        Returns:
            Cached prompt or None.
        """
        current_hash = self._calculate_hash(content)
        cached = self._cache.get(key)

        if cached:
            cached_prompt, cached_hash = cached
            if cached_hash == current_hash:
                logger.debug(f"Cache hit for {key}")
                return cached_prompt

        logger.debug(f"Cache miss for {key}")
        return None

    def set(self, key: str, prompt: str, content: str) -> None:
        """
        Cache a prompt.

        Args:
            key: Cache key.
            prompt: Prompt to cache.
            content: Content used to generate the prompt.
        """
        content_hash = self._calculate_hash(content)
        self._cache[key] = (prompt, content_hash)
        logger.debug(f"Cached prompt for {key}")

    def clear(self) -> None:
        """Clear cache."""
        self._cache.clear()

    def _calculate_hash(self, content: str) -> str:
        """Calculate hash for content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class ContextCompressor:
    """Main context compression engine."""

    def __init__(self, provider: Any, config: CompressionConfig | None = None):
        """
        Initialize compressor.

        Args:
            provider: LLM provider for summary strategy.
            config: Compression configuration.
        """
        self.config = config or CompressionConfig()
        self.provider = provider
        self.system_prompt_cache = SystemPromptCache()
        self._strategies: dict[str, CompressionStrategy] = {
            "summary": SummaryStrategy(provider),
            "truncation": TruncationStrategy(),
            "semantic": SemanticStrategy(),
        }

    async def compress_messages(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Compress message list to fit token limit.

        Args:
            messages: Original messages.
            model: Model name to check token limits.

        Returns:
            Compressed messages and statistics.
        """
        if not self.config.enabled:
            return messages, {"compressed": False, "reason": "disabled"}

        # Calculate current token count
        total_tokens = self._estimate_tokens(messages)
        logger.info(f"Estimated tokens before compression: {total_tokens}")

        if total_tokens <= self.config.target_context_tokens:
            return messages, {
                "compressed": False,
                "original_tokens": total_tokens,
                "reason": "under_limit"
            }

        # Apply compression
        compressed = await self._apply_compression(messages)
        final_tokens = self._estimate_tokens(compressed)

        stats = {
            "compressed": True,
            "original_tokens": total_tokens,
            "final_tokens": final_tokens,
            "reduction": total_tokens - final_tokens,
            "reduction_percent": ((total_tokens - final_tokens) / total_tokens * 100) if total_tokens > 0 else 0
        }

        logger.info(f"Compression complete: {total_tokens} -> {final_tokens} tokens "
                   f"({stats['reduction_percent']:.1f}% reduction)")

        return compressed, stats

    async def compress_system_prompt(self, system_prompt: str, content_sources: dict[str, str]) -> str:
        """
        Compress system prompt using cache.

        Args:
            system_prompt: System prompt to compress.
            content_sources: Content used to build the prompt (for cache key).

        Returns:
            System prompt (cached or newly built).
        """
        if not self.config.preserve_system_prompt_cache:
            return system_prompt

        # Create cache key from content sources
        cache_key = self._build_cache_key(content_sources)

        # Check cache
        cached = self.system_prompt_cache.get(cache_key, str(content_sources))
        if cached:
            return cached

        # Cache and return
        self.system_prompt_cache.set(cache_key, system_prompt, str(content_sources))
        return system_prompt

    def _build_cache_key(self, content_sources: dict[str, str]) -> str:
        """Build cache key from content sources."""
        # Use sorted keys for consistent hash
        sorted_items = sorted(content_sources.items())
        return hashlib.sha256(str(sorted_items).encode()).hexdigest()[:16]

    async def _apply_compression(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply compression to messages."""
        if not messages:
            return messages

        # Separate system prompt and other messages
        system_messages = [m for m in messages if m.get("role") == "system"]
        other_messages = [m for m in messages if m.get("role") != "system"]

        if not other_messages:
            return messages

        # Apply history compression
        compressed_history = await self._compress_history(other_messages)

        # Combine system messages with compressed history
        return system_messages + compressed_history

    async def _compress_history(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compress message history."""
        if len(messages) <= self.config.recent_messages_keep:
            return messages

        # Keep recent messages as-is
        recent = messages[-self.config.recent_messages_keep:]
        older = messages[:-self.config.recent_messages_keep]

        if not older:
            return messages

        # Compress older messages
        strategy = self._strategies.get(self.config.strategy, self._strategies["semantic"])

        # Group older messages for compression
        compressed_older = []
        for msg in older:
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > self.config.min_content_length:
                # Compress content
                compressed_content = await strategy.compress(
                    content,
                    target_ratio=0.3  # More aggressive for older messages
                )
                compressed_older.append({
                    **msg,
                    "content": compressed_content,
                    "_compressed": True,
                    "_original_length": len(content)
                })
            else:
                compressed_older.append(msg)

        return compressed_older + recent

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate total tokens for messages."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 4  # Rough estimate
            elif isinstance(content, list):
                # Handle multimodal content
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text = item.get("text", "")
                            total += len(text) // 4
                        # Images counted separately by model
        return total

    def get_strategy(self, name: str) -> CompressionStrategy | None:
        """Get compression strategy by name."""
        return self._strategies.get(name)

    def set_strategy(self, name: str, strategy: CompressionStrategy) -> None:
        """Set compression strategy."""
        self._strategies[name] = strategy
