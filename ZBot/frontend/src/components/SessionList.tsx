import { useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import type { SessionSummary } from '../types';

interface SessionListProps {
  sessions: SessionSummary[];
  currentSession: string;
  onSelect: (_name: string) => void;
  onDelete: (_name: string) => void | Promise<void>;
  onNew: () => void;
  onRename: (_oldName: string, _newName: string) => Promise<boolean>;
  loading: boolean;
}

/**
 * SessionList 组件 — 会话列表
 */
export default function SessionList({
  sessions,
  currentSession,
  onSelect,
  onDelete,
  onNew,
  onRename,
  loading,
}: SessionListProps) {
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  // MEDIUM 修复:用 committingRef 防止 Enter + onBlur 双触发。
  // 之前:Enter 提交后 setEditingName(null) -> input 卸载 -> 焦点移 body
  // 触发 onBlur -> 再次 commit(虽然 editingName=null early return,但仍会跑 setState)。
  // 现在:commit 期间上锁,commit 完成后由调用方清锁。
  const committingRef = useRef(false);

  const startEdit = (name: string) => {
    setEditingName(name);
    setEditValue(name);
  };

  const commitEdit = async () => {
    if (!editingName || committingRef.current) return;
    committingRef.current = true;
    try {
      const trimmed = editValue.trim();
      if (trimmed && trimmed !== editingName) {
        await onRename(editingName, trimmed);
      }
      setEditingName(null);
    } finally {
      committingRef.current = false;
    }
  };

  const handleEditKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitEdit();
    } else if (e.key === 'Escape') {
      setEditingName(null);
    }
  };

  if (loading) {
    return (
      <div className="session-list">
        <p className="session-empty">加载中...</p>
      </div>
    );
  }

  return (
    <div className="session-list">
      {/* 头部：标题 + 新建按钮 */}
      <div className="session-header">
        <span className="session-title">会话</span>
        <button
          className="session-new-btn"
          onClick={onNew}
          title="新建会话"
        >
          +
        </button>
      </div>

      {/* 会话列表 */}
      <ul className="session-items">
        {sessions.length === 0 ? (
          <li className="session-empty">还没有会话</li>
        ) : (
          sessions.map((session) => (
            <li
              key={session.name}
              className={`session-item ${session.name === currentSession ? 'active' : ''}`}
              onClick={() => onSelect(session.name)}
            >
              {/* 会话名称：编辑态或显示态 */}
              {editingName === session.name ? (
                <input
                  className="session-rename-input"
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onBlur={commitEdit}
                  onKeyDown={handleEditKeyDown}
                  onClick={(e: MouseEvent<HTMLInputElement>) => e.stopPropagation()}
                  autoFocus
                />
              ) : (
                <span
                  className="session-name"
                  onDoubleClick={(e: MouseEvent<HTMLSpanElement>) => {
                    e.stopPropagation();
                    startEdit(session.name);
                  }}
                  title="双击重命名"
                >
                  {session.name}
                </span>
              )}

              {/* 删除按钮 */}
              <button
                className="session-delete-btn"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(session.name);
                }}
                title="删除会话"
              >
                ×
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
