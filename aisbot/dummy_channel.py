
import asyncio

from aisbot.config.loader import load_config
from aisbot.bus.squeue import MessageBus
from aisbot.bus.events import InboundMessage,OutboundMessage


async def recv(bus: MessageBus) -> None:
    """Receive messages from the bus (for testing pub/sub)."""
    print("[recv] Started receiving messages...")
    while True:
        msg = await bus.consume_inbound()
        if msg:
            print(f"[recv] Received: {msg}")

        msg = await bus.consume_outbound()
        if msg:
            print(f"[recv] Received: {msg}")    


async def main():
    config = load_config()

    # Create bus from config
    bus = MessageBus(config=config.bus)

    # Initialize the bus (required before publishing)
    await bus.init()

    message = InboundMessage(
        channel="whatsapp",
        sender_id="zhangsan",
        chat_id="1",
        content="hello",
    )

    outmessage = OutboundMessage(
        channel="whatsapp",
        reply_to="zhangsan",
        chat_id="1",
        content="hello",
    )

    # Start recv in background
    recv_task = asyncio.create_task(recv(bus))

    # Publish messages
    while True:
        await bus.publish_inbound(message)
        await bus.publish_outbound(outmessage)
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
