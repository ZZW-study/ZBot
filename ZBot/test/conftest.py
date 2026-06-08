"""API 测试共享的 pytest fixture。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ZBot.backend.app import app


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """把绑定工作区的代码 (lifespan、SessionManager) 重定向到临时目录。

    默认的 `workspace = Path.home() / ".ZBot" / "workspace"` 会触碰
    用户的真实文件。我们 patch `ZBot.backend.app` 里的 `Path.home` 引用,
    使 lifespan 回退到 `tmp_path / ".ZBot" / "workspace"`。
    """
    from ZBot.backend import app as app_mod

    class _FakeHome:
        def __call__(self) -> Path:
            return tmp_path

    # 用 staticmethod 包装,避免 bound method 在 monkeypatch 下的边缘问题。
    monkeypatch.setattr(app_mod.Path, "home", staticmethod(lambda: tmp_path))
    yield tmp_path / ".ZBot" / "workspace"


@pytest.fixture(autouse=True)
def _clean_file_store():
    """autouse 清理 file_store,避免跨测试文件泄漏(原本只在 test_agent_run_service_close.py 局部)。"""
    from ZBot.backend.handlers.agent_files import file_store

    file_store.clear()
    yield
    file_store.clear()


@pytest.fixture
def client(isolated_workspace: Path) -> Iterator[TestClient]:
    """FastAPI TestClient 触发 lifespan (使 app.state 被初始化)。

    依赖 `isolated_workspace`,使所有 session/run/follow-up 状态都创建于
    临时目录,不会触碰用户的真实 ~/.ZBot/workspace。
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """把 config 加载/保存重定向到临时文件,让测试不触碰 ~/.ZBot/config.json。"""
    from ZBot.services.config import loader as loader_mod
    from ZBot.services.config import paths as paths_mod
    from ZBot.services.config.config import config_cache

    tmp_config = tmp_path / "config.json"

    def _temp_path() -> Path:
        return tmp_config

    monkeypatch.setattr(paths_mod, "get_config_path", _temp_path)
    monkeypatch.setattr(loader_mod, "get_config_path", _temp_path)
    config_cache.invalidate()
    yield tmp_config
    config_cache.invalidate()
    if tmp_config.exists():
        tmp_config.unlink()
