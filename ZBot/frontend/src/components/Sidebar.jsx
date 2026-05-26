/**
 * Sidebar.jsx — 左侧栏组件
 * 显示品牌标识、会话输入框、连接状态、操作按钮
 */

// 导入子组件和工具函数
import StatusRow from './StatusRow';
import { socketStateLabel } from '../utils/format';  // { } 解构导入具名导出

// 函数组件，参数用解构取出所有 props
// 每个 prop 都是从父组件 ChatPage 传来的
export default function Sidebar({
  sessionName,      // 当前会话名（字符串）
  setSessionName,   // 修改会话名的函数
  socketState,      // WebSocket 连接状态（字符串）
  isRunning,        // 是否正在运行（布尔值）
  activeRunId,      // 当前运行 ID（字符串）
  onReconnect,      // 重新连接的回调函数
  onOpenSettings,   // 打开设置的回调函数
}) {
  return (
    // <aside> — HTML 语义标签，表示"侧边内容"
    <aside className="sidebar">

      {/* 品牌区域 */}
      <div className="brand">
        <div className="brand-mark">Z</div>
        <div>
          <h1>ZBot</h1>
          <p>Agent Harness</p>
        </div>
      </div>

      {/* 会话输入框 */}
      {/* htmlFor — 等价于 HTML 的 for 属性（for 是 JS 保留字，所以用 htmlFor） */}
      {/* 点击 label 时会聚焦到对应的 input */}
      <label className="field-label" htmlFor="session-name">会话</label>
      <input
        id="session-name"
        className="session-input"
        value={sessionName}                                    // 受控组件：值由 React 管理
        onChange={(event) => setSessionName(event.target.value)} // 输入变化时更新状态
        // event.target — 触发事件的 DOM 元素（即这个 <input>）
        // event.target.value — 输入框的当前值
        disabled={isRunning}                                   // 运行时禁用输入
      />

      {/* 状态面板 */}
      <section className="status-panel">
        {/* 传递 props 给 StatusRow 子组件 */}
        {/* socketStateLabel(socketState) — 调用工具函数，把状态转为中文 */}
        <StatusRow label="连接" value={socketStateLabel(socketState)} tone={socketState} />

        {/* 三元运算符：isRunning 为 true 显示"执行中"，否则显示"空闲" */}
        <StatusRow label="运行" value={isRunning ? '执行中' : '空闲'} tone={isRunning ? 'running' : 'idle'} />

        {/* activeRunId || '-' — 如果 activeRunId 为空字符串（假值），显示 '-' */}
        <StatusRow label="Run ID" value={activeRunId || '-'} />
      </section>

      {/* 重新连接按钮 */}
      <button
        className="connect-button"
        type="button"
        onClick={onReconnect}  // 点击时调用父组件传来的 onReconnect
        // || 逻辑或：任一条件为 true 就禁用
        disabled={socketState === 'connected' || isRunning}
      >
        重新连接
      </button>

      {/* 设置按钮 */}
      <button
        className="settings-button"
        type="button"
        onClick={onOpenSettings}
        disabled={isRunning}
      >
        设置
      </button>
    </aside>
  );
}
