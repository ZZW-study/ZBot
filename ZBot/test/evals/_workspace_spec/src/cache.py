"""评测用 fixture：简单的 TTL+LRU 混合缓存。"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """带过期时间的缓存。命中时按 LRU 把 key 移到队尾。"""

    def __init__(self, max_size: int = 256, ttl_seconds: int = 60) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()

    def get(self, key: str) -> Any:
        if key not in self._data:
            return None
        expiry, value = self._data[key]
        if expiry < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expiry = time.monotonic() + (ttl if ttl is not None else self._ttl_seconds)
        self._data[key] = (expiry, value)
        self._data.move_to_end(key)
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def size(self) -> int:
        return len(self._data)