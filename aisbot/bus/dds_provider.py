"""DDS-based message bus provider implementation."""

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Callable, Awaitable

from loguru import logger

from aisbot.bus.events import InboundMessage, OutboundMessage
from aisbot.bus.provider import BusProvider


def _json_default(obj: Any) -> str:
    """Handle non-serializable objects for JSON."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def _parse_datetime(obj: dict[str, Any]) -> dict[str, Any]:
    """Parse datetime strings back to datetime objects."""
    if "timestamp" in obj and isinstance(obj["timestamp"], str):
        obj["timestamp"] = datetime.fromisoformat(obj["timestamp"])
    return obj


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
        logger.info(f"[DDS] Initializing with domain_id={self._domain_id}")
        start = time.perf_counter()

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

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(f"[DDS] Initialized in {elapsed:.2f}ms")

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        data = json.dumps(msg.__dict__, default=_json_default)
        start = time.perf_counter()
        await self._inbound_pub.send(data)
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(f"[DDS] Published inbound in {elapsed:.2f}ms: {msg.session_key}")

    async def consume_inbound(self) -> InboundMessage | None:
        """Consume the next inbound message."""
        start = time.perf_counter()
        data = await self._inbound_sub.recv(timeout_ms=1000)
        elapsed = (time.perf_counter() - start) * 1000
        if data:
            try:
                # Handle both raw JSON string and already-parsed dict
                if isinstance(data, str):
                    # minidds may double-encode the data as a JSON string literal
                    # Try parsing once first
                    parsed = json.loads(data)
                    # If still a string, parse again (double-encoded)
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    data = parsed
                if not isinstance(data, dict):
                    logger.warning(f"[DDS] Invalid message format: expected dict, got {type(data).__name__}")
                    return None
                # Parse datetime strings back to datetime objects
                data = _parse_datetime(data)
                msg = InboundMessage(**data)
                logger.debug(f"[DDS] Consumed inbound in {elapsed:.2f}ms: {msg.session_key}")
                return msg
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"[DDS] Failed to parse inbound message: {e}, data: {data[:100] if isinstance(data, str) else data}...")
                return None
        logger.debug(f"[DDS] No inbound (timeout after {elapsed:.2f}ms)")
        return None

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        data = json.dumps(msg.__dict__, default=_json_default)
        start = time.perf_counter()
        await self._outbound_pub.send(data)
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(f"[DDS] Published outbound in {elapsed:.2f}ms: {msg.channel}:{msg.chat_id}")

    async def consume_outbound(self) -> OutboundMessage | None:
        """Consume the next outbound message."""
        start = time.perf_counter()
        data = await self._outbound_sub.recv(timeout_ms=1000)
        elapsed = (time.perf_counter() - start) * 1000
        if data:
            try:
                # Handle both raw JSON string and already-parsed dict
                if isinstance(data, str):
                    # minidds may double-encode the data as a JSON string literal
                    parsed = json.loads(data)
                    # If still a string, parse again (double-encoded)
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    data = parsed
                if not isinstance(data, dict):
                    logger.warning(f"[DDS] Invalid outbound format: expected dict, got {type(data).__name__}")
                    return None
                # Parse datetime strings back to datetime objects
                data = _parse_datetime(data)
                msg = OutboundMessage(**data)
                logger.debug(f"[DDS] Consumed outbound in {elapsed:.2f}ms: {msg.channel}:{msg.chat_id}")
                return msg
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"[DDS] Failed to parse outbound message: {e}, data: {data[:100] if isinstance(data, str) else data}...")
                return None
        logger.debug(f"[DDS] No outbound (timeout after {elapsed:.2f}ms)")
        return None

    def subscribe_outbound(
        self, channel: str, callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Subscribe to outbound messages for a specific channel."""
        if channel not in self._outbound_subscribers:
            self._outbound_subscribers[channel] = []
        self._outbound_subscribers[channel].append(callback)
        logger.debug(f"[DDS] Subscribed to channel: {channel}")

    async def dispatch_outbound(self) -> None:
        """Dispatch outbound messages to subscribed channels."""
        self._running = True
        logger.info("[DDS] Outbound dispatcher started")

        while self._running:
            try:
                start = time.perf_counter()
                data = await self._outbound_sub.recv(timeout_ms=1000)
                elapsed = (time.perf_counter() - start) * 1000
                if data:
                    try:
                        # Handle both raw JSON string and already-parsed dict
                        if isinstance(data, str):
                            # minidds may double-encode the data as a JSON string literal
                            parsed = json.loads(data)
                            # If still a string, parse again (double-encoded)
                            if isinstance(parsed, str):
                                parsed = json.loads(parsed)
                            data = parsed
                        if not isinstance(data, dict):
                            logger.warning(f"[DDS] Invalid dispatch format: expected dict, got {type(data).__name__}")
                            continue
                        # Parse datetime strings back to datetime objects
                        data = _parse_datetime(data)
                        msg = OutboundMessage(**data)
                        logger.debug(f"[DDS] Dispatching in {elapsed:.2f}ms: {msg.channel}:{msg.chat_id}")
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"[DDS] Failed to parse dispatch message: {e}, data: {data[:100] if isinstance(data, str) else data}...")
                        continue
                    subscribers = self._outbound_subscribers.get(msg.channel, [])

                    for callback in subscribers:
                        try:
                            await callback(msg)
                        except Exception as e:
                            logger.error(f"Error dispatching to {msg.channel}: {e}")
                else:
                    logger.debug(f"[DDS] No outbound to dispatch (waited {elapsed:.2f}ms)")
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("[DDS] Outbound dispatcher cancelled")
                break

    def stop(self) -> None:
        """Stop the provider."""
        self._running = False
        logger.info("[DDS] Stopped")

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return 0

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return 0
