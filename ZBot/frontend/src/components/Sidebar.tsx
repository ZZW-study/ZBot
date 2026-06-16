import StatusRow from './StatusRow';
import SessionList from './SessionList';
import { connectionStateLabel } from '../utils/format';
import type { SessionSummary, SocketState } from '../types';

interface SidebarProps {
  sessionName: string;
  socketState: SocketState;
  isRunning: boolean;
  activeRunId: string;
  onReset: () => void;
  onOpenSettings: () => void;
  sessions: SessionSummary[];
  sessionsLoading: boolean;
  onSelectSession: (_name: string) => void;
  onDeleteSession: (_name: string) => void | Promise<void>;
  onNewSession: (_name?: string) => void;
  onRenameSession: (_oldName: string, _newName: string) => Promise<boolean>;
}

export default function Sidebar({
  sessionName, socketState, isRunning,
  activeRunId, onReset, onOpenSettings,
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
        <StatusRow label="连接" value={connectionStateLabel(socketState)} tone={socketState} />
        <StatusRow label="运行" value={isRunning ? '执行中' : '空闲'} tone={isRunning ? 'running' : 'idle'} />
        <StatusRow label="Run ID" value={activeRunId || '-'} />
      </section>

      <div className="sidebar-actions">
        <button className="connect-button" type="button" onClick={onReset}
          disabled={socketState === 'connected' || isRunning}
          title="重置状态"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
            <path
              d="M3 8a5 5 0 018-3.5M13 8a5 5 0 01-8 3.5M11 3v3h-3M5 13v-3h3"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
          重置状态
        </button>

        <button className="settings-button" type="button" onClick={onOpenSettings}
          disabled={isRunning}
          title="设置"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.4" fill="none" />
            <path
              d="M8 1.5v2M8 12.5v2M14.5 8h-2M3.5 8h-2M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4M12.6 12.6l-1.4-1.4M4.8 4.8L3.4 3.4"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
          设置
        </button>
      </div>
    </aside>
  );
}
