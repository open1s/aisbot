"""Async message queue for decoupled channel-agent communication."""

from typing import Callable, Awaitable

from aisbot.bus.events import InboundMessage, OutboundMessage
from aisbot.bus.provider import BusType
from aisbot.bus.factory import BusFactory


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.

    This class uses the Provider/Factory pattern to support different
    underlying transport mechanisms (DDS, Zenoh).
    """

    def __init__(
        self,
        bus_type: BusType | str | None = None,
        config: "BusConfig | None" = None,
        **provider_kwargs,
    ):
        """
        Initialize the message bus.

        Args:
            bus_type: Type of bus provider to use ("dds" or "zenoh").
                      If None, uses config.bus.provider if available.
            config: BusConfig object for provider configuration.
            **provider_kwargs: Additional arguments passed to the provider.
        """
        # Determine bus type from config or parameter
        if bus_type is None:
            if config is not None:
                bus_type = config.provider
            else:
                bus_type = "dds"

        # Build provider kwargs from config if available
        if config is not None:
            if config.provider == "dds" and "domain_id" not in provider_kwargs:
                provider_kwargs["domain_id"] = config.domain_id
            elif config.provider == "zenoh" and "config" not in provider_kwargs:
                provider_kwargs["config"] = config.zenoh_config

        self._provider = BusFactory.create(bus_type, **provider_kwargs)
        self._running = False

    async def init(self) -> None:
        """Initialize the bus provider."""
        await self._provider.initialize()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self._provider.publish_inbound(msg)

    async def consume_inbound(self) -> InboundMessage | None:
        """Consume the next inbound message (blocks until available)."""
        return await self._provider.consume_inbound()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self._provider.publish_outbound(msg)

    async def consume_outbound(self) -> OutboundMessage | None:
        """Consume the next outbound message (blocks until available)."""
        return await self._provider.consume_outbound()

    def subscribe_outbound(
        self, channel: str, callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Subscribe to outbound messages for a specific channel."""
        self._provider.subscribe_outbound(channel, callback)

    async def dispatch_outbound(self) -> None:
        """
        Dispatch outbound messages to subscribed channels.
        Run this as a background task.
        """
        await self._provider.dispatch_outbound()

    def stop(self) -> None:
        """Stop the dispatcher loop."""
        self._provider.stop()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self._provider.inbound_size

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self._provider.outbound_size
