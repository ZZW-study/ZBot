---
name: memory
description: 基于 grep 检索的双层记忆系统
---

# 记忆系统

## 结构

- `memory/MEMORY.md` — 长期事实记忆（用户偏好、项目上下文、关联关系）。会始终加载到上下文里。
- `memory/HISTORY.md` — 只追加不修改的事件日志。**不会**加载到上下文。可通过 grep 类工具或内存过滤器进行检索。每条记录以 `[YYYY-MM-DD HH:MM]` 开头。

## 检索历史事件

根据文件大小选择检索方式：

- 小型 `memory/HISTORY.md`：使用 `read_file` 读取后在内存中检索
- 大型或长期使用的 `memory/HISTORY.md`：使用 `exec` 工具进行精准检索

示例：
- **Linux/macOS:** `grep -i "keyword" memory/HISTORY.md`
- **Windows:** `findstr /i "keyword" memory\HISTORY.md`
- **跨平台 Python:** `python -c "from pathlib import Path; text = Path('memory/HISTORY.md').read_text(encoding='utf-8'); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"`

对于大型历史文件，优先使用命令行精准检索。

## 何时更新 MEMORY.md

遇到重要信息请立即通过 `edit_file` 或 `write_file` 写入：
- 用户偏好（如“我更喜欢深色模式”）
- 项目上下文（如“该接口使用 OAuth2 鉴权”）
- 人物/关系信息（如“Alice 是项目负责人”）

## 自动整合
当会话内容过多时，旧对话会被自动总结并追加到 `HISTORY.md`。关键长期信息会被提取到 `MEMORY.md`。你无需手动管理该过程。