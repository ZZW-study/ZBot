"""SessionManager 会话持久化 CRUD 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ZBot.session.manager import SessionManager


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """临时工作区目录。"""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def manager(workspace_path: Path) -> SessionManager:
    """创建 SessionManager 实例。"""
    return SessionManager(workspace=workspace_path)


class TestSessionManagerGetOrCreate:
    """get_or_create 测试。"""

    @pytest.mark.asyncio
    async def test_new_session_returns_created(self, manager: SessionManager):
        """不存在的会话应返回 (Session, False)。"""
        session, is_existing = await manager.get_or_create("new_session")
        assert session.session_name == "new_session"
        assert is_existing is False
        assert session.messages == []

    @pytest.mark.asyncio
    async def test_existing_session_returns_loaded(self, manager: SessionManager, workspace_path: Path):
        """已保存的会话应返回 (Session, True)。"""
        # 先创建一个会话并保存
        session1, _ = await manager.get_or_create("existing_session")
        session1.messages.append({"role": "user", "content": "hello"})
        await manager.save(session1)

        # 清除缓存，模拟新请求
        manager._cache.clear()

        # 再次获取应返回已加载的会话
        session2, is_existing = await manager.get_or_create("existing_session")
        assert is_existing is True
        assert len(session2.messages) == 1
        assert session2.messages[0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_cached_session_returns_immediately(self, manager: SessionManager):
        """缓存中的会话应直接返回，不读磁盘。"""
        session1, _ = await manager.get_or_create("cached_session")
        session1.messages.append({"role": "user", "content": "cached"})

        # 第二次调用应返回缓存
        session2, is_existing = await manager.get_or_create("cached_session")
        assert session2 is session1  # 同一对象
        assert len(session2.messages) == 1


class TestSessionManagerSave:
    """save 测试。"""

    @pytest.mark.asyncio
    async def test_save_creates_jsonl_file(self, manager: SessionManager, workspace_path: Path):
        """保存后应生成 .jsonl 文件。"""
        session, _ = await manager.get_or_create("save_test")
        session.messages.append({"role": "user", "content": "test message"})
        await manager.save(session)

        # 检查文件存在
        session_file = workspace_path / "sessions" / "save_test.jsonl"
        assert session_file.exists()

        # 检查内容格式
        lines = session_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2  # metadata + 1 message
        metadata = json.loads(lines[0])
        assert metadata["_type"] == "metadata"
        message = json.loads(lines[1])
        assert message["role"] == "user"
        assert message["content"] == "test message"


class TestSessionManagerDelete:
    """delete 测试。"""

    @pytest.mark.asyncio
    async def test_delete_removes_session(self, manager: SessionManager):
        """删除后应移除缓存和文件。"""
        session, _ = await manager.get_or_create("delete_test")
        session.messages.append({"role": "user", "content": "to delete"})
        await manager.save(session)

        # 删除
        result = await manager.delete("delete_test")
        assert result is True
        assert "delete_test" not in manager._cache

        # 再次获取应返回新会话
        session2, is_existing = await manager.get_or_create("delete_test")
        assert is_existing is False
        assert session2.messages == []

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, manager: SessionManager):
        """删除不存在的会话应返回 False。"""
        result = await manager.delete("nonexistent")
        assert result is False


class TestSessionLoadErrorHandling:
    """会话加载错误处理测试（P-007 修复验证）。"""

    @pytest.mark.asyncio
    async def test_corrupted_json_returns_none(self, manager: SessionManager, workspace_path: Path):
        """损坏的 JSONL 文件应返回 None 而非抛出异常。"""
        # 创建损坏的文件
        session_file = workspace_path / "sessions" / "corrupted.jsonl"
        session_file.write_text("not valid json\n", encoding="utf-8")

        # 加载应返回 None
        session = await manager._load("corrupted")
        assert session is None

    @pytest.mark.asyncio
    async def test_missing_file_returns_none(self, manager: SessionManager):
        """不存在的文件应返回 None。"""
        session = await manager._load("missing")
        assert session is None
