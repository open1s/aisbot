"""LiteLLM provider implementation for multi-provider support."""

import os
from typing import Any
from abc import ABC

from aisbot.providers.base import LLMResponse, ToolCallRequest
from aisbot.providers.liteprovider import LitellmProvider


class ProviderFactory(ABC):
    """
    LLM provider using LiteLLM for multi-provider support.

    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.
    """

    providers = {}

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
    ):
        self.api_key = api_key
        self.api_base = api_base
        self.default_model = default_model
        self.extra_headers = extra_headers or {}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Pass api_base directly for custom endpoints (vLLM, etc.)
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Pass extra headers (e.g. APP-Code for AiHubMix)
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        provider_class = self.match_provider(model)
        if provider_class is None:
            raise ValueError(f"No provider found for model: {model}")

        provider = provider_class(api_key=self.api_key, api_base=self.api_base)
        provider.initialize()  # Instantiate provider

        try:
            response = await provider.completions(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            # Return error as content for graceful handling
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Parse arguments from JSON string if needed
                args = tc.function.arguments
                if isinstance(args, str):
                    import json

                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}

                tool_calls.append(
                    ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    @classmethod
    def register_provider(cls, subclass) -> str:
        """
        Register a provider subclass.

        Args:
            subclass: Provider class to register. Must have a `name` attribute or
                     the class name will be used (with 'Provider' suffix removed).

        Returns:
            The provider name used for registration.
        """
        # Get provider name: use `name` attribute if defined, otherwise use class name
        if hasattr(subclass, "name") and subclass.name:
            provider_name = subclass.name
        else:
            # Use class name, removing 'Provider' suffix if present
            class_name = subclass.__name__
            if class_name.endswith("Provider"):
                provider_name = class_name[:-8].lower()
            else:
                provider_name = class_name.lower()

        cls.providers[provider_name] = subclass
        return provider_name

    def match_provider(self, model: str) -> type | None:
        """
        Match a provider class for the given model.

        Args:
            model: Model identifier (e.g., 'gpt-4', 'claude-3-opus').

        Returns:
            The matched provider class, or None if no match found.
        """
        for provider_class in self.providers.values():
            if provider_class.match_model(model):
                return provider_class
        return None


ProviderFactory.register_provider(LitellmProvider)

# ============================================================================
# Provider Registration Examples
# ============================================================================

# Example 1: OpenAI Provider (uses class name as provider name)
#
# class OpenAIProvider(BaseProvider):
#     def __init__(self, api_key: str | None = None, api_base: str | None = None):
#         super().__init__(api_key, api_base)
#
#     @classmethod
#     def match_model(cls, model: str) -> bool:
#         # Match models like: gpt-4, gpt-3.5-turbo, o1-preview, etc.
#         return model.startswith("gpt-") or model.startswith("o1-")
#
#     def get_default_model(self) -> str:
#         return "gpt-4"
#
#     async def completions(self, **kwargs):
#         # Call litellm.completion with OpenAI model
#         return completion(**kwargs)
#
# # Register the provider (provider name will be "openai" automatically)
# ProviderFactory.register_provider(OpenAIProvider)


# Example 2: Anthropic Provider (explicit provider name)
#
# class AnthropicProvider(BaseProvider):
#     name = "anthropic"  # Explicit provider name
#
#     def __init__(self, api_key: str | None = None, api_base: str | None = None):
#         super().__init__(api_key, api_base)
#
#     @classmethod
#     def match_model(cls, model: str) -> bool:
#         # Match models like: claude-3-opus, claude-3-sonnet, etc.
#         return model.startswith("claude-")
#
#     def get_default_model(self) -> str:
#         return "claude-3-opus-20240229"
#
#     async def completions(self, **kwargs):
#         return completion(**kwargs)
#
# ProviderFactory.register_provider(AnthropicProvider)


# Example 3: Custom API Endpoint (uses api_base)
#
# class CustomAPIProvider(BaseProvider):
#     def __init__(self, api_key: str | None = None, api_base: str | None = None):
#         super().__init__(api_key, api_base)
#
#     @classmethod
#     def match_model(cls, model: str) -> bool:
#         # Match all models from this provider
#         return model.startswith("custom/")
#
#     def get_default_model(self) -> str:
#         return "custom/model-1"
#
#     async def completions(self, **kwargs):
#         return completion(**kwargs)
#
# ProviderFactory.register_provider(CustomAPIProvider)


# Example 4: Multi-model pattern provider
#
# class MultiModelProvider(BaseProvider):
#     # Define supported prefixes as class attribute
#     supported_prefixes = ["gpt-", "claude-", "gemini-"]
#
#     def __init__(self, api_key: str | None = None, api_base: str | None = None):
#         super().__init__(api_key, api_base)
#
#     @classmethod
#     def match_model(cls, model: str) -> bool:
#         # Match any model with supported prefix
#         return any(model.startswith(prefix) for prefix in cls.supported_prefixes)
#
#     def get_default_model(self) -> str:
#         return "gpt-4"
#
#     async def completions(self, **kwargs):
#         return completion(**kwargs)
#
# ProviderFactory.register_provider(MultiModelProvider)


# ============================================================================
# Usage Example
# ============================================================================

# from aisbot.providers.provider import ProviderFactory
#
# # Create factory instance
# factory = ProviderFactory(
#     api_key="your-api-key",
#     default_model="gpt-4"
# )
#
# # Register additional providers (optional, can also do in __init__)
# ProviderFactory.register_provider(OpenAIProvider)
# ProviderFactory.register_provider(AnthropicProvider)
#
# # Use with different models - provider will be auto-selected
# await factory.chat(
#     messages=[{"role": "user", "content": "Hello"}],
#     model="gpt-4"           # Uses OpenAIProvider
# )
# await factory.chat(
#     messages=[{"role": "user", "content": "Hello"}],
#     model="claude-3-opus"    # Uses AnthropicProvider
# )
# await factory.chat(
#     messages=[{"role": "user", "content": "Hello"}],
#     model="nvidia/llama"     # Uses LitellmProvider
# )
