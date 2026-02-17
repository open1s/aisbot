"""Zenoh-based message bus provider implementation."""

import asyncio
import json
import time
from datetime import datetime
from typing import Any, Callable, Awaitable

import zenoh
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


class ZenohProvider(BusProvider):
    """
    Zenoh-based message bus provider.

    This provider uses the Zenoh protocol for pub/sub messaging
    between channels and agents.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize the Zenoh provider.

        Args:
            config: Optional Zenoh configuration dictionary.
        """
        self._config = config or {}
        self._session = None
        self._running = False

        # Topics
        self._inbound_topic = "inbound"
        self._outbound_topic = "outbound"

        # Publishers and subscribers
        self._inbound_pub = None
        self._inbound_sub = None
        self._outbound_pub = None
        self._outbound_sub = None

        # Subscribers registry
        self._outbound_subscribers: dict[
            str, list[Callable[[OutboundMessage], Awaitable[None]]]
        ] = {}

    async def initialize(self) -> None:
        """Initialize Zenoh session and endpoints."""
        logger.info("[Zenoh] Initializing...")
        start = time.perf_counter()

        # Create Zenoh session with config
        if self._config:
            zenoh_config = zenoh.Config()
            zenoh_config.insert_json5("config", json.dumps(self._config))
        else:
            zenoh_config = zenoh.Config()
        self._session = zenoh.open(zenoh_config)

        # Create publishers (synchronous)
        self._inbound_pub = self._session.declare_publisher(
            zenoh.KeyExpr(self._inbound_topic)
        )
        self._outbound_pub = self._session.declare_publisher(
            zenoh.KeyExpr(self._outbound_topic)
        )

        # Create subscribers (synchronous)
        self._inbound_sub = self._session.declare_subscriber(
            zenoh.KeyExpr(self._inbound_topic)
        )
        self._outbound_sub = self._session.declare_subscriber(
            zenoh.KeyExpr(self._outbound_topic)
        )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(f"[Zenoh] Initialized in {elapsed:.2f}ms")

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        data = json.dumps(msg.__dict__, default=_json_default)
        start = time.perf_counter()
        self._inbound_pub.put(data)
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(f"[Zenoh] Published inbound in {elapsed:.2f}ms: {msg.session_key}")

    async def consume_inbound(self) -> InboundMessage | None:
        """Consume the next inbound message."""
        start = time.perf_counter()
        try:
            # sample = await asyncio.wait_for(
            #     asyncio.to_thread(self._inbound_sub.recv),
            #     timeout=0.1
            # )
            while True:
                sample = self._inbound_sub.try_recv()
                if sample:
                    break
                else:
                    await asyncio.sleep(0.01)

            elapsed = (time.perf_counter() - start) * 1000
            if sample:
                try:
                    data = sample.payload.to_string()
                    # Handle potential double-encoding
                    parsed = json.loads(data)
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    data = parsed
                    if not isinstance(data, dict):
                        logger.warning(
                            f"[Zenoh] Invalid message format: expected dict, got {type(data).__name__}"
                        )
                        return None
                    data = _parse_datetime(data)
                    msg = InboundMessage(**data)
                    logger.debug(
                        f"[Zenoh] Consumed inbound in {elapsed:.2f}ms: {msg.session_key}"
                    )
                    return msg
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"[Zenoh] Failed to parse inbound message: {e}")
                    return None
        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            logger.debug(f"[Zenoh] No inbound (timeout after {elapsed:.2f}ms)")
            return None
        return None

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        data = json.dumps(msg.__dict__, default=_json_default)
        start = time.perf_counter()
        self._outbound_pub.put(data)
        elapsed = (time.perf_counter() - start) * 1000
        logger.debug(
            f"[Zenoh] Published outbound in {elapsed:.2f}ms: {msg.channel}:{msg.chat_id}"
        )

    async def consume_outbound(self) -> OutboundMessage | None:
        """Consume the next outbound message."""
        start = time.perf_counter()
        try:
            # sample = await asyncio.wait_for(
            #             asyncio.to_thread(self._outbound_sub.recv),
            #             timeout=0.1
            # )

            while True:
                sample = self._outbound_sub.try_recv()
                if sample:
                    break
                else:
                    await asyncio.sleep(0.01)
            elapsed = (time.perf_counter() - start) * 1000
            if sample:
                try:
                    data = sample.payload.to_string()
                    # Handle potential double-encoding
                    parsed = json.loads(data)
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    data = parsed
                    if not isinstance(data, dict):
                        logger.warning(
                            f"[Zenoh] Invalid outbound format: expected dict, got {type(data).__name__}"
                        )
                        return None
                    data = _parse_datetime(data)
                    msg = OutboundMessage(**data)
                    logger.debug(
                        f"[Zenoh] Consumed outbound in {elapsed:.2f}ms: {msg.channel}:{msg.chat_id}"
                    )
                    return msg
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"[Zenoh] Failed to parse outbound message: {e}")
                    return None
        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            logger.debug(f"[Zenoh] No outbound (timeout after {elapsed:.2f}ms)")
            return None
        return None

    def subscribe_outbound(
        self, channel: str, callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Subscribe to outbound messages for a specific channel."""
        if channel not in self._outbound_subscribers:
            self._outbound_subscribers[channel] = []
        self._outbound_subscribers[channel].append(callback)
        logger.debug(f"[Zenoh] Subscribed to channel: {channel}")

    async def dispatch_outbound(self) -> None:
        """Dispatch outbound messages to subscribed channels."""
        self._running = True
        logger.info("[Zenoh] Outbound dispatcher started")

        while self._running:
            try:
                start = time.perf_counter()
                try:
                    # sample = await asyncio.wait_for(
                    #     asyncio.to_thread(self._outbound_sub.recv),
                    #     timeout=0.1
                    # )
                    while True:
                        sample = self._outbound_sub.try_recv()
                        if sample:
                            break
                        else:
                            await asyncio.sleep(0.01)
                    elapsed = (time.perf_counter() - start) * 1000
                    if sample:
                        try:
                            data = sample.payload.to_string()
                            # Handle potential double-encoding
                            parsed = json.loads(data)
                            if isinstance(parsed, str):
                                parsed = json.loads(parsed)
                            data = parsed
                            if not isinstance(data, dict):
                                logger.warning(
                                    f"[Zenoh] Invalid dispatch format: expected dict, got {type(data).__name__}"
                                )
                                continue
                            data = _parse_datetime(data)
                            msg = OutboundMessage(**data)
                            logger.debug(
                                f"[Zenoh] Dispatching in {elapsed:.2f}ms: {msg.channel}:{msg.chat_id}"
                            )
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning(
                                f"[Zenoh] Failed to parse dispatch message: {e}"
                            )
                            continue
                        subscribers = self._outbound_subscribers.get(msg.channel, [])

                        for callback in subscribers:
                            try:
                                await callback(msg)
                            except Exception as e:
                                logger.error(f"Error dispatching to {msg.channel}: {e}")
                    else:
                        logger.debug(
                            f"[Zenoh] No outbound to dispatch (waited {elapsed:.2f}ms)"
                        )
                except asyncio.TimeoutError:
                    elapsed = (time.perf_counter() - start) * 1000
                    logger.debug(
                        f"[Zenoh] No outbound to dispatch (waited {elapsed:.2f}ms)"
                    )
            except asyncio.CancelledError:
                logger.info("[Zenoh] Outbound dispatcher cancelled")
                break

    def stop(self) -> None:
        """Stop the provider and release resources."""
        self._running = False
        logger.info("[Zenoh] Stopping...")

        # Undeclare publishers and subscribers
        if self._inbound_pub:
            self._inbound_pub.undeclare()
        if self._inbound_sub:
            self._inbound_sub.undeclare()
        if self._outbound_pub:
            self._outbound_pub.undeclare()
        if self._outbound_sub:
            self._outbound_sub.undeclare()

        # Close session
        if self._session:
            self._session.close()

        logger.info("[Zenoh] Stopped")

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return 0

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return 0
