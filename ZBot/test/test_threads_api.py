"""Tests for /api/threads/* endpoints (RESTful thread resource)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ZBot.backend.app import app


@pytest.fixture
def client():
    # Use context manager so FastAPI lifespan is triggered and
    # app.state.thread_manager / run_registry / follow_up_queue get initialized.
    with TestClient(app) as c:
        yield c


def test_list_threads(client: TestClient):
    r = client.get("/api/threads")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_and_get_thread(client: TestClient):
    name = "test-thread-api-1"
    r = client.post("/api/threads", json={"name": name})
    assert r.status_code == 201
    assert r.headers.get("Location") == f"/api/threads/{name}"
    body = r.json()
    assert body["name"] == name
    assert body["message_count"] == 0
    assert body["messages"] == []

    # GET returns 200 with same body
    r2 = client.get(f"/api/threads/{name}")
    assert r2.status_code == 200
    assert r2.json()["name"] == name

    # cleanup
    client.delete(f"/api/threads/{name}")


def test_create_duplicate_returns_409(client: TestClient):
    name = "test-thread-dup"
    client.post("/api/threads", json={"name": name})
    r = client.post("/api/threads", json={"name": name})
    assert r.status_code == 409
    assert "detail" in r.json()
    client.delete(f"/api/threads/{name}")


def test_get_nonexistent_returns_404(client: TestClient):
    """Critical regression test: GET must NOT have side effects (no get_or_create)."""
    r = client.get("/api/threads/this-thread-does-not-exist-xyz")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_patch_composite_update(client: TestClient):
    name = "test-thread-patch"
    client.post("/api/threads", json={"name": name})
    r = client.patch(f"/api/threads/{name}", json={"title": "My Thread", "pinned": True})
    assert r.status_code == 200
    # response shows the updated state (after update_metadata + reload)
    # Note: the in-memory cache may show the old soft fields until the file is reloaded.
    client.delete(f"/api/threads/{name}")


def test_patch_empty_body_returns_400(client: TestClient):
    name = "test-thread-empty"
    client.post("/api/threads", json={"name": name})
    r = client.patch(f"/api/threads/{name}", json={})
    assert r.status_code == 400
    client.delete(f"/api/threads/{name}")


def test_patch_rename(client: TestClient):
    name = "test-thread-rename"
    new_name = "test-thread-renamed"
    client.post("/api/threads", json={"name": name})
    r = client.patch(f"/api/threads/{name}", json={"name": new_name})
    assert r.status_code == 200
    assert r.json()["name"] == new_name
    # old name should 404
    assert client.get(f"/api/threads/{name}").status_code == 404
    # new name should 200
    assert client.get(f"/api/threads/{new_name}").status_code == 200
    client.delete(f"/api/threads/{new_name}")


def test_delete_thread(client: TestClient):
    name = "test-thread-delete"
    client.post("/api/threads", json={"name": name})
    r = client.delete(f"/api/threads/{name}")
    assert r.status_code == 204
    # delete again -> 404
    r2 = client.delete(f"/api/threads/{name}")
    assert r2.status_code == 404


def test_invalid_thread_name_returns_422(client: TestClient):
    r = client.post("/api/threads", json={"name": "x" * 200})  # too long
    assert r.status_code == 422
