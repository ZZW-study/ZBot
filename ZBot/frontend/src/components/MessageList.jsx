import { eventMessage } from '../utils/format';

export default function MessageList({ messages, isRunning, latestEvent, streamingContent }) {
  const streamingText = streamingContent || (latestEvent ? eventMessage(latestEvent) : '正在处理任务...');

  return (
    <div className="message-list">
      {messages.map((message) => (
        <article className={`message ${message.role}`} key={message.id}>
          <span>{message.role === 'user' ? '你' : 'ZBot'}</span>
          <p>{message.content}</p>
        </article>
      ))}
      {isRunning && (
        <article className="message assistant streaming">
          <span>ZBot</span>
          <p>{streamingText}</p>
        </article>
      )}
    </div>
  );
}
