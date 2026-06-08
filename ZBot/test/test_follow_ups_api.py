"""Tests for /api/sessions/{name}/follow-ups 端点 (steering 队列)。"""

from __future__ import annotations

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _create_session(client: TestClient, name: str = "test-fu-session") -> None:
    client.post("/api/sessions", json={"name": name})


# ---------------------------------------------------------------------------
# 空 / 列表
# ---------------------------------------------------------------------------

def test_empty_queue_returns_200_and_empty_list(client: TestClient, isolated_config):
    _create_session(client)
    r = client.get("/api/sessions/test-fu-session/follow-ups")
    assert r.status_code == 200
    assert r.json() == []


def test_list_on_missing_session_returns_404(client: TestClient, isolated_config):
    r = client.get("/api/sessions/no-such-session/follow-ups")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 入队
# ---------------------------------------------------------------------------

def test_enqueue_returns_201_with_follow_up(client: TestClient, isolated_config):
    _create_session(client)
    r = client.post(
        "/api/sessions/test-fu-session/follow-ups",
        json={"message": "follow up message"},
    )
    assert r.status_code == 201
    body = r.json()
    assert (body.get("followUpId") or body.get("follow_up_id"))
    assert body["message"] == "follow up message"


def test_enqueue_then_list_returns_item(client: TestClient, isolated_config):
    _create_session(client)
    enqueue = client.post(
        "/api/sessions/test-fu-session/follow-ups",
        json={"message": "queued msg"},
    )
    fu_id = enqueue.json().get("followUpId") or enqueue.json().get("follow_up_id")

    r = client.get("/api/sessions/test-fu-session/follow-ups")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert (items[0].get("followUpId") or items[0].get("follow_up_id")) == fu_id
    assert items[0]["message"] == "queued msg"


def test_enqueue_multiple_preserves_order(client: TestClient, isolated_config):
    _create_session(client)
    ids: list[str] = []
    for msg in ["first", "second", "third"]:
        r = client.post(
            "/api/sessions/test-fu-session/follow-ups",
            json={"message": msg},
        )
        ids.append(r.json().get("followUpId") or r.json().get("follow_up_id"))

    r = client.get("/api/sessions/test-fu-session/follow-ups")
    items = r.json()
    assert [i["message"] for i in items] == ["first", "second", "third"]


def test_enqueue_on_missing_session_returns_404(client: TestClient, isolated_config):
    r = client.post(
        "/api/sessions/no-such-session/follow-ups",
        json={"message": "x"},
    )
    assert r.status_code == 404


def test_enqueue_empty_message_returns_422(client: TestClient, isolated_config):
    _create_session(client)
    r = client.post(
        "/api/sessions/test-fu-session/follow-ups",
        json={"message": ""},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 移除
# ---------------------------------------------------------------------------

def test_remove_returns_204_then_list_empty(client: TestClient, isolated_config):
    _create_session(client)
    enqueue = client.post(
        "/api/sessions/test-fu-session/follow-ups",
        json={"message": "to be removed"},
    )
    fu_id = enqueue.json().get("followUpId") or enqueue.json().get("follow_up_id")

    r = client.delete(f"/api/sessions/test-fu-session/follow-ups/{fu_id}")
    assert r.status_code == 204

    # 队列应为空
    r2 = client.get("/api/sessions/test-fu-session/follow-ups")
    assert r2.json() == []


def test_remove_unknown_returns_404(client: TestClient, isolated_config):
    r = client.delete("/api/sessions/test-fu-session/follow-ups/no-such-fu-id")
    assert r.status_code == 404


def test_remove_one_of_many_keeps_others(client: TestClient, isolated_config):
    _create_session(client)
    ids: list[str] = []
    for msg in ["keep-1", "remove", "keep-2"]:
        enqueue = client.post(
            "/api/sessions/test-fu-session/follow-ups",
            json={"message": msg},
        )
        ids.append(enqueue.json().get("followUpId") or enqueue.json().get("follow_up_id"))

    # 移除 the middle one
    r = client.delete(f"/api/sessions/test-fu-session/follow-ups/{ids[1]}")
    assert r.status_code == 204

    # 另两条应按原顺序保留
    r2 = client.get("/api/sessions/test-fu-session/follow-ups")
    items = r2.json()
    assert [i["message"] for i in items] == ["keep-1", "keep-2"]
