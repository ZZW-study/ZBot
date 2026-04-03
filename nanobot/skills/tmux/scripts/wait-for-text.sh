#!/usr/bin/env bash
# 脚本解释器：指定使用 Bash  shell 执行当前脚本

# 启用 Bash 严格模式，提升脚本安全性和健壮性
# -e：任何命令执行失败（返回非0值），立即终止整个脚本
# -u：使用未定义的变量时，直接报错并退出
# -o pipefail：管道中任意一个命令失败，整个管道的返回值即为失败
set -euo pipefail

# ==================== 函数定义 ====================
# 函数名：usage
# 作用：打印脚本的使用帮助文档，当用户输入错误参数或使用 -h 时调用
usage() {
  # 输出内置的帮助文本（ heredoc 语法）
  cat <<'USAGE'
Usage: wait-for-text.sh -t target -p pattern [options]

Poll a tmux pane for text and exit when found.

Options:
  -t, --target    tmux target (session:window.pane), required
  -p, --pattern   regex pattern to look for, required
  -F, --fixed     treat pattern as a fixed string (grep -F)
  -T, --timeout   seconds to wait (integer, default: 15)
  -i, --interval  poll interval in seconds (default: 0.5)
  -l, --lines     number of history lines to inspect (integer, default: 1000)
  -h, --help      show this help
USAGE
}

# ==================== 变量初始化（默认值） ====================
target=""            # tmux 目标（格式：会话:窗口.窗格），必填参数
pattern=""           # 要匹配的文本/正则表达式，必填参数
grep_flag="-E"       # grep 匹配模式：默认 -E（正则），使用 -F 则切换为固定字符串
timeout=15           # 超时时间，默认 15 秒（必须是整数）
interval=0.5         # 轮询间隔，默认 0.5 秒
lines=1000           # 捕获 tmux 窗格的历史行数，默认 1000 行

# ==================== 命令行参数解析 ====================
# 循环处理所有传入的脚本参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    # -t / --target：指定 tmux 目标窗格
    -t|--target)   target="${2-}"; shift 2 ;;
    # -p / --pattern：指定要匹配的规则
    -p|--pattern)  pattern="${2-}"; shift 2 ;;
    # -F / --fixed：将匹配规则视为固定字符串，而非正则
    -F|--fixed)    grep_flag="-F"; shift ;;
    # -T / --timeout：设置超时时间（秒）
    -T|--timeout)  timeout="${2-}"; shift 2 ;;
    # -i / --interval：设置轮询间隔（秒）
    -i|--interval) interval="${2-}"; shift 2 ;;
    # -l / --lines：设置捕获的历史行数
    -l|--lines)    lines="${2-}"; shift 2 ;;
    # -h / --help：打印帮助并退出
    -h|--help)     usage; exit 0 ;;
    # 未知参数：报错并打印帮助
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

# ==================== 参数合法性校验 ====================
# 校验：target 和 pattern 是必填参数，不能为空
if [[ -z "$target" || -z "$pattern" ]]; then
  echo "target and pattern are required" >&2
  usage
  exit 1
fi

# 校验：超时时间必须是正整数
if ! [[ "$timeout" =~ ^[0-9]+$ ]]; then
  echo "timeout must be an integer number of seconds" >&2
  exit 1
fi

# 校验：历史行数必须是正整数
if ! [[ "$lines" =~ ^[0-9]+$ ]]; then
  echo "lines must be an integer" >&2
  exit 1
fi

# 校验：系统必须安装 tmux 命令
if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux not found in PATH" >&2
  exit 1
fi

# ==================== 超时时间计算 ====================
# 获取当前时间戳（秒级，Unix 时间戳）
start_epoch=$(date +%s)
# 计算超时截止时间戳 = 开始时间 + 超时秒数
deadline=$((start_epoch + timeout))

# ==================== 核心轮询循环 ====================
while true; do
  # 捕获 tmux 窗格文本
  # -p：直接打印到标准输出
  # -J：将自动换行的行拼接为完整行
  # -t：指定目标窗格
  # -S "-${lines}"：读取最后 N 行历史
  # 2>/dev/null：屏蔽错误输出；|| true：捕获失败不中断脚本
  pane_text="$(tmux capture-pane -p -J -t "$target" -S "-${lines}" 2>/dev/null || true)"

  # 匹配文本：将窗格内容通过 grep 匹配规则
  # 匹配成功则脚本正常退出（返回码 0）
  if printf '%s\n' "$pane_text" | grep $grep_flag -- "$pattern" >/dev/null 2>&1; then
    exit 0
  fi

  # 判断是否超时：获取当前时间戳，与截止时间对比
  now=$(date +%s)
  if (( now >= deadline )); then
    # 超时后输出错误信息
    echo "Timed out after ${timeout}s waiting for pattern: $pattern" >&2
    echo "Last ${lines} lines from $target:" >&2
    # 输出最后捕获的窗格内容，方便排查问题
    printf '%s\n' "$pane_text" >&2
    exit 1
  fi

  # 等待指定间隔时间，继续下一次轮询
  sleep "$interval"
done