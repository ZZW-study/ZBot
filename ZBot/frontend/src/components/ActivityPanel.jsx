/**
 * ActivityPanel.jsx — 右侧事件面板
 * 显示运行过程中的所有事件（工具调用、模型请求等）
 */

// 导入子组件
import EventRow from './EventRow';

// 函数组件，只接收一个 props：events（事件数组）
export default function ActivityPanel({ events }) {
  return (
    // <aside> — 侧边内容
    <aside className="activity">

      {/* 头部：标题 + 事件计数 */}
      <div className="activity-header">
        <h2>运行事件</h2>
        {/* events.length — 数组长度（事件数量） */}
        <span>{events.length}</span>
      </div>

      {/* 事件列表 */}
      <div className="event-list">
        {/* 三元运算符：数组为空显示空状态，否则渲染列表 */}
        {events.length === 0 ? (
          <p className="empty">还没有事件。</p>
        ) : (
          // .map() 遍历数组，每个事件渲染一个 EventRow
          // key — 列表项的唯一标识
          //   React 靠 key 判断列表中哪些项是新增/删除/移动的，key 重复会导致渲染错误
          //   用 created_at + index 组合，防止时间戳重复
          //   event.created_at || index — 如果没有时间戳，用数组索引作兜底
          events.map((event, index) => (
            <EventRow event={event} key={`${event.created_at || index}-${index}`} />
          ))
        )}
      </div>
    </aside>
  );
}
