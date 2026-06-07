"""Shared pytest fixtures for API tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ZBot.backend.app import app


@pytest.fixture
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect workspace-bound code (lifespan, ThreadManager) to a temp directory.

    The default `workspace = Path.home() / ".ZBot" / "workspace"` would touch the
    user's real files. We patch the `Path.home` reference inside `ZBot.backend.app`
    so the lifespan falls back to `tmp_path / ".ZBot" / "workspace"`.
    """
    from ZBot.backend import app as app_mod

    class _FakeHome:
        def __call__(self) -> Path:
            return tmp_path

    monkeypatch.setattr(app_mod.Path, "home", _FakeHome())
    yield tmp_path / ".ZBot" / "workspace"


@pytest.fixture
def client(isolated_workspace: Path) -> Iterator[TestClient]:
    """FastAPI TestClient with lifespan triggered (so app.state is initialized).

    Depends on `isolated_workspace` so all thread/run/session state is created
    under a temp directory and never touches the user's real ~/.ZBot/workspace.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect config load/save to a temp file so tests don't touch ~/.ZBot/config.json.

    Both `ZBot.services.config.paths.get_config_path` (the source) and the
    references imported into `ZBot.services.config.loader` are patched so that
    `load_config()` / `save_config()` see the temp path.
    """
    from ZBot.services.config import loader as loader_mod
    from ZBot.services.config import paths as paths_mod
    from ZBot.services.config.config import config_cache

    tmp_config = tmp_path / "config.json"

    def _temp_path() -> Path:
        return tmp_config

    # Patch in the source module
    monkeypatch.setattr(paths_mod, "get_config_path", _temp_path)
    # Patch the imported reference in the loader (load_config / save_config use it)
    monkeypatch.setattr(loader_mod, "get_config_path", _temp_path)
    # Reset cache so load_config() re-reads from the new path
    config_cache.invalidate()
    yield tmp_config
    config_cache.invalidate()
    if tmp_config.exists():
        tmp_config.unlink()
