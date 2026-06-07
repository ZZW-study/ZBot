#!/usr/bin/env bash
# 构建脚本：跑单测并打包 wheel
set -euo pipefail
echo "[build] starting at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[build] target platform: linux/amd64"
echo "[build] running unit tests"
python -m pytest tests/ -q
echo "[build] packaging wheel"
python -m build --wheel
echo "[build] done at $(date -u +%Y-%m-%dT%H:%M:%SZ)"