"""Bus provider abstract base class and factory."""

from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from enum import Enum

from aisbot.bus.events import InboundMessage, OutboundMessage


class BusType(Enum):
    """Supported bus types."""

    DDS = "dds"
    ZENOH = "zenoh"


class BusProvider(ABC):
    """
    Abstract base class for message bus providers.

    Implementations must provide pub/sub functionality for inbound/outbound messages
    using different underlying transport mechanisms (DDS, Zenoh, etc.).
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the bus provider and create topics."""
        pass

    @abstractmethod
    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        pass

    @abstractmethod
    async def consume_inbound(self) -> InboundMessage | None:
        """Consume the next inbound message (blocks until available)."""
        pass

    @abstractmethod
    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        pass

    @abstractmethod
    async def consume_outbound(self) -> OutboundMessage | None:
        """Consume the next outbound message (blocks until available)."""
        pass

    @abstractmethod
    def subscribe_outbound(
        self, channel: str, callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Subscribe to outbound messages for a specific channel."""
        pass

    @abstractmethod
    async def dispatch_outbound(self) -> None:
        """Dispatch outbound messages to subscribed channels."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the provider and release resources."""
        pass

    @property
    @abstractmethod
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        pass

    @property
    @abstractmethod
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        pass
