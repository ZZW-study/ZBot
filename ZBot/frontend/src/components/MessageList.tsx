import { useEffect, useRef } from 'react';
import type { ChatMessage } from '../types';
import Markdown from './Markdown';
import Message from './Message';

interface MessageListProps {
  messages: ChatMessage[];
  isRunning: boolean;
  streamingContent: string;
  loading?: boolean;
}

export default function MessageList({
  messages,
  isRunning,
  streamingContent,
  loading = false,
}: MessageListProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  // MEDIUM 修复:auto-scroll 抢用户意图。tracking 用户是否在底部,
  // 只在 near-bottom 时才跟随 scroll,避免用户往上读时被打断。
  const nearBottomRef = useRef(true);
  const streamingText = streamingContent || (isRunning ? '正在处理任务...' : '');

  useEffect(() => {
    const list = listRef.current;
    if (!list || loading) return;
    if (nearBottomRef.current) {
      list.scrollTop = list.scrollHeight;
    }
  }, [loading, messages.length, streamingContent]);

  const handleScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget;
    // 距离底部 32px 内算"near bottom",给 auto-scroll 一点缓冲。
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
  };

  return (
    <div className="message-list" ref={listRef} onScroll={handleScroll}>
      {loading && (
        <div className="message-state">正在加载会话历史...</div>
      )}

      {!loading && messages.length === 0 && !isRunning && (
        <div className="message-state">这个会话还没有消息。</div>
      )}

      {!loading && messages.map((message) => (
        // H28 修复:历史 assistant 走 <Markdown /> 渲染,而非 <p>。
        // 同时 H30 修复:复用已存在的 <Message> 组件,不再内联 JSX。
        <Message key={message.id} message={message} />
      ))}

      {!loading && isRunning && streamingContent && (
        <article className="message assistant streaming" key="__streaming__">
          <span>ZBot</span>
          <Markdown source={streamingText} streaming />
        </article>
      )}
    </div>
  );
}
