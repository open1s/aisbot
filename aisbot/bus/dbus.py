"""Async message queue for decoupled channel-agent communication."""

import asyncio

from loguru import logger
from minidds import PyDataBus


class DBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self, domain_id=0):
        self.bus = PyDataBus(domain_id=domain_id)
        self._running = False

    async def create_topic(self, topic_name, type_name):
        """Create a non-keyed topic for pub/sub."""
        topic = await self.bus.create_no_key_topic(
            topic_name=topic_name, type_name=type_name
        )
        return topic

    async def create_keyed_topic(self, topic_name, type_name):
        """Create a keyed topic for pub/sub with key filtering."""
        topic = await self.bus.create_keyed_topic(
            topic_name=topic_name, type_name=type_name
        )
        return topic

    async def create_subscriber(self, topic):
        """Create a subscriber for a non-keyed topic."""
        subscriber = await self.bus.create_subscriber(topic)
        return subscriber

    async def create_publisher(self, topic):
        """Create a publisher for a non-keyed topic."""
        publisher = await self.bus.create_publisher(topic)
        return publisher

    async def create_keyed_subscriber(self, topic):
        """Create a subscriber for a keyed topic."""
        subscriber = await self.bus.create_keyed_subscriber(topic)
        return subscriber

    async def create_keyed_publisher(self, topic):
        """Create a publisher for a keyed topic."""
        publisher = await self.bus.create_keyed_publisher(topic)
        return publisher

    async def register_topic(self, topic, cb):
        """
        Register a topic with a callback function.
        Starts polling for messages on the topic.
        """
        sub = await self.create_subscriber(topic)
        if cb:
            asyncio.create_task(self._poll_topic_(sub, cb))
        return sub

    async def register_keyed_topic(self, topic, cb):
        """
        Register a topic with a callback function.
        Starts polling for messages on the topic.
        """
        sub = await self.create_keyed_subscriber(topic)
        if cb:
            asyncio.create_task(self._poll_topic_(sub, cb))
        return sub

    async def _poll_topic_(self, subscriber, cb):
        """
        Internal method to continuously poll for messages and call callback.
        Handles both keyed and non-keyed subscribers.
        """
        logger.info("Starting to poll for messages...")
        try:
            while True:
                result = await subscriber.recv(timeout_ms=1000)
                if result:
                    logger.debug(f"Received message: {result}")
                    try:
                        # Check if result is a tuple (keyed topic)
                        if isinstance(result, tuple) and len(result) == 2:
                            key, message = result
                            if asyncio.iscoroutinefunction(cb):
                                await cb(key, message)
                            else:
                                cb(key, message)
                        else:
                            # Non-keyed topic
                            if asyncio.iscoroutinefunction(cb):
                                await cb(result)
                            else:
                                cb(result)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")
        except asyncio.CancelledError:
            logger.info("Polling task cancelled")
        except Exception as e:
            logger.error(f"Polling error: {e}")

    async def loop_forever(self):
        """Keep the event loop running indefinitely."""
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")
