import { useEffect, useMemo, useRef } from 'react';
import type { ChatMessage, Turn } from '../types';
import EmptyState from './EmptyState';
import LiveStatus from './LiveStatus';
import Message from './Message';

interface MessageListProps {
  messages: ChatMessage[];
  turns: Turn[];
  isRunning: boolean;
  loading?: boolean;
  livePhase?: 'idle' | 'thinking' | 'tool' | 'finalizing' | 'streaming';
  liveToolName?: string;
  onPickExample?: (_prompt: string) => void;
  composerRef?: React.RefObject<HTMLTextAreaElement | null>;
}

const EXAMPLE_PROMPTS = [
  '用 Python 写一个扫雷游戏的最小可运行版本',
  '阅读 README.md 总结三条要点',
  '用 web_search 调研 2025 年大模型 Agent 框架趋势',
  '把这段代码改造成 TypeScript 并补上类型注解',
];

export default function MessageList({
  messages,
  turns,
  isRunning,
  loading = false,
  livePhase = 'idle',
  liveToolName = '',
  onPickExample,
  composerRef,
}: MessageListProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  // 仅在用户位于底部时自动滚动, 避免抢用户阅读。
  const nearBottomRef = useRef(true);

  useEffect(() => {
    const list = listRef.current;
    if (!list || loading) return;
    if (nearBottomRef.current) {
      list.scrollTop = list.scrollHeight;
    }
  }, [loading, messages.length, turns.length, turns.map((t) => t.items.length).join(',')]);

  const handleScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget;
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
  };

  // 单一状态卡片: 只在启动期 (thinking / tool / finalizing) 且 turn 还没内容时显示。
  // 助手开始吐字 (phase=streaming) 或 turn 已经有内容, 状态卡片立即让位。
  // ZBot: refined LiveStatus gating. Show when:
  //   - isRunning + (no turn yet) + phase in (thinking/tool/finalizing) -> show thinking
  //   - isRunning + (turn has only running tool_call as last item) -> show "calling X"
  // Hide when:
  //   - last item is text (assistant already speaking)
  //   - last item is done/failed tool_call (no current tool)
  //   - turn.status is completed/failed/cancelled (run done)
  // ZBot: 过程 vs 结果 严格分离.
  //   - 状态卡片显示 = isRunning (run 进行期间, 始终显示)
  //   - 状态卡片隐藏 = !isRunning (run 结束, 无论成功失败)
  //   - LiveStatus 内部对每个 phase 都有文案 (含 streaming: '正在分析结果...')
  const showLiveStatus = isRunning;

  const showEmptyState = !loading && messages.length === 0 && turns.length === 0;

  const exampleNodes = useMemo(
    () =>
      EXAMPLE_PROMPTS.map((label) => ({
        label,
        onPick: (picked: string) => {
          onPickExample?.(picked);
          composerRef?.current?.focus();
        },
      })),
    [onPickExample, composerRef],
  );

  return (
    <div className="message-list" ref={listRef} onScroll={handleScroll}>
      {loading && (
        <div className="message-state">正在加载会话历史...</div>
      )}

      {showEmptyState && (
        <EmptyState
          icon={<div className="empty-state-mark">Z</div>}
          title="开启新对话"
          description="ZBot 可以调用工具、读写文件、查网页、写代码。下面是一些示例 prompt, 点击直接填到输入框。"
          examples={exampleNodes}
        />
      )}

      {/* ZBot 改: 只渲染 turns, 因为 ChatPage 已经在收到后端 ChatMessage[] 时
          把它们转换成 turns (每个 [user, assistant] 对配成 1 个 turn)。
          之前同时渲染 messages 和 turns 会导致用户消息 + 助手回答被渲染两次。 */}
      {!loading && turns.map((turn) => (
        <Message key={turn.turnId} turn={turn} />
      ))}

      {showLiveStatus && (
        <LiveStatus phase={livePhase} toolName={liveToolName} />
      )}
    </div>
  );
}