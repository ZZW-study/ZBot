"""消息总线模块：用于实现通道（Channel）与代理（Agent）之间的解耦通信"""

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]


