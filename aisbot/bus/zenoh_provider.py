"""Zenoh-based message bus provider implementation."""

import asyncio
import json
from typing import Callable, Awaitable

from loguru import logger

from aisbot.bus.events import InboundMessage, OutboundMessage
from aisbot.bus.provider import BusProvider


class ZenohProvider(BusProvider):
    """
    Zenoh-based message bus provider.

    This provider uses the Zenoh protocol for pub/sub messaging.
    Zenoh provides efficient pub/sub with automatic discovery and
    support for various transports (UDP, TCP, WebSocket, etc.).
    """

    def __init__(self, config: dict | None = None):
        """
        Initialize the Zenoh provider.

        Args:
            config: Optional Zenoh configuration dictionary.
        """
        self._config = config or {}
        self._session = None
        self._running = False

        # Publishers and subscribers
        self._inbound_pub = None
        self._outbound_pub = None
        self._inbound_sub = None
        self._outbound_sub = None

        # Subscribers registry
        self._outbound_subscribers: dict[
            str, list[Callable[[OutboundMessage], Awaitable[None]]]
        ] = {}

        # Key expressions
        self._inbound_key = "aisbot/inbound"
        self._outbound_key = "aisbot/outbound"

    async def initialize(self) -> None:
        """Initialize Zenoh session and endpoints."""
        import zenoh

        logger.info("Initializing Zenoh provider")

        # Create Zenoh config
        zenoh_config = zenoh.Config()
        for key, value in self._config.items():
            zenoh_config.set_json(key, json.dumps(value))

        # Open session (zenoh.open is synchronous in newer versions)
        self._session = zenoh.open(zenoh_config)

        # Declare publishers
        self._inbound_pub = self._session.declare_publisher(self._inbound_key)
        self._outbound_pub = self._session.declare_publisher(self._outbound_key)

        # Declare subscribers
        self._inbound_sub = self._session.declare_subscriber(
            self._inbound_key, self._handle_inbound
        )
        self._outbound_sub = self._session.declare_subscriber(
            self._outbound_key, self._handle_outbound
        )

        logger.info("Zenoh provider initialized successfully")

    async def _handle_inbound(self, sample) -> None:
        """Handle incoming inbound messages."""
        try:
            data = json.loads(sample.payload.to_string())
            msg = InboundMessage(**data)
            logger.debug(f"Received inbound message: {msg.session_key}")
        except Exception as e:
            logger.error(f"Error handling inbound message: {e}")

    async def _handle_outbound(self, sample) -> None:
        """Handle incoming outbound messages."""
        try:
            data = json.loads(sample.payload.to_string())
            msg = OutboundMessage(**data)
            logger.debug(f"Received outbound message: {msg.channel}:{msg.chat_id}")

            # Dispatch to subscribers
            subscribers = self._outbound_subscribers.get(msg.channel, [])
            for callback in subscribers:
                try:
                    await callback(msg)
                except Exception as e:
                    logger.error(f"Error dispatching to {msg.channel}: {e}")
        except Exception as e:
            logger.error(f"Error handling outbound message: {e}")

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        data = json.dumps(msg.__dict__, default=str)
        self._inbound_pub.put(data)
        logger.debug(f"Published inbound message: {msg.session_key}")

    async def consume_inbound(self) -> InboundMessage | None:
        """
        Consume the next inbound message.

        Note: Zenoh uses push-based subscription, so this method
        returns None. Use subscribe_outbound instead for receiving messages.
        """
        return None

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        data = json.dumps(msg.__dict__, default=str)
        self._outbound_pub.put(data)
        logger.debug(f"Published outbound message: {msg.channel}:{msg.chat_id}")

    async def consume_outbound(self) -> OutboundMessage | None:
        """
        Consume the next outbound message.

        Note: Zenoh uses push-based subscription, so this method
        returns None. Use subscribe_outbound instead for receiving messages.
        """
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
        """
        Dispatch outbound messages to subscribed channels.

        Note: With Zenoh's push-based model, this is handled automatically
        by the subscriber callback. This method is a no-op for compatibility.
        """
        self._running = True
        logger.info("Zenoh outbound dispatcher started (push-based)")

        # Keep the task running
        while self._running:
            await asyncio.sleep(1)

    def stop(self) -> None:
        """Stop the provider and release resources."""
        self._running = False

        if self._session:
            self._session.close()
            self._session = None

        logger.info("Zenoh provider stopped")

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        # Zenoh doesn't have a queue size concept
        return 0

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        # Zenoh doesn't have a queue size concept
        return 0
