import StatusRow from './StatusRow';
import { socketStateLabel } from '../utils/format';

export default function Sidebar({
  sessionName,
  setSessionName,
  socketState,
  isRunning,
  activeRunId,
  onReconnect,
  onOpenSettings,
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">Z</div>
        <div>
          <h1>ZBot</h1>
          <p>Agent Harness</p>
        </div>
      </div>

      <label className="field-label" htmlFor="session-name">会话</label>
      <input
        id="session-name"
        className="session-input"
        value={sessionName}
        onChange={(event) => setSessionName(event.target.value)}
        disabled={isRunning}
      />

      <section className="status-panel">
        <StatusRow label="连接" value={socketStateLabel(socketState)} tone={socketState} />
        <StatusRow label="运行" value={isRunning ? '执行中' : '空闲'} tone={isRunning ? 'running' : 'idle'} />
        <StatusRow label="Run ID" value={activeRunId || '-'} />
      </section>

      <button
        className="connect-button"
        type="button"
        onClick={onReconnect}
        disabled={socketState === 'connected' || isRunning}
      >
        重新连接
      </button>

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
