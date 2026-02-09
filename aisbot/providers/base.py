"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRequest:
    """A tool call request from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    
    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0


class BaseProvider(ABC):
    """
    Abstract base class for LLM providers.

    Implementations should handle the specifics of each provider's API
    while maintaining a consistent interface.
    """

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        self.api_key = api_key
        self.api_base = api_base

    def initialize(self):
        """Initialize the provider."""
        pass

    @abstractmethod
    async def completions(self, **kwargs):
        """
        Send a completion request to the provider API.

        Args:
            **kwargs: Provider-specific arguments (model, messages, etc.)

        Returns:
            Raw response from the provider API.
        """
        pass

    @classmethod
    def match_model(cls, model: str) -> bool:
        """Check if the model matches this provider."""
        return True

    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        pass
