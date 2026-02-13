# Context Compression

Context compression is a feature that reduces token usage in LLM conversations while maintaining conversation quality. It automatically compresses context when approaching token limits.

**🚀 Enabled by default** - Compression is automatically enabled with sensible defaults.

## Features

### 1. System Prompt Caching
- Caches system prompts to avoid rebuilding unchanged prompts
- Significantly reduces overhead for repeated calls

### 2. Hierarchical Message Compression
- Keeps recent messages (configurable, default: 10)
- Compresses older messages using configurable strategies
- Preserves conversation flow while reducing tokens

**Default Configuration:**
```yaml
tools:
  compression:
    enabled: true  # ✨ Enabled by default
    max_context_tokens: 16000
    target_context_tokens: 12000
    recent_messages_keep: 10
    strategy: "semantic"
```

### 3. Multiple Compression Strategies

#### Truncation Strategy
- Simple and fast truncation at sentence boundaries
- Best for: Quick compression without LLM calls
- Use when: Performance is critical, approximate preservation is acceptable

#### Semantic Strategy
- Intelligently preserves important sections
- Preserves code blocks, headers, and key terms
- Best for: Technical conversations with code
- Use when: Semantic understanding of content is important

#### Summary Strategy (LLM-based)
- Uses LLM to generate concise summaries
- Highest quality compression
- Best for: Important conversations where meaning must be preserved
- Use when: Token savings justify the LLM call cost

### 4. Tool Result Compression
- Automatically compresses long tool outputs
- Prevents tool results from overwhelming context

## Configuration

Compression is **enabled by default** with sensible settings. You can customize it in your `config.yaml`:

```yaml
tools:
  compression:
    enabled: true                    # Enable/disable compression
    max_context_tokens: 16000        # Start compressing above this
    target_context_tokens: 12000     # Target this many tokens after compression
    recent_messages_keep: 10         # Always keep this many recent messages
    strategy: "semantic"             # "truncation", "semantic", or "summary"
    min_content_length: 200          # Minimum content length to compress
    preserve_system_prompt_cache: true
```

### Disable Compression

To disable compression, set `enabled: false`:

```yaml
tools:
  compression:
    enabled: false
```

Or via environment variable:
```bash
export AISBOT_TOOLS__COMPRESSION__ENABLED=false
```

## Usage

**Compression works automatically out of the box!**

With default settings, the system will:

1. ✅ Cache system prompts on first use
2. ✅ Monitor token count before each LLM call
3. ✅ Apply compression when exceeding `max_context_tokens`
4. ✅ Log compression statistics

No configuration needed - just start using aisbot and enjoy reduced token usage!

### Manual Usage (Advanced)

```python
from aisbot.agent.compression import ContextCompressor, CompressionConfig
from aisbot.agent.context import ContextBuilder

# Create compressor
config = CompressionConfig(
    enabled=True,
    max_context_tokens=16000,
    target_context_tokens=12000,
    strategy="semantic"
)
compressor = ContextCompressor(provider, config)

# Use with ContextBuilder
builder = ContextBuilder(workspace, compressor)

# Build compressed messages
messages, stats = await builder.build_messages(
    history=history,
    current_message="Hello",
    provider=provider,
    model=model
)

if stats['compressed']:
    print(f"Reduced tokens: {stats['reduction']} ({stats['reduction_percent']:.1f}%)")
```

## Performance Impact

### Token Savings
- Typical reduction: 30-70% depending on strategy and content
- System prompt cache: 100% savings on repeated calls
- Conversation history: 40-60% typical reduction

### Latency Impact
- **Truncation**: ~1-5ms (negligible)
- **Semantic**: ~5-20ms (minimal)
- **Summary**: +1 LLM call (depends on model)

### Best Practices

1. Use `semantic` strategy for general purpose
2. Use `truncation` for high-throughput scenarios
3. Use `summary` for important/long-running conversations
4. Adjust `recent_messages_keep` based on conversation patterns
5. Monitor compression stats to tune thresholds

## Monitoring

Compression statistics are logged at INFO level:

```
INFO: Estimated tokens before compression: 18500
INFO: Compression complete: 18500 -> 11500 tokens (37.8% reduction)
```

Key metrics:
- `original_tokens`: Tokens before compression
- `final_tokens`: Tokens after compression
- `reduction`: Absolute token reduction
- `reduction_percent`: Percentage reduction

## Examples

See `examples/compression_demo.py` for a working demonstration of all compression strategies.

Run the demo:
```bash
python examples/compression_demo.py
```

## Testing

Run compression tests:
```bash
pytest tests/test_compression.py -v
```

Tests cover:
- All compression strategies
- Cache functionality
- Integration with ContextBuilder
- End-to-end compression scenarios
