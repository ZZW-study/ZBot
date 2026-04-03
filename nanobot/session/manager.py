"""
会话管理模块：负责处理AI对话的历史记录存储、加载、缓存和持久化
核心功能：
1. 用Session类封装单条对话会话的所有数据（消息、时间、元数据）
2. 用SessionManager类管理所有会话的磁盘存储、内存缓存、文件迁移
3. 采用JSONL格式存储消息（逐行JSON），高效读写且兼容大文件
"""

import json
import shutil #  shell utility（shell 工具），专门用来简化文件和文件夹的批量 / 高级操作。
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from loguru import logger

from nanobot.config import get_legacy_sessions_dir
from nanobot.utils.helpers import ensure_dir, safe_filename


@dataclass
class Session:
    """
    对话会话实体类:
    1. 消息以JSONL格式存储，便于逐行读取/追加，无需加载整个文件
    2. 消息【只允许追加】，目的：提升大模型(LLM)的缓存效率
    3. 消息合并（总结）只会写入MEMORY.md/HISTORY.md，不会修改原始消息列表
    """
    key: str # 会话标识
    messages: list[dict[str, Any]] = field(default_factory=list) # 对话消息列表
    created_at: datetime = field(default_factory=datetime.now)   # 会话创建时间
    updated_at: datetime = field(default_factory=datetime.now)   # 会话最后更新时间（新增消息/清空时更新）
    metadata: dict[str, Any] = field(default_factory=dict)       # 会话元数据：存储扩展信息（如用户配置、模型参数等）  
    last_consolidated: int = 0                                   # 已合并的消息数量：标记哪些消息已经被总结写入文件，避免重复合并


    def add_message(self,role: str,content: str,**kwargs: Any) ->None:
        """
        向会话中【追加】一条新消息
        Args:
            role: 消息角色（user-用户 / assistant-AI / system-系统 / tool-工具）
            content: 消息文本内容
            **kwargs: 额外参数（如工具调用信息、消息ID等）
        """
        # 构造标准消息字典
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }

        self.messages.append(msg)
        self.updated_at = datetime.now()


    def get_history(self,max_messages: int = 500) ->list[dict[str,Any]]:
        """
        获取用于LLM输入的对话历史
        1. 只返回【未合并】的消息（已合并的消息已总结为文件，无需重复传入）
        2. 限制最大消息数量（避免超过LLM上下文长度限制）
        3. 自动裁剪开头非用户消息（避免孤立的工具返回结果，保证对话上下文合法）
        """
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]

        # 删除开头的非用户消息，避免孤立的工具结果/AI回复
        for i,m in enumerate(sliced): 
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        # 精简：构造LLM需要的最小消息结构（剔除无用字段）
        out: list[dict[str, Any]] = []
        for m in sliced:
            # 基础字段：角色+内容
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            # 可选字段：如果存在工具调用相关字段，一并保留（LLM需要）
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        
        # 返回最终可直接传入LLM的对话历史
        return out


    def clear(self) ->None:
        """
        清空当前会话（重置会话）
        操作：清空消息列表 + 重置合并计数 + 更新时间
        """
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    会话管理器：负责所有会话的【内存缓存】+【磁盘持久化】+【文件迁移】
    存储规则：每个会话对应一个JSONL文件，存储在工作区的sessions目录下
    """
    def __init__(self, workspace: Path | str):
        """
        初始化会话管理器
        """
        self.workspace = Path(workspace)
        self.sessions_dir = ensure_dir(self.workspace / "sessions")      # 会话存储目录
        self.legacy_sessions_dir = get_legacy_sessions_dir()             # 旧版本（遗留）会话目录，仅在迁移时访问
        self._cache: dict[str, Session] = {}                 # 内存缓存：key=会话标识，value=Session对象


    def _get_session_path(self,key: str) ->Path:
        """【私有方法】获取当前版本会话的文件路径"""
        safe_key = safe_filename(key.replace(":","_"))
        return self.sessions_dir / f"{safe_key}.jsonl"


    def _get_legacy_session_path(self, key: str) -> Path:
        """获取旧版本（遗留）会话的文件路径"""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"


    def get_or_create(self, key: str) -> Session:
        """
        【核心对外方法】获取会话：缓存有则直接返回，无则加载/创建
        流程：内存缓存 → 磁盘加载 → 新建空会话
        """
        # 第一步：检查内存缓存
        if key in self._cache:
            return self._cache[key]

        # 第二步：尝试从磁盘加载会话
        session = self._load(key)
        # 第三步：加载失败（文件不存在/损坏），创建全新会话
        if session is None:
            session = Session(key=key)

        # 将会话存入内存缓存，下次直接读取
        self._cache[key] = session
        return session


    def _load(self, key: str) -> Session | None:
        """
        【私有方法】从磁盘加载会话（支持旧版本文件迁移）
        流程：
        1. 尝试加载新版本会话文件
        2. 不存在则尝试加载旧版本文件，并自动迁移到新版本目录
        3. 解析JSONL文件：第一行是元数据，后续行是消息
        """
        # 获取新版本会话路径
        path = self._get_session_path(key)
        # 如果新版本文件不存在，检查旧版本文件
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            # 旧版本文件存在 → 自动迁移到新版本目录
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("已从就路径迁移会话{}", key)
                except Exception:
                    # 迁移失败，记录错误日志，不中断程序
                    logger.exception("迁移会话 {} 失败", key)

        # 最终文件仍不存在，返回None
        if not path.exists():
            return None

        # 开始解析JSONL文件
        try:
            # 初始化变量
            messages = []          # 消息列表
            metadata = {}         # 元数据
            created_at = None     # 创建时间
            last_consolidated = 0 # 已合并消息数

            # 逐行读取JSONL文件（高效，无需加载整个文件）
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行
                    if not line:
                        continue

                    # 解析单行JSON
                    data = json.loads(line)

                    # 第一行是【元数据行】（标记_type: metadata）
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        # 解析创建时间（兼容空值）
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    # 其余行是【消息行】
                    else:
                        messages.append(data)

            # 构造并返回Session对象
            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            # 文件损坏/解析失败，记录警告，返回None
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """
        【核心对外方法】将会话持久化保存到磁盘
        存储格式：
        第一行：元数据（_type: metadata）
        后续行：每条消息逐行存储（JSONL格式）
        """
        # 获取会话文件路径
        path = self._get_session_path(session.key)

        # 覆盖写入文件（每次保存全量写入，保证数据一致性）
        with open(path, "w", encoding="utf-8") as f:
            # 1. 写入元数据行
            metadata_line = {
                "_type": "metadata",          # 标记为元数据
                "key": session.key,           # 会话标识
                "created_at": session.created_at.isoformat(),  # 创建时间
                "updated_at": session.updated_at.isoformat(),  # 更新时间
                "metadata": session.metadata,  # 扩展元数据
                "last_consolidated": session.last_consolidated  # 已合并数
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            
            # 2. 逐行写入所有消息
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        # 更新内存缓存（保证缓存与磁盘数据一致）
        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """
        【对外方法】使内存缓存失效（删除指定会话的缓存）
        场景：手动删除会话文件后，清空内存缓存
        """
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        【对外方法】列出所有已保存的会话
        逻辑：遍历sessions目录下所有.jsonl文件，读取第一行元数据
        返回：按【最后更新时间】倒序排列的会话列表
        """
        sessions = []

        # 遍历所有.jsonl会话文件
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # 只读取第一行（元数据），高效
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        # 只处理元数据行
                        if data.get("_type") == "metadata":
                            # 兼容旧文件：无key则从文件名还原（下划线→冒号）
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            sessions.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                # 损坏文件直接跳过
                continue

        # 按最后更新时间倒序排序（最新的排在前面）
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)










