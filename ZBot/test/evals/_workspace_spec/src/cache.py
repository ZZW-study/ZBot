"""TTL+LRU 混合缓存(含 1 个 off-by-one bug, 留作评测任务发现)。

设计:
  - _data: OrderedDict[key, (expiry_monotonic, value)]
  - get(key): 命中后移到末尾(LRU touch); 过期返回 None
  - set(key, value, ttl=None): 设值, 自动 LRU 淘汰
  - delete(key): 删除键
  - size(): 当前条目数

边界: 命中率 80% 左右时偶发返回 None 是因为淘汰阈值错了 1。
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """带过期时间的缓存, 命中时按 LRU 把 key 移到队尾."""

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
        # BUG: off-by-one — 应该是 > _max_size, 现在 >= 多保留 1 个
        # 现象: 高命中压力下 _data 实际容量 = _max_size + 1,
        #       进而 set 后再 get, 部分 key 表现"被淘汰但其实还在"
        while len(self._data) >= self._max_size:
            self._data.popitem(last=False)

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def size(self) -> int:
        return len(self._data)
