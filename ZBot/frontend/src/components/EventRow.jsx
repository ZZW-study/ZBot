/**
 * EventRow.jsx — 单个事件行
 * 显示一个事件的标题、时间、消息内容
 */

// 从工具函数模块导入三个函数
import { eventMessage, eventTitle, formatTime } from '../utils/format';

// 函数组件，接收一个 props：event（事件对象）
export default function EventRow({ event }) {
  return (
    // <article> — 独立内容块
    //
    // className 动态拼接：
    //   event.type?.replace('.', '-') — 把 "tool.started" 变成 "tool-started"
    //   ?. 可选链：如果 event.type 是 null/undefined，不报错
    //   .replace('.', '-') — 字符串方法，把 '.' 替换为 '-'
    //   || '' — 如果结果是 undefined，用空字符串
    //   最终结果如 "event-row tool-started"
    <article className={`event-row ${event.type?.replace('.', '-') || ''}`}>
      <div>
        {/* 事件标题（中文） */}
        <strong>{eventTitle(event)}</strong>
        {/* 格式化时间 */}
        <time>{formatTime(event.created_at)}</time>
      </div>
      {/* 事件消息内容 */}
      <p>{eventMessage(event)}</p>
    </article>
  );
}
