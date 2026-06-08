"""Tests for /api/agent/files 和 /api/sessions/{name}/runs/* 端点。"""

from __future__ import annotations

import io
import time

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _create_session(client: TestClient, name: str = "test-runs-session") -> None:
    """Create a session; ignore 409 if it already exists."""
    client.post("/api/sessions", json={"name": name})


def _write_config_for_failure(isolated_config) -> None:
    """Write a config that triggers AgentSetupError (empty model)."""
    import json
    isolated_config.write_text(
        json.dumps({"model": "", "provider": "auto"}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 文件上传
# ---------------------------------------------------------------------------

def test_post_files_returns_201_with_file_id(client: TestClient, isolated_config):
    files = [("files", ("hello.txt", io.BytesIO(b"hello world"), "text/plain"))]
    r = client.post("/api/agent/files", files=files)
    assert r.status_code == 201
    body = r.json()
    assert "fileId" in body or "file_id" in body
    fid = body.get("fileId") or body.get("file_id")
    assert isinstance(fid, str) and len(fid) > 0


def test_post_files_no_files_returns_400(client: TestClient, isolated_config):
    # 空 list 被拒绝
    r = client.post("/api/agent/files", files=[])
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Run 生命周期 - 启动、状态、取消
# ---------------------------------------------------------------------------

def test_start_run_on_missing_session_returns_404(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    r = client.post(
        "/api/sessions/does-not-exist/runs",
        json={"message": "hello"},
    )
    assert r.status_code == 404


def test_start_run_when_no_config_returns_503(client: TestClient, isolated_config):
    _create_session(client)
    # 完全没有 config 文件 - get_config_or_503 应 503
    r = client.post(
        "/api/sessions/test-runs-session/runs",
        json={"message": "hello"},
    )
    assert r.status_code == 503


def test_start_run_returns_201_with_run_id(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    _create_session(client)
    r = client.post(
        "/api/sessions/test-runs-session/runs",
        json={"message": "hello"},
    )
    assert r.status_code == 201
    body = r.json()
    run_id = body.get("runId") or body.get("run_id")
    assert isinstance(run_id, str) and len(run_id) > 0
    assert body.get("sessionName") == "test-runs-session" or body.get("session_name") == "test-runs-session"
    # 清理: cancel the run to free the background task
    client.delete(f"/api/sessions/test-runs-session/runs/{run_id}")


def test_get_run_status_returns_state(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    _create_session(client)
    start = client.post(
        "/api/sessions/test-runs-session/runs",
        json={"message": "hi"},
    )
    run_id = (start.json().get("runId") or start.json().get("run_id"))

    r = client.get(f"/api/sessions/test-runs-session/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert (body.get("runId") or body.get("run_id")) == run_id
    assert body["status"] in {"queued", "running", "completed", "failed", "cancelled"}
    # 清理
    client.delete(f"/api/sessions/test-runs-session/runs/{run_id}")


def test_get_unknown_run_returns_404(client: TestClient, isolated_config):
    r = client.get("/api/sessions/test-runs-session/runs/no-such-run")
    assert r.status_code == 404


def test_get_run_wrong_session_returns_404(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    _create_session(client)
    start = client.post(
        "/api/sessions/test-runs-session/runs",
        json={"message": "hi"},
    )
    run_id = (start.json().get("runId") or start.json().get("run_id"))

    r = client.get(f"/api/sessions/wrong-session/runs/{run_id}")
    assert r.status_code == 404
    # 清理
    client.delete(f"/api/sessions/test-runs-session/runs/{run_id}")


def test_cancel_unknown_run_returns_404(client: TestClient, isolated_config):
    r = client.delete("/api/sessions/test-runs-session/runs/no-such-run")
    assert r.status_code == 404


def test_cancel_run_returns_204(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    _create_session(client)
    start = client.post(
        "/api/sessions/test-runs-session/runs",
        json={"message": "hi"},
    )
    run_id = (start.json().get("runId") or start.json().get("run_id"))

    r = client.delete(f"/api/sessions/test-runs-session/runs/{run_id}")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# SSE 流
# ---------------------------------------------------------------------------

def test_sse_streams_session_meta_and_failure_event(client: TestClient, isolated_config):
    """A failing run (no model configured) should produce session_meta + task_complete events."""
    _write_config_for_failure(isolated_config)
    _create_session(client)
    start = client.post(
        "/api/sessions/test-runs-session/runs",
        json={"message": "hi"},
    )
    assert start.status_code == 201
    run_id = (start.json().get("runId") or start.json().get("run_id"))

    # Open SSE 流 with timeout
    seen_event_types: set[str] = set()
    deadline = time.time() + 15.0
    try:
        with client.stream(
            "GET",
            f"/api/sessions/test-runs-session/runs/{run_id}/events",
        ) as resp:
            assert resp.status_code == 200
            ct = resp.headers.get("content-type", "")
            assert "text/event-stream" in ct
            # 读取 SSE 事件
            for line in resp.iter_lines():
                if time.time() > deadline:
                    break
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    seen_event_types.add(event_type)
                    if "task_complete" in event_type or "error" in event_type:
                        # 收到终止事件,可以停止
                        break
                elif line.startswith(":"):
                    # SSE 注释 (heartbeat) - 跳过
                    continue
    finally:
        # 取消以清理后台 task
        try:
            client.delete(f"/api/sessions/test-runs-session/runs/{run_id}")
        except Exception:
            pass

    # 我们必须收到 session_meta 和至少一个终止事件
    assert "session_meta" in seen_event_types, f"Missing session_meta, got {seen_event_types}"
    assert (
        "event_msg" in seen_event_types
    ), f"Missing event_msg wrapper, got {seen_event_types}"


def test_sse_unknown_run_returns_404(client: TestClient, isolated_config):
    r = client.get("/api/sessions/test-runs-session/runs/no-such-run/events")
    assert r.status_code == 404
