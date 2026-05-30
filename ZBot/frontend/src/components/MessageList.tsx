/**
 * MessageList.jsx — 消息列表组件
 * 渲染所有聊天消息，以及 AI 正在回复时的流式消息气泡
 */

// 导入工具函数：把事件对象转为可读的消息文本
import { eventMessage } from '../utils/format';
import type { AgentEvent, ChatMessage } from '../types';

interface MessageListProps {
  messages: ChatMessage[];
  isRunning: boolean;
  latestEvent: AgentEvent | null;
  streamingContent: string;
}

// 函数组件，接收 4 个 props
export default function MessageList({ messages, isRunning, latestEvent, streamingContent }: MessageListProps) {
  // 流式消息的显示文本
  // 优先级：streamingContent > 事件消息 > 默认文本
  // || 逻辑或：左边是假值时用右边
  // latestEvent ? eventMessage(latestEvent) : '...' — 嵌套在 || 里的三元运算符
  //   先判断 latestEvent 是否存在，存在就调用 eventMessage()，否则用默认文本
  const streamingText = streamingContent || (latestEvent ? eventMessage(latestEvent) : '正在处理任务...');

  return (
    // 消息列表容器
    <div className="message-list">

      {/* .map() — 遍历数组，把每个元素转为 JSX */}
      {/* 返回一个新数组，React 渲染数组中的每个元素 */}
      {messages.map((message) => (
        // <article> — HTML 语义标签，表示"独立的内容块"
        // className 用模板字符串拼接：始终有 "message" 类，再加上 role（"user" 或 "assistant"）
        //   例如 "message user" 或 "message assistant"
        // key — 列表项的唯一标识，React 用它判断哪些项变了，高效更新 DOM
        <article className={`message ${message.role}`} key={message.id}>
          {/* 三元运算符：user 显示"你"，assistant 显示"ZBot" */}
          <span>{message.role === 'user' ? '你' : 'ZBot'}</span>
          <p>{message.content}</p>
        </article>
      ))}

      {/* 短路求值：isRunning 为 true 时才渲染流式消息气泡 */}
      {isRunning && (
        <article className="message assistant streaming">
          <span>ZBot</span>
          <p>{streamingText}</p>
        </article>
      )}
    </div>
  );
}
