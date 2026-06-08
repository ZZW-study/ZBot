/**
 * Message — single message bubble.
 *  - user: plain text bubble, right-aligned.
 *  - assistant: reasoning block(s), markdown text, tool call list, and an
 *    optional inline error card. Streaming is indicated by a CSS cursor
 *    (the markdown itself is shown as plain text while running).
 */

import type { ChatMessage, Turn } from '../types';
import Markdown from './Markdown';
import ReasoningBlock from './ReasoningBlock';
import ToolCallList from './ToolCallList';

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
  const reasoning = turn.items.filter((it): it is Extract<typeof it, { kind: 'reasoning' }> => it.kind === 'reasoning');
  const messageItem = turn.items.find((it) => it.kind === 'message');
  const errors = turn.items.filter((it): it is Extract<typeof it, { kind: 'error' }> => it.kind === 'error');
  const isRunning = turn.status === 'running';

  return (
    <article className={`message assistant ${isRunning ? 'streaming' : turn.status}`} data-turn-status={turn.status}>
      <header className="message-meta">
        <span>ZBot</span>
        {isRunning && <span className="message-meta-hint">streaming…</span>}
      </header>

      {reasoning.map((it, i) => (
        <ReasoningBlock key={`r-${i}-${it.summary.slice(0, 8)}`} summary={it.summary} />
      ))}

      {messageItem && messageItem.kind === 'message' && messageItem.content && (
        <Markdown source={messageItem.content} streaming={isRunning} />
      )}

      <ToolCallList items={turn.items} />

      {errors.map((it, i) => (
        <div key={`e-${i}`} className="message-error" role="alert">
          <strong>Error{it.code ? ` (${it.code})` : ''}:</strong> {it.message}
        </div>
      ))}
    </article>
  );
}