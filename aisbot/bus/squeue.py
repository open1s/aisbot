"""Async message queue for decoupled channel-agent communication."""

import asyncio
from typing import Callable, Awaitable
import json
from loguru import logger

from aisbot.bus.events import InboundMessage, OutboundMessage
from aisbot.bus.dbus import DBus


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.
    
    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """
    
    def __init__(self,domain_id=0):
        self.dbus = DBus(domain_id=domain_id)
        self.inbound_topic = None
        self.outbound_topic = None
        self.inbound_sub = None
        self.outbound_pub = None
        self.inbound_pub = None
        self.outbound_sub = None
        self._outbound_subscribers: dict[str, list[Callable[[OutboundMessage], Awaitable[None]]]] = {}
        self._running = False

    async def init(self):
        """Initialize async components."""
        self.inbound_topic = await self.dbus.create_topic("inbound", "InboundMessage")
        self.outbound_topic = await self.dbus.create_topic("outbound", "OutboundMessage")

        self.inbound_sub = await self.dbus.create_subscriber(self.inbound_topic)
        self.outbound_pub = await self.dbus.create_publisher(self.outbound_topic)

        self.inbound_pub = await self.dbus.create_publisher(self.inbound_topic)
        self.outbound_sub = await self.dbus.create_subscriber(self.outbound_topic)
    
    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        # await self.inbound.put(msg)
        await self.inbound_pub.send(msg)
    
    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        data = await self.inbound_sub.recv(timeout_ms=1000)
        # Deserialize JSON to dictionary, then create InboundMessage
        if data:
            data = json.loads(data)
            return InboundMessage(**data)
        return None
    
    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        # await self.outbound.put(msg)
        await self.outbound_pub.send(msg)
    
    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        data = await self.outbound_sub.recv(timeout_ms=1000)
        # Deserialize JSON to dictionary, then create OutboundMessage
        if data:
            data = json.loads(data)
            return OutboundMessage(**data)
        return None
    
    def subscribe_outbound(
        self, 
        channel: str, 
        callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Subscribe to outbound messages for a specific channel."""

        print(f"DEBUG subscribe outbound: {channel}")

        if channel not in self._outbound_subscribers:
            self._outbound_subscribers[channel] = []
        self._outbound_subscribers[channel].append(callback)
    
    async def dispatch_outbound(self) -> None:
        """
        Dispatch outbound messages to subscribed channels.
        Run this as a background task.
        """
        self._running = True
        while self._running:
            try:
                # msg = await asyncio.wait_for(self.outbound.get(), timeout=1.0)
                data = await self.outbound_sub.recv(timeout_ms=1000)
                msg = None
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
    
    def stop(self) -> None:
        """Stop the dispatcher loop."""
        self._running = False
    
    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()
    
    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
  


# async def main():
#     bus = MessageBus()
#     await bus.init()


#     msg = OutboundMessage(channel="test", chat_id="test", content="test")
#     print(f"DEBUG consume outbound: {msg}")
#     await bus.publish_outbound(msg)
#     msg = await bus.consume_outbound()

#     print(f"DEBUG consume outbound: {msg}")

# if __name__ == "__main__":
#     asyncio.run(main(),debug=True)
