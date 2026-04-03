"""【异步消息队列】，用来让「聊天渠道（WhatsApp/电报）」和「AI机器人核心」解耦通信"""

import asyncio
from nanobot.bus.events import InboundMessage,OutboundMessage

class MessageBus:
    """
    异步消息总线：彻底分离【聊天渠道】和【AI核心大脑】
    工作流程：
    1. 聊天渠道（WhatsApp）把用户消息 → 推送到【入站队列】
    2. AI核心从【入站队列】取消息 → 处理生成回复
    3. AI核心把回复消息 → 推送到【出站队列】
    4. 聊天渠道从【出站队列】取消息 → 发给用户
    """
    def __init__(self):
        """
        初始化消息总线：创建两个【异步先进先出队列】
        """
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self,msg: InboundMessage) ->None:
        """异步放入入站消息"""
        await self.inbound.put(msg)

    async def consume_inbound(self) ->InboundMessage:
        """异步取出入站消息"""
        return await self.inbound.get()   

    async def publish_outbound(self,msg: OutboundMessage) ->None:
        """异步放入出站消息"""
        await self.outbound.put(msg)
    
    async def consume_outbound(self) ->OutboundMessage:
        """异步取出出站消息"""
        return await self.outbound.get()

    @property
    def inbound_size(self) ->int:
        """获取【入站队列】待处理的消息数量（有多少条用户消息还没处理）"""
        return self.inbound.qsize()

    @property
    def outbound_size(self) ->int:
        """获取【出站队列】待发送的消息数量（有多少条机器人回复还没发出去）"""
        return self.outbound.qsize()

