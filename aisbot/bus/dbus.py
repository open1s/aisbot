"""Async message queue for decoupled channel-agent communication."""

import asyncio
from typing import Callable, Optional

from loguru import logger

# Disable debug/info logging, only show warnings and errors
# logger.remove()
# logger.add(lambda msg: None, level="WARNING")

from aisbot.bus.events import InboundMessage, OutboundMessage

from minidds import PyDataBus, PyTopic


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
            topic_name=topic_name,
            type_name=type_name
        )
        return topic

    async def create_keyed_topic(self, topic_name, type_name):
        """Create a keyed topic for pub/sub with key filtering."""
        topic = await self.bus.create_keyed_topic(
            topic_name=topic_name,
            type_name=type_name
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

# async def main():
#     """Example usage of MessageBus with callback registration."""
#     bus = MessageBus(0)

#     # Define a callback for incoming messages (non-keyed)
#     def message_handler(message):
#         print(f"Received message: {message}")

#     # Define a callback for incoming messages (keyed)
#     def keyed_message_handler(key, message):
#         print(f"Received keyed message - Key: {key}, Message: {message}")

#     # Create topic and register with callback
#     topic = await bus.create_topic("inbound_message", "InboundMessage")
#     await bus.register_topic(topic, message_handler)

#     topic_keyed = await bus.create_keyed_topic("keyed_inbound_message", "KeyedInboundMessage")
#     await bus.register_keyed_topic(topic_keyed, keyed_message_handler)


#     async def sender():
#         try:
#             while True:
#                 pub = await bus.create_publisher(topic)
#                 await pub.send({"text": "Hello, world!"})


#                 pub_keyed = await bus.create_keyed_publisher(topic_keyed)
#                 await pub_keyed.send(key=1, message={"text": "Hello, world!"})

#                 await asyncio.sleep(0.1)
#         except KeyboardInterrupt:
#             print("Shutting down...")

#     # Start sender task
#     asyncio.create_task(sender())

#     # Keep event loop running
#     try:
#         while True:
#             await asyncio.sleep(1)
#     except KeyboardInterrupt:
#         print("Shutting down...")


# if __name__ == "__main__":
#     # Enable asyncio debug mode for development
#     try:
#         asyncio.run(main(), debug=True)
#     except KeyboardInterrupt:
#         print("\nApplication stopped by user.")
