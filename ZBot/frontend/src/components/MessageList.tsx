import { useEffect, useRef } from 'react';
import { eventMessage } from '../utils/format';
import type { AgentEvent, ChatMessage } from '../types';

interface MessageListProps {
  messages: ChatMessage[];
  isRunning: boolean;
  latestEvent: AgentEvent | null;
  streamingContent: string;
  loading?: boolean;
}

export default function MessageList({
  messages,
  isRunning,
  latestEvent,
  streamingContent,
  loading = false,
}: MessageListProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const streamingText = streamingContent || (latestEvent ? eventMessage(latestEvent) : '正在处理任务...');

  useEffect(() => {
    const list = listRef.current;
    if (!list || loading) return;
    list.scrollTop = list.scrollHeight;
  }, [loading, messages.length, streamingContent]);

  return (
    <div className="message-list" ref={listRef}>
      {loading && (
        <div className="message-state">正在加载会话历史...</div>
      )}

      {!loading && messages.length === 0 && !isRunning && (
        <div className="message-state">这个会话还没有消息。</div>
      )}

      {!loading && messages.map((message) => (
        <article className={`message ${message.role}`} key={message.id}>
          <span>{message.role === 'user' ? '你' : 'ZBot'}</span>
          <p>{message.content}</p>
        </article>
      ))}

      {!loading && isRunning && (
        <article className="message assistant streaming">
          <span>ZBot</span>
          <p>{streamingText}</p>
        </article>
      )}
    </div>
  );
}
