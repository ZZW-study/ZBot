"""简单的文件日志器，使用便于轮转的 append 模式。"""

from __future__ import annotations

import time
from pathlib import Path


_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}


class FileLogger:
    def __init__(self, path: str | Path, level: str = "INFO") -> None:
        self._path = Path(path)
        self._level = _LEVELS.get(level.upper(), 20)

    def _emit(self, level: str, message: str) -> None:
        if _LEVELS[level] < self._level:
            return
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        line = f"{ts} [{level}] {message}\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(line)

    def debug(self, msg: str) -> None:
        self._emit("DEBUG", msg)

    def info(self, msg: str) -> None:
        self._emit("INFO", msg)

    def warn(self, msg: str) -> None:
        self._emit("WARN", msg)

    def error(self, msg: str) -> None:
        self._emit("ERROR", msg)