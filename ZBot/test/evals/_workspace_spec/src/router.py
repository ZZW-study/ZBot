"""极简的 path-prefix 路由器，用于分发 HTTP 请求。"""

from __future__ import annotations

import re
from typing import Callable


class Route:
    __slots__ = ("method", "pattern", "handler")

    def __init__(self, method: str, pattern: str, handler: Callable) -> None:
        self.method = method.upper()
        self.pattern = re.compile(pattern)
        self.handler = handler

    def match(self, method: str, path: str) -> re.Match | None:
        if method.upper() != self.method:
            return None
        return self.pattern.fullmatch(path)


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, pattern: str, handler: Callable) -> None:
        self._routes.append(Route(method, pattern, handler))

    def dispatch(self, method: str, path: str):
        for route in self._routes:
            match = route.match(method, path)
            if match is not None:
                return route.handler, match
        return None, None