"""
智能体持久化记忆系统
核心功能：实现双层记忆存储（长期记忆+会话历史），通过LLM自动整合对话历史，避免上下文溢出，永久留存关键信息
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING # Python 导入模块会执行全量代码，顶层相互导入形成加载死循环；所以导入此
from loguru import logger
from nanobot.utils.helpers import ensure_dir


# 类型检查开关：仅在IDE静态检查时生效，运行时不执行，解决循环导入问题
if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session 


# ====================== LLM的「记忆保存指令」 ======================
# 固定的工具配置，告诉LLM：必须调用save_memory函数，且严格按照指定格式返回结果
_SAVE_MEMORY_TOOL = [
    {
        "type": "function",  # 工具类型：函数调用
        "function": {
            "name": "save_memory",  # 函数名称：保存记忆
            "description": "将记忆整合结果保存到持久化存储中。",  # 函数功能描述
            "parameters": {  # 函数必须传入的参数格式
                "type": "object",
                "properties": {
                    # 参数1：历史条目（简短摘要，用于快速检索）
                    "history_entry": {
                        "type": "string",
                        "description": (
                            "一段2-5句话的摘要，总结对话中的关键事件/决策/主题。"
                            "必须以 [年月日 时分] 开头，内容要方便grep命令搜索关键信息。"
                        ),
                    },
                    # 参数2：长期记忆更新（完整的markdown格式长期记忆）
                    "memory_update": {
                        "type": "string",
                        "description": (
                            "完整更新后的长期记忆（markdown格式）。"
                            "包含所有旧事实+新事实，无更新则返回原内容。"
                        ),
                    },
                },
                "required": ["history_entry", "memory_update"],  # 两个参数为必填项
            },
        },
    }
]



# ======================双层记忆存储管理器类======================
class MemoryStore:
    """
    双层记忆架构设计：
    1. MEMORY.md：长期记忆 → 存储永久有效的事实、偏好、关键信息
    2. HISTORY.md：会话历史 → 存储精简的对话摘要，支持文本搜索（grep）
    """
    def __init__(self,workspace: Path):
        """
        初始化记忆存储系统
        :param workspace: 项目工作根目录，记忆文件会存放在该目录下的memory文件夹中
        """
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"  
        self.history_file = self.memory_dir / "HISTORY.md"


    def read_long_term(self) ->str:
        """读取长期记忆文件内容，文件不存在则返回空字符串"""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        else:
            return ""


    def write_long_term(self, content: str) -> None:
        """覆盖写入长期记忆文件（全量更新）"""
        self.memory_file.write_text(content, encoding="utf-8")


    def append_history(self, entry: str) -> None:
        """追加写入会话历史文件（换行分隔，不覆盖旧内容）"""
        with open(self.history_file, mode="a", encoding="utf-8") as f:
            f.write(entry.strip() + "\n\n")


    def get_memory_context(self) ->str:
        """
        获取可直接喂给LLM的记忆上下文
        用于在对话时，让LLM知道之前的长期记忆
        """
        long_term = self.read_long_term()
        return f"## 长期记忆\n{long_term}" if long_term else ""


    async def consolidate(
            self,
            session: Session,
            provider: LLMProvider,
            model: str,
            *, # 参数分隔符，用于强制分隔位置参数和关键字参数(一个必须传，一个可传可不传)
            archive_all: bool = False,   # 是否归档所有消息（默认：只归档旧消息）
            memory_window: int = 50,     # 保留在上下文的最新消息数量（默认50条）
    ):
            """
            记忆整合：将旧的对话消息 → 交给LLM处理 → 保存到双层记忆文件
            作用：解决LLM上下文长度限制，自动精简历史，永久留存关键信息
            返回值：True=整合成功/无需整合，False=整合失败
            """
            # 1.判断需要整合的旧消息
            if archive_all:
                # 强制归档：处理会话中所有消息 
                old_messages = session.messages
                keep_count = 0
                logger.info("记忆消息全部归档，共处理{}条消息",len(session.messages))
            else:
                # 常规归档：只整合「超出保留窗口的旧消息」，最新的消息保留在上下文
                keep_count = memory_window // 2  # 保留最新25条
                # 如果总消息数 ≤ 保留数量，无需整合
                if len(session.messages) <= keep_count:
                    return True
                # 如果上一次整合后没有新消息，无需整合
                if len(session.messages) - session.last_consolidated <= 0:
                    return True
                # 提取：上一次整合后 → 倒数25条之前 的所有旧消息
                old_messages = session.messages[session.last_consolidated:-keep_count]
                # 无旧消息，直接返回
                if not old_messages:
                    return True
                logger.info("记忆整合: 待整合 {} 条，保留最新 {} 条", len(old_messages), keep_count)


            # 2.格式化旧消息为纯文本
            lines = []
            for m in old_messages:
                # 跳过空内容消息
                if not m.get("content"):
                    continue
                # 拼接工具使用标记（如果调用了工具）
                tools = f" [工具: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
                # 格式化消息：[时间戳] 角色: 内容（工具）
                lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

            # 3.拼接LLM提示词
            # 获取当前已有的长期记忆
            current_memory = self.read_long_term()
            # 构造提示词：告诉LLM需要处理对话，并调用save_memory工具
            prompt = f"""处理以下对话，并调用save_memory工具完成记忆整合。
            ## 当前长期记忆
{current_memory or "(空)"}

## 待处理对话
{chr(10).join(lines)}"""

            # 4：调用LLM执行记忆整合
            try:
                # 调用LLM聊天接口，强制使用save_memory工具
                response = await provider.chat(
                    messages=[
                        # 系统提示：定义LLM角色为「记忆整合智能体」
                        {"role": "system", "content": "你是一个记忆整合智能体，必须调用save_memory工具处理对话。"},
                        # 用户提示：传入待处理的记忆和对话
                        {"role": "user", "content": prompt},
                    ],
                    tools=_SAVE_MEMORY_TOOL,  # 绑定工具
                    model=model,              # 指定模型
                )

                # 5：校验LLM是否正确调用工具
                # 如果LLM没有调用save_memory工具，警告并返回失败
                if not response.has_tool_calls:
                    logger.warning("记忆整合：LLM未调用save_memory工具，跳过")
                    return False

                # 获取工具调用的参数
                args = response.tool_calls[0].arguments
                # 兼容处理：部分LLM返回JSON字符串，需要转字典
                if isinstance(args, str):
                    args = json.loads(args)
                # 兼容处理：部分LLM返回列表，取第一个字典
                if isinstance(args, list):
                    if args and isinstance(args[0], dict):
                        args = args[0]
                    else:
                        logger.warning("记忆整合：参数格式错误（空列表/非字典）")
                        return False
                # 最终校验参数必须是字典
                if not isinstance(args, dict):
                    logger.warning("记忆整合：参数类型错误 {}", type(args).__name__)
                    return False

                # 6：保存整合结果到文件
                # 1. 保存会话历史摘要
                if entry := args.get("history_entry"):
                    # 兼容非字符串格式，转为JSON字符串
                    if not isinstance(entry, str):
                        entry = json.dumps(entry, ensure_ascii=False)
                    self.append_history(entry)

                # 2. 保存更新后的长期记忆
                if update := args.get("memory_update"):
                    if not isinstance(update, str):
                        update = json.dumps(update, ensure_ascii=False)
                    # 只有内容发生变化时，才写入文件（避免无意义覆盖）
                    if update != current_memory:
                        self.write_long_term(update)

                # 7：更新会话整合标记
                # 记录本次整合的位置，下次只整合新消息
                session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
                logger.info("记忆整合完成：总消息{}条，最后整合位置={}", len(session.messages), session.last_consolidated)
                return True

            # 异常捕获：记录错误日志，返回失败
            except Exception:
                logger.exception("记忆整合失败")
                return False

