"""Tests for /api/agent/files and /api/threads/{name}/runs/* endpoints."""

from __future__ import annotations

import io
import time

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_thread(client: TestClient, name: str = "test-runs-thread") -> None:
    """Create a thread; ignore 409 if it already exists."""
    client.post("/api/threads", json={"name": name})


def _write_config_for_failure(isolated_config) -> None:
    """Write a config that triggers AgentSetupError (empty model)."""
    import json
    isolated_config.write_text(
        json.dumps({"model": "", "provider": "auto"}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# File upload
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
    # Empty list is rejected
    r = client.post("/api/agent/files", files=[])
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Run lifecycle - start, status, cancel
# ---------------------------------------------------------------------------

def test_start_run_on_missing_thread_returns_404(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    r = client.post(
        "/api/threads/does-not-exist/runs",
        json={"message": "hello"},
    )
    assert r.status_code == 404


def test_start_run_when_no_config_returns_503(client: TestClient, isolated_config):
    _create_thread(client)
    # No config file at all - get_config_or_503 should 503
    r = client.post(
        "/api/threads/test-runs-thread/runs",
        json={"message": "hello"},
    )
    assert r.status_code == 503


def test_start_run_returns_201_with_run_id(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    _create_thread(client)
    r = client.post(
        "/api/threads/test-runs-thread/runs",
        json={"message": "hello"},
    )
    assert r.status_code == 201
    body = r.json()
    run_id = body.get("runId") or body.get("run_id")
    assert isinstance(run_id, str) and len(run_id) > 0
    assert body.get("threadName") == "test-runs-thread" or body.get("thread_name") == "test-runs-thread"
    # cleanup: cancel the run to free the background task
    client.delete(f"/api/threads/test-runs-thread/runs/{run_id}")


def test_get_run_status_returns_state(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    _create_thread(client)
    start = client.post(
        "/api/threads/test-runs-thread/runs",
        json={"message": "hi"},
    )
    run_id = (start.json().get("runId") or start.json().get("run_id"))

    r = client.get(f"/api/threads/test-runs-thread/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert (body.get("runId") or body.get("run_id")) == run_id
    assert body["status"] in {"queued", "running", "completed", "failed", "cancelled"}
    # cleanup
    client.delete(f"/api/threads/test-runs-thread/runs/{run_id}")


def test_get_unknown_run_returns_404(client: TestClient, isolated_config):
    r = client.get("/api/threads/test-runs-thread/runs/no-such-run")
    assert r.status_code == 404


def test_get_run_wrong_thread_returns_404(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    _create_thread(client)
    start = client.post(
        "/api/threads/test-runs-thread/runs",
        json={"message": "hi"},
    )
    run_id = (start.json().get("runId") or start.json().get("run_id"))

    r = client.get(f"/api/threads/wrong-thread/runs/{run_id}")
    assert r.status_code == 404
    # cleanup
    client.delete(f"/api/threads/test-runs-thread/runs/{run_id}")


def test_cancel_unknown_run_returns_404(client: TestClient, isolated_config):
    r = client.delete("/api/threads/test-runs-thread/runs/no-such-run")
    assert r.status_code == 404


def test_cancel_run_returns_204(client: TestClient, isolated_config):
    _write_config_for_failure(isolated_config)
    _create_thread(client)
    start = client.post(
        "/api/threads/test-runs-thread/runs",
        json={"message": "hi"},
    )
    run_id = (start.json().get("runId") or start.json().get("run_id"))

    r = client.delete(f"/api/threads/test-runs-thread/runs/{run_id}")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

def test_sse_streams_session_meta_and_failure_event(client: TestClient, isolated_config):
    """A failing run (no model configured) should produce session_meta + task_complete events."""
    _write_config_for_failure(isolated_config)
    _create_thread(client)
    start = client.post(
        "/api/threads/test-runs-thread/runs",
        json={"message": "hi"},
    )
    assert start.status_code == 201
    run_id = (start.json().get("runId") or start.json().get("run_id"))

    # Open SSE stream with timeout
    seen_event_types: set[str] = set()
    deadline = time.time() + 15.0
    try:
        with client.stream(
            "GET",
            f"/api/threads/test-runs-thread/runs/{run_id}/events",
        ) as resp:
            assert resp.status_code == 200
            ct = resp.headers.get("content-type", "")
            assert "text/event-stream" in ct
            # Read SSE events
            for line in resp.iter_lines():
                if time.time() > deadline:
                    break
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                    seen_event_types.add(event_type)
                    if "task_complete" in event_type or "error" in event_type:
                        # Got terminal event, can stop
                        break
                elif line.startswith(":"):
                    # SSE comment (heartbeat) - skip
                    continue
    finally:
        # Cancel to clean up background task
        try:
            client.delete(f"/api/threads/test-runs-thread/runs/{run_id}")
        except Exception:
            pass

    # We must have received session_meta and at least one terminal event
    assert "session_meta" in seen_event_types, f"Missing session_meta, got {seen_event_types}"
    assert (
        "event_msg" in seen_event_types
    ), f"Missing event_msg wrapper, got {seen_event_types}"


def test_sse_unknown_run_returns_404(client: TestClient, isolated_config):
    r = client.get("/api/threads/test-runs-thread/runs/no-such-run/events")
    assert r.status_code == 404
