"""根据最近的 error.log 生成一段简短的文本报告。"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    log_path = Path("logs/error.log")
    if not log_path.exists():
        print("no log file found")
        return 1
    pattern = re.compile(r"host=([\w.\-]+)")
    counter: Counter = Counter()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        for match in pattern.findall(line):
            counter[match] += 1
    print("Error counts by host:")
    for host, count in counter.most_common():
        print(f"  {host}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())