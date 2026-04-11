#!/usr/bin/env bash
# 脚本解释器：指定使用bash执行本脚本

# 开启严格模式：脚本运行更安全，遇到错误立即退出
# -e：命令执行失败直接退出
# -u：使用未定义变量直接报错退出
# -o pipefail：管道中任意命令失败，整个管道返回失败
set -euo pipefail

# ==================== 函数定义 ====================
#  usage：打印脚本使用帮助信息
#  无参数，直接输出用法说明到控制台
usage() {
  cat <<'USAGE'
Usage: find-sessions.sh [-L socket-name|-S socket-path|-A] [-q pattern]

List tmux sessions on a socket (default tmux socket if none provided).

Options:
  -L, --socket       tmux socket name (passed to tmux -L)
  -S, --socket-path  tmux socket path (passed to tmux -S)
  -A, --all          scan all sockets under NANOBOT_TMUX_SOCKET_DIR
  -q, --query        case-insensitive substring to filter session names
  -h, --help         show this help
USAGE
}

# ==================== 变量初始化 ====================
# tmux套接字名称（-L参数使用）
socket_name=""
# tmux套接字绝对路径（-S参数使用）
socket_path=""
# 会话名称过滤关键词（-q参数使用）
query=""
# 是否扫描所有套接字（-A参数使用）
scan_all=false
# tmux套接字存放目录：优先使用环境变量，无则使用系统临时目录
socket_dir="${NANOBOT_TMUX_SOCKET_DIR:-${TMPDIR:-/tmp}/ZBot-tmux-sockets}"

# ==================== 命令行参数解析 ====================
# 循环处理所有传入的参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    # -L/--socket：指定tmux套接字名称
    -L|--socket)      socket_name="${2-}"; shift 2 ;;
    # -S/--socket-path：指定tmux套接字绝对路径
    -S|--socket-path) socket_path="${2-}"; shift 2 ;;
    # -A/--all：扫描所有套接字
    -A|--all)         scan_all=true; shift ;;
    # -q/--query：设置会话名称过滤关键词
    -q|--query)       query="${2-}"; shift 2 ;;
    # -h/--help：打印帮助并退出
    -h|--help)        usage; exit 0 ;;
    # 未知参数：报错并打印帮助
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

# ==================== 参数合法性校验 ====================
# 禁止同时使用--all和-L/-S
if [[ "$scan_all" == true && ( -n "$socket_name" || -n "$socket_path" ) ]]; then
  echo "Cannot combine --all with -L or -S" >&2
  exit 1
fi

# 禁止同时使用-L和-S（二选一）
if [[ -n "$socket_name" && -n "$socket_path" ]]; then
  echo "Use either -L or -S, not both" >&2
  exit 1
fi

# 检查系统是否安装了tmux命令
if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux not found in PATH" >&2
  exit 1
fi

# ==================== 核心函数：列出tmux会话 ====================
#  list_sessions：查询并格式化输出tmux会话信息
#  参数1：套接字标签（用于打印提示信息）
#  剩余参数：tmux命令的附加参数（-L/-S）
list_sessions() {
  # 读取套接字标签
  local label="$1"; shift
  # 构建tmux基础命令
  local tmux_cmd=(tmux "$@")

  # 执行tmux list-sessions：查询所有会话，格式化输出（名称/连接状态/创建时间）
  # 2>/dev/null：屏蔽错误输出
  if ! sessions="$("${tmux_cmd[@]}" list-sessions -F '#{session_name}\t#{session_attached}\t#{session_created_string}' 2>/dev/null)"; then
    echo "No tmux server found on $label" >&2
    return 1
  fi

  # 如果设置了过滤关键词，忽略大小写匹配会话名称
  if [[ -n "$query" ]]; then
    sessions="$(printf '%s\n' "$sessions" | grep -i -- "$query" || true)"
  fi

  # 无匹配会话时提示
  if [[ -z "$sessions" ]]; then
    echo "No sessions found on $label"
    return 0
  fi

  # 格式化打印会话信息
  echo "Sessions on $label:"
  # 按制表符分割每行数据，遍历输出
  printf '%s\n' "$sessions" | while IFS=$'\t' read -r name attached created; do
    # 判断会话是否被连接：1=已连接，0=未连接
    attached_label=$([[ "$attached" == "1" ]] && echo "attached" || echo "detached")
    # 格式化输出：会话名称、连接状态、创建时间
    printf '  - %s (%s, started %s)\n' "$name" "$attached_label" "$created"
  done
}

# ==================== 执行逻辑：扫描所有套接字 ====================
if [[ "$scan_all" == true ]]; then
  # 检查套接字目录是否存在
  if [[ ! -d "$socket_dir" ]]; then
    echo "Socket directory not found: $socket_dir" >&2
    exit 1
  fi

  # 开启nullglob：通配符无匹配时返回空，而非原字符串
  shopt -s nullglob
  # 获取目录下所有文件
  sockets=("$socket_dir"/*)
  # 关闭nullglob
  shopt -u nullglob

  # 无套接字文件时报错
  if [[ "${#sockets[@]}" -eq 0 ]]; then
    echo "No sockets found under $socket_dir" >&2
    exit 1
  fi

  # 遍历所有套接字文件，逐个查询会话
  exit_code=0
  for sock in "${sockets[@]}"; do
    # 只处理套接字文件（-S：判断是否为套接字）
    if [[ ! -S "$sock" ]]; then
      continue
    fi
    # 调用核心函数查询会话，失败则记录退出码
    list_sessions "socket path '$sock'" -S "$sock" || exit_code=$?
  done
  # 按最终状态码退出
  exit "$exit_code"
fi

# ==================== 执行逻辑：单个套接字查询 ====================
# 初始化tmux命令数组
tmux_cmd=(tmux)
# 默认标签：默认套接字
socket_label="default socket"

# 根据参数设置tmux命令和标签
if [[ -n "$socket_name" ]]; then
  # 使用套接字名称
  tmux_cmd+=(-L "$socket_name")
  socket_label="socket name '$socket_name'"
elif [[ -n "$socket_path" ]]; then
  # 使用套接字路径
  tmux_cmd+=(-S "$socket_path")
  socket_label="socket path '$socket_path'"
fi

# 调用核心函数，列出会话
list_sessions "$socket_label" "${tmux_cmd[@]:1}"