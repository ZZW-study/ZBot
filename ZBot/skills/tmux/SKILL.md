---
name: tmux
description: "通过发送按键和抓取 pane 输出来远程控制 tmux 会话，适合交互式 CLI。"
metadata: {"nanobot":{"emoji":"🧵","os":["darwin","linux"],"requires":{"bins":["tmux"]}}}
---

# tmux 技能

只有需要交互式 TTY 时才使用 tmux。对于长时间运行但非交互式的任务，优先使用 `exec` 后台模式。

## 快速开始（隔离 socket，配合 exec 工具）

```bash
SOCKET_DIR="${NANOBOT_TMUX_SOCKET_DIR:-${TMPDIR:-/tmp}/nanobot-tmux-sockets}"
mkdir -p "$SOCKET_DIR"
SOCKET="$SOCKET_DIR/nanobot.sock"
SESSION=nanobot-python

tmux -S "$SOCKET" new -d -s "$SESSION" -n shell
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -- 'PYTHON_BASIC_REPL=1 python3 -q' Enter
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

启动会话后，始终打印监控命令：

```
To monitor:
  tmux -S "$SOCKET" attach -t "$SESSION"
  tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

## Socket 约定

- 使用 `NANOBOT_TMUX_SOCKET_DIR` 环境变量。
- 默认 socket 路径：`"$NANOBOT_TMUX_SOCKET_DIR/nanobot.sock"`。

## 定位 pane 和命名

- 目标格式：`session:window.pane`（默认是 `:0.0`）。
- 名称保持简短，避免空格。
- 查看状态：`tmux -S "$SOCKET" list-sessions`、`tmux -S "$SOCKET" list-panes -a`。

## 查找会话

- 列出当前 socket 上的会话：`{baseDir}/scripts/find-sessions.sh -S "$SOCKET"`。
- 扫描所有 socket：`{baseDir}/scripts/find-sessions.sh --all`（使用 `NANOBOT_TMUX_SOCKET_DIR`）。

## 安全发送输入

- 优先使用字面量发送：`tmux -S "$SOCKET" send-keys -t target -l -- "$cmd"`。
- 控制键：`tmux -S "$SOCKET" send-keys -t target C-c`。

## 观察输出

- 抓取最近历史：`tmux -S "$SOCKET" capture-pane -p -J -t target -S -200`。
- 等待提示符或文本：`{baseDir}/scripts/wait-for-text.sh -t session:0.0 -p 'pattern'`。
- 可以 attach；用 `Ctrl+b d` detach。

## 启动进程

- 对 Python REPL，设置 `PYTHON_BASIC_REPL=1`（非 basic REPL 会破坏 send-keys 流程）。

## Windows / WSL

- tmux 支持 macOS/Linux。在 Windows 上使用 WSL，并在 WSL 内安装 tmux。
- 这个技能只对 `darwin`/`linux` 开启，并要求 PATH 中存在 `tmux`。

## 编排编码 Agent（Codex、Claude Code）

tmux 很适合并行运行多个编码 Agent：

```bash
SOCKET="${TMPDIR:-/tmp}/codex-army.sock"

# 创建多个会话
for i in 1 2 3 4 5; do
  tmux -S "$SOCKET" new-session -d -s "agent-$i"
done

# 在不同工作目录启动 Agent
tmux -S "$SOCKET" send-keys -t agent-1 "cd /tmp/project1 && codex --yolo 'Fix bug X'" Enter
tmux -S "$SOCKET" send-keys -t agent-2 "cd /tmp/project2 && codex --yolo 'Fix bug Y'" Enter

# 轮询是否完成（检查 shell prompt 是否返回）
for sess in agent-1 agent-2; do
  if tmux -S "$SOCKET" capture-pane -p -t "$sess" -S -3 | grep -q "❯"; then
    echo "$sess: DONE"
  else
    echo "$sess: Running..."
  fi
done

# 获取已完成会话的完整输出
tmux -S "$SOCKET" capture-pane -p -t agent-1 -S -500
```

**提示：**
- 并行修复时使用独立 git worktree，避免分支冲突。
- 在新 clone 里运行 codex 前，先执行 `pnpm install`。
- 通过 shell prompt（`❯` 或 `$`）判断是否完成。
- 非交互式修复时，Codex 需要 `--yolo` 或 `--full-auto`。

## 清理

- 杀掉一个会话：`tmux -S "$SOCKET" kill-session -t "$SESSION"`。
- 杀掉某个 socket 上的所有会话：`tmux -S "$SOCKET" list-sessions -F '#{session_name}' | xargs -r -n1 tmux -S "$SOCKET" kill-session -t`。
- 移除私有 socket 上的全部内容：`tmux -S "$SOCKET" kill-server`。

## 辅助脚本：wait-for-text.sh

`{baseDir}/scripts/wait-for-text.sh` 会在超时前轮询某个 pane，查找正则表达式或固定字符串。

```bash
{baseDir}/scripts/wait-for-text.sh -t session:0.0 -p 'pattern' [-F] [-T 20] [-i 0.5] [-l 2000]
```

- `-t`/`--target`：pane 目标（必填）。
- `-p`/`--pattern`：要匹配的正则（必填）；加 `-F` 表示固定字符串。
- `-T`：超时秒数（整数，默认 15）。
- `-i`：轮询间隔秒数（默认 0.5）。
- `-l`：搜索的历史行数（整数，默认 1000）。
