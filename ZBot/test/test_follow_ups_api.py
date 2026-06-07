"""Tests for /api/threads/{name}/follow-ups endpoints (steering queue)."""

from __future__ import annotations

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_thread(client: TestClient, name: str = "test-fu-thread") -> None:
    client.post("/api/threads", json={"name": name})


# ---------------------------------------------------------------------------
# Empty / list
# ---------------------------------------------------------------------------

def test_empty_queue_returns_200_and_empty_list(client: TestClient, isolated_config):
    _create_thread(client)
    r = client.get("/api/threads/test-fu-thread/follow-ups")
    assert r.status_code == 200
    assert r.json() == []


def test_list_on_missing_thread_returns_404(client: TestClient, isolated_config):
    r = client.get("/api/threads/no-such-thread/follow-ups")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def test_enqueue_returns_201_with_follow_up(client: TestClient, isolated_config):
    _create_thread(client)
    r = client.post(
        "/api/threads/test-fu-thread/follow-ups",
        json={"message": "follow up message"},
    )
    assert r.status_code == 201
    body = r.json()
    assert (body.get("followUpId") or body.get("follow_up_id"))
    assert body["message"] == "follow up message"


def test_enqueue_then_list_returns_item(client: TestClient, isolated_config):
    _create_thread(client)
    enqueue = client.post(
        "/api/threads/test-fu-thread/follow-ups",
        json={"message": "queued msg"},
    )
    fu_id = enqueue.json().get("followUpId") or enqueue.json().get("follow_up_id")

    r = client.get("/api/threads/test-fu-thread/follow-ups")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert (items[0].get("followUpId") or items[0].get("follow_up_id")) == fu_id
    assert items[0]["message"] == "queued msg"


def test_enqueue_multiple_preserves_order(client: TestClient, isolated_config):
    _create_thread(client)
    ids: list[str] = []
    for msg in ["first", "second", "third"]:
        r = client.post(
            "/api/threads/test-fu-thread/follow-ups",
            json={"message": msg},
        )
        ids.append(r.json().get("followUpId") or r.json().get("follow_up_id"))

    r = client.get("/api/threads/test-fu-thread/follow-ups")
    items = r.json()
    assert [i["message"] for i in items] == ["first", "second", "third"]


def test_enqueue_on_missing_thread_returns_404(client: TestClient, isolated_config):
    r = client.post(
        "/api/threads/no-such-thread/follow-ups",
        json={"message": "x"},
    )
    assert r.status_code == 404


def test_enqueue_empty_message_returns_422(client: TestClient, isolated_config):
    _create_thread(client)
    r = client.post(
        "/api/threads/test-fu-thread/follow-ups",
        json={"message": ""},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

def test_remove_returns_204_then_list_empty(client: TestClient, isolated_config):
    _create_thread(client)
    enqueue = client.post(
        "/api/threads/test-fu-thread/follow-ups",
        json={"message": "to be removed"},
    )
    fu_id = enqueue.json().get("followUpId") or enqueue.json().get("follow_up_id")

    r = client.delete(f"/api/threads/test-fu-thread/follow-ups/{fu_id}")
    assert r.status_code == 204

    # queue should be empty now
    r2 = client.get("/api/threads/test-fu-thread/follow-ups")
    assert r2.json() == []


def test_remove_unknown_returns_404(client: TestClient, isolated_config):
    r = client.delete("/api/threads/test-fu-thread/follow-ups/no-such-fu-id")
    assert r.status_code == 404


def test_remove_one_of_many_keeps_others(client: TestClient, isolated_config):
    _create_thread(client)
    ids: list[str] = []
    for msg in ["keep-1", "remove", "keep-2"]:
        enqueue = client.post(
            "/api/threads/test-fu-thread/follow-ups",
            json={"message": msg},
        )
        ids.append(enqueue.json().get("followUpId") or enqueue.json().get("follow_up_id"))

    # Remove the middle one
    r = client.delete(f"/api/threads/test-fu-thread/follow-ups/{ids[1]}")
    assert r.status_code == 204

    # The other two should remain in original order
    r2 = client.get("/api/threads/test-fu-thread/follow-ups")
    items = r2.json()
    assert [i["message"] for i in items] == ["keep-1", "keep-2"]
