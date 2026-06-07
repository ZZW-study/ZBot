"""TTLCache 实现的单元测试。"""

from src.cache import TTLCache


def test_set_and_get():
    cache = TTLCache(max_size=10, ttl_seconds=60)
    cache.set("k", "v")
    assert cache.get("k") == "v"


def test_missing_key_returns_none():
    cache = TTLCache(max_size=10, ttl_seconds=60)
    assert cache.get("missing") is None


def test_delete_returns_true_when_present():
    cache = TTLCache(max_size=10, ttl_seconds=60)
    cache.set("a", 1)
    assert cache.delete("a") is True
    assert cache.get("a") is None


def test_delete_returns_false_when_absent():
    cache = TTLCache(max_size=10, ttl_seconds=60)
    assert cache.delete("ghost") is False


def test_size_reflects_entries():
    cache = TTLCache(max_size=10, ttl_seconds=60)
    assert cache.size() == 0
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.size() == 2