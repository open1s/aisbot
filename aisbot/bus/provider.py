import asyncio
from typing import Callable, Awaitable
from aisbot.bus.events import InboundMessage, OutboundMessage

class BusProvider:
    """
    Async message bus provider that provides a message bus at low level.
    """
    
    def __init__(self):
        pass
    
    async def publish_inbound(self, msg: InboundMessage) -> None:
        pass
    
    async def consume_inbound(self) -> InboundMessage:
        pass
    
    async def publish_outbound(self, msg: OutboundMessage) -> None:
        pass
    
    async def consume_outbound(self) -> OutboundMessage:
        pass
    
    def subscribe_outbound(
        self, 
        channel: str, 
        callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        pass
    
    async def dispatch_outbound(self) -> None:
        pass
    
    def stop(self) -> None:
        pass
    
    @property
    def inbound_size(self) -> int:
        pass
    @property
    def outbound_size(self) -> int:
        pass