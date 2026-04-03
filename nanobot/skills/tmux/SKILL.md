---
name: tmux
description: 通过发送按键、抓取窗格输出，远程控制 tmux 会话以运行交互式命令行程序。
metadata: {"nanobot":{"emoji":"🧵","os":["darwin","linux"],"requires":{"bins":["tmux"]}}}
---

# tmux 技能

仅在需要**交互式 TTY 终端**时使用 tmux。对于长时间运行、非交互式的任务，优先使用 exec 后台模式。

## 快速开始（独立套接字，exec 工具）

```bash
SOCKET_DIR="${NANOBOT_TMUX_SOCKET_DIR:-${TMPDIR:-/tmp}/nanobot-tmux-sockets}"
mkdir -p "$SOCKET_DIR"
SOCKET="$SOCKET_DIR/nanobot.sock"
SESSION=nanobot-python

tmux -S "$SOCKET" new -d -s "$SESSION" -n shell
tmux -S "$SOCKET" send-keys -t "$SESSION":0.0 -- 'PYTHON_BASIC_REPL=1 python3 -q' Enter
tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

启动会话后，务必输出监控命令：

```
查看会话：
  tmux -S "$SOCKET" attach -t "$SESSION"
  tmux -S "$SOCKET" capture-pane -p -J -t "$SESSION":0.0 -S -200
```

## 套接字规范
- 使用环境变量 `NANOBOT_TMUX_SOCKET_DIR`
- 默认套接字路径：`"$NANOBOT_TMUX_SOCKET_DIR/nanobot.sock"`

## 目标窗格与命名规则
- 目标格式：`会话名:窗口.窗格`（默认值 `:0.0`）
- 名称保持简短，避免空格
- 查看信息：`tmux -S "$SOCKET" list-sessions`、`tmux -S "$SOCKET" list-panes -a`

## 查找会话
- 列出当前套接字的会话：`{baseDir}/scripts/find-sessions.sh -S "$SOCKET"`
- 扫描所有套接字：`{baseDir}/scripts/find-sessions.sh --all`（使用 `NANOBOT_TMUX_SOCKET_DIR`）

## 安全发送输入
- 优先使用原文发送：`tmux -S "$SOCKET" send-keys -t 目标 -l -- "$命令"`
- 控制按键：`tmux -S "$SOCKET" send-keys -t 目标 C-c`

## 监听输出
- 捕获最近历史记录：`tmux -S "$SOCKET" capture-pane -p -J -t 目标 -S -200`
- 等待提示符：`{baseDir}/scripts/wait-for-text.sh -t 会话:0.0 -p '匹配规则'`
- 可以连接会话；使用 `Ctrl+b d` 断开连接

## 启动进程
- 运行 Python REPL 时，设置 `PYTHON_BASIC_REPL=1`（标准REPL会破坏按键发送流程）

## Windows / WSL
- tmux 仅支持 macOS/Linux。Windows 系统请使用 WSL，并在 WSL 内安装 tmux
- 本技能仅支持 `darwin`/`linux` 系统，且要求 `tmux` 在环境变量中

## 编排编码智能体（Codex、Claude Code）
tmux 非常适合并行运行多个编码智能体：

```bash
SOCKET="${TMPDIR:-/tmp}/codex-army.sock"

# 创建多个会话
for i in 1 2 3 4 5; do
  tmux -S "$SOCKET" new-session -d -s "agent-$i"
done

# 在不同工作目录启动智能体
tmux -S "$SOCKET" send-keys -t agent-1 "cd /tmp/project1 && codex --yolo '修复bug X'" Enter
tmux -S "$SOCKET" send-keys -t agent-2 "cd /tmp/project2 && codex --yolo '修复bug Y'" Enter

# 轮询任务完成状态（检查是否返回命令提示符）
for sess in agent-1 agent-2; do
  if tmux -S "$SOCKET" capture-pane -p -t "$sess" -S -3 | grep -q "❯"; then
    echo "$sess: 已完成"
  else
    echo "$sess: 运行中..."
  fi
done

# 获取已完成会话的完整输出
tmux -S "$SOCKET" capture-pane -p -t agent-1 -S -500
```

**使用技巧：**
- 并行修复时使用独立的 git 工作树（避免分支冲突）
- 全新克隆的项目中，运行 codex 前先执行 `pnpm install`
- 通过命令提示符（`❯` 或 `$`）判断任务完成
- Codex 非交互式修复需要添加 `--yolo` 或 `--full-auto` 参数

## 清理操作
- 关闭单个会话：`tmux -S "$SOCKET" kill-session -t "$SESSION"`
- 关闭套接字下所有会话：`tmux -S "$SOCKET" list-sessions -F '#{session_name}' | xargs -r -n1 tmux -S "$SOCKET" kill-session -t`
- 关闭私有套接字所有服务：`tmux -S "$SOCKET" kill-server`

## 辅助工具：wait-for-text.sh
`{baseDir}/scripts/wait-for-text.sh` 可轮询窗格内容，匹配正则/固定字符串并支持超时：

```bash
{baseDir}/scripts/wait-for-text.sh -t 会话:0.0 -p '匹配规则' [-F] [-T 20] [-i 0.5] [-l 2000]
```

- `-t`/`--target` 窗格目标（必填）
- `-p`/`--pattern` 匹配正则（必填）；添加 `-F` 表示匹配固定字符串
- `-T` 超时时间（秒，默认15）
- `-i` 轮询间隔（秒，默认0.5）
- `-l` 搜索历史行数（默认1000）