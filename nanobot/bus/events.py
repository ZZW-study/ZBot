"""定义【消息总线】的事件类型,消息总线 = 机器人传递/接受消息的「中央通道」，所有消息都通过这里流转"""

from dataclasses import dataclass,field
from datetime import datetime
from typing import Any

@dataclass # @dataclass：装饰器，自动给类生成 __init__、__repr__、__eq__ 等基础方法，专门用来定义只存数据、逻辑少的类（数据类）。
class InboundMessage:
    """
    【入站消息】：机器人从各个聊天渠道（WhatsApp/电报等）**收到**的用户消息
    例子：用户在 WhatsApp 给机器人发了一句"你好" → 封装成这个类
    """
    channel: str                                                # 消息来源渠道：值是 whatsapp/telegram/discord 等，区分哪个聊天软件
    sender_id: str                                              # 发送者唯一ID：比如WhatsApp的手机号、电报的用户ID（用来识别是谁发的）
    chat_id: str                                                # 聊天会话ID：单聊/群聊的唯一标识（用来区分是私聊还是群聊）
    content: str                                                # 消息核心内容：用户发的文字（比如"你好""帮我查天气"）
    timestamp: datetime = field(default_factory=datetime.now)   # 消息时间戳
    media: list = field(default_factory=list)                   # 媒体文件列表：存储图片/视频/音频的链接，空列表表示没有媒体
    metadata: dict[str,Any] = field(default_factory=dict)       # 元数据：渠道专属的额外信息（比如WhatsApp的消息状态、电报的群信息）
    session_key_override: str | None = None                     # 自定义会话键

    @property
    def session_key(self) ->str:
        """
        【会话唯一键】：用来区分不同的聊天会话，机器人靠这个记住和谁在聊天
        规则：如果自定义了会话键就用自定义的，否则用 「渠道:会话ID」
        例子：whatsapp:123456789（代表WhatsApp的123456789这个聊天）
        """
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """
    【出站消息】：机器人要发送给聊天渠道（WhatsApp/电报等）的回复消息
     例子：机器人回复"我是AI助手" → 封装成这个类，发给WhatsApp
    """
    channel: str  # 目标发送渠道：要发给哪个聊天软件（比如whatsapp）
    chat_id: str  # 目标会话ID：要发给哪个聊天（和入站的chat_id对应）
    content: str  # 要发送的文字内容：机器人的回复话术
    reply_to: str | None = None # 可选：回复哪条消息（引用回复），值为消息ID，None表示普通发送
    media: list[str] = field(default_factory=list) # 要发送的媒体文件列表：图片/视频链接，空列表表示不发媒体
    metadata: dict[str, Any] = field(default_factory=dict)  # 发送元数据：渠道专属的发送参数（比如WhatsApp的发送配置）

