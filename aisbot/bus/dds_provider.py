"""DDS-based message bus provider implementation."""

import asyncio
import json
from typing import Callable, Awaitable

from loguru import logger

from aisbot.bus.events import InboundMessage, OutboundMessage
from aisbot.bus.provider import BusProvider


class DDSProvider(BusProvider):
    """
    DDS-based message bus provider using minidds.

    This provider uses the DDS (Data Distribution Service) protocol
    for pub/sub messaging between channels and agents.
    """

    def __init__(self, domain_id: int = 0):
        """
        Initialize the DDS provider.

        Args:
            domain_id: DDS domain ID for topic isolation.
        """
        from minidds import PyDataBus

        self._domain_id = domain_id
        self._bus = PyDataBus(domain_id=domain_id)
        self._running = False

        # Topics and endpoints
        self._inbound_topic = None
        self._outbound_topic = None
        self._inbound_sub = None
        self._outbound_pub = None
        self._inbound_pub = None
        self._outbound_sub = None

        # Subscribers registry
        self._outbound_subscribers: dict[
            str, list[Callable[[OutboundMessage], Awaitable[None]]]
        ] = {}

    async def initialize(self) -> None:
        """Initialize DDS topics and endpoints."""
        logger.info(f"Initializing DDS provider with domain_id={self._domain_id}")

        self._inbound_topic = await self._bus.create_no_key_topic(
            topic_name="inbound", type_name="InboundMessage"
        )
        self._outbound_topic = await self._bus.create_no_key_topic(
            topic_name="outbound", type_name="OutboundMessage"
        )

        self._inbound_sub = await self._bus.create_subscriber(self._inbound_topic)
        self._outbound_pub = await self._bus.create_publisher(self._outbound_topic)
        self._inbound_pub = await self._bus.create_publisher(self._inbound_topic)
        self._outbound_sub = await self._bus.create_subscriber(self._outbound_topic)

        logger.info("DDS provider initialized successfully")

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        data = json.dumps(msg.__dict__, default=str)
        await self._inbound_pub.send(data)
        logger.debug(f"Published inbound message: {msg.session_key}")

    async def consume_inbound(self) -> InboundMessage | None:
        """Consume the next inbound message."""
        data = await self._inbound_sub.recv(timeout_ms=1000)
        if data:
            data = json.loads(data)
            return InboundMessage(**data)
        return None

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        data = json.dumps(msg.__dict__, default=str)
        await self._outbound_pub.send(data)
        logger.debug(f"Published outbound message: {msg.channel}:{msg.chat_id}")

    async def consume_outbound(self) -> OutboundMessage | None:
        """Consume the next outbound message."""
        data = await self._outbound_sub.recv(timeout_ms=1000)
        if data:
            data = json.loads(data)
            return OutboundMessage(**data)
        return None

    def subscribe_outbound(
        self, channel: str, callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Subscribe to outbound messages for a specific channel."""
        if channel not in self._outbound_subscribers:
            self._outbound_subscribers[channel] = []
        self._outbound_subscribers[channel].append(callback)
        logger.debug(f"Subscribed to outbound channel: {channel}")

    async def dispatch_outbound(self) -> None:
        """Dispatch outbound messages to subscribed channels."""
        self._running = True
        logger.info("Starting outbound dispatcher")

        while self._running:
            try:
                data = await self._outbound_sub.recv(timeout_ms=1000)
                if data:
                    data = json.loads(data)
                    msg = OutboundMessage(**data)
                    subscribers = self._outbound_subscribers.get(msg.channel, [])

                    for callback in subscribers:
                        try:
                            await callback(msg)
                        except Exception as e:
                            logger.error(f"Error dispatching to {msg.channel}: {e}")
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("Outbound dispatcher cancelled")
                break

    def stop(self) -> None:
        """Stop the provider."""
        self._running = False
        logger.info("DDS provider stopped")

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        # DDS doesn't have a direct queue size, return 0
        return 0

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        # DDS doesn't have a direct queue size, return 0
        return 0
