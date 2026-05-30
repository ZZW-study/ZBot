import StatusRow from './StatusRow';
import SessionList from './SessionList';
import { socketStateLabel } from '../utils/format';
import type { SessionSummary, SocketState } from '../types';

interface SidebarProps {
  sessionName: string;
  socketState: SocketState;
  isRunning: boolean;
  activeRunId: string;
  onReconnect: () => void;
  onOpenSettings: () => void;
  sessions: SessionSummary[];
  sessionsLoading: boolean;
  onSelectSession: (_name: string) => void;
  onDeleteSession: (_name: string) => void | Promise<void>;
  onNewSession: () => void;
  onRenameSession: (_oldName: string, _newName: string) => Promise<boolean>;
}

export default function Sidebar({
  // 原有的 props
  sessionName, socketState, isRunning,
  activeRunId, onReconnect, onOpenSettings,
  // 新增的 props（会话列表相关）
  sessions, sessionsLoading, onSelectSession, onDeleteSession, onNewSession, onRenameSession,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">Z</div>
        <div>
          <h1>ZBot</h1>
          <p>Agent Harness</p>
        </div>
      </div>

      {/* 会话列表 — 替换了原来的输入框 */}
      <SessionList
        sessions={sessions}
        currentSession={sessionName}
        onSelect={onSelectSession}
        onDelete={onDeleteSession}
        onNew={onNewSession}
        onRename={onRenameSession}
        loading={sessionsLoading}
      />

      <section className="status-panel">
        <StatusRow label="连接" value={socketStateLabel(socketState)} tone={socketState} />
        <StatusRow label="运行" value={isRunning ? '执行中' : '空闲'} tone={isRunning ? 'running' : 'idle'} />
        <StatusRow label="Run ID" value={activeRunId || '-'} />
      </section>

      <button className="connect-button" type="button" onClick={onReconnect}
        disabled={socketState === 'connected' || isRunning}>
        重新连接
      </button>

      <button className="settings-button" type="button" onClick={onOpenSettings}
        disabled={isRunning}>
        设置
      </button>
    </aside>
  );
}
