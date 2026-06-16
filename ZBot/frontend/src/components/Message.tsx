/**
 * Message - single message bubble.
 *  - user: plain text bubble, right-aligned.
 *  - assistant: status / final answer + tool call summary (collapsed).
 *
 * ZBot 改: 过程 vs 结果 严格分离.
 *   - turn.status === 'running' -> 不渲染 (LiveStatus 卡片负责)
 *   - turn.status === 'completed' / 'failed' / 'cancelled' ->
 *       FinalAnswerBubble (白气泡, 分块流式) + ToolCallSummary (折叠摘要)
 */

import type { ChatMessage, Turn, ToolCallTurnItem } from '../types';
import FinalAnswerBubble from './FinalAnswerBubble';
import Markdown from './Markdown';
import ToolCallSummary from './ToolCallSummary';

interface AssistantMessageProps {
  turn: Turn;
}

export default function Message({ message, turn }: { message?: ChatMessage; turn?: Turn }) {
  if (message) {
    return (
      <article className={`message ${message.role}`} data-role={message.role}>
        <header className="message-meta">
          <span>{message.role === 'user' ? '你' : 'ZBot'}</span>
        </header>
        {message.role === 'assistant' ? (
          <Markdown source={message.content} />
        ) : (
          <div className="markdown"><p>{message.content}</p></div>
        )}
      </article>
    );
  }
  if (turn) {
    return <AssistantTurn turn={turn} />;
  }
  return null;
}

function AssistantTurn({ turn }: AssistantMessageProps) {
  // ZBot: 过程 vs 结果 严格分离.
  //   - 运行中: 不渲染任何内容 (LiveStatus 卡片负责显示状态)
  //   - 已完成: 渲染 user_message (用户问题) + final answer 白气泡 + 工具调用折叠摘要
  // ZBot 改: turn 里现在有 user_message 项 (kind: 'user_message'), 渲染在最前面,
  // 这样用户在 MessageList 里看到的"用户问题 + 助手回答"是连贯的, 切会话也不丢。
  const userItem = turn.items.find((it) => it.kind === 'user_message');
  const messageItem = turn.items.find((it) => it.kind === 'message');
  const toolCalls = turn.items.filter((it): it is ToolCallTurnItem => it.kind === 'tool_call');
  const errors = turn.items.filter((it): it is Extract<typeof it, { kind: 'error' }> => it.kind === 'error');
  const finalContent = messageItem && messageItem.kind === 'message' ? messageItem.content : '';

  // 如果整个 turn 是 running 且还没有 user_message (历史加载等场景), 不渲染
  if (turn.status === 'running' && !userItem && turn.items.length === 0) {
    return null;
  }

  return (
    <>
      {userItem && userItem.kind === 'user_message' && (
        <article className="message user">
          <header className="message-meta">
            <span>你</span>
          </header>
          <div className="markdown"><p>{userItem.content}</p></div>
        </article>
      )}
      {turn.status === 'completed' || turn.status === 'failed' || turn.status === 'cancelled' || (turn.status === 'running' && (finalContent || toolCalls.length > 0 || errors.length > 0)) ? (
        <article className={`message assistant ${turn.status}`} data-turn-status={turn.status}>
          {finalContent && <FinalAnswerBubble finalContent={finalContent} />}

          {toolCalls.length > 0 && <ToolCallSummary toolCalls={toolCalls} />}

          {errors.map((it, i) => (
            <div key={`e-${i}`} className="message-error" role="alert">
              <strong>Error{it.code ? ` (${it.code})` : ''}:</strong> {it.message}
            </div>
          ))}
        </article>
      ) : null}
    </>
  );
}
