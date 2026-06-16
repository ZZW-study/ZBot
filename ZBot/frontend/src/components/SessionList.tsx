/**
 * SessionList - 侧边栏中的会话列表
 *
 * ZBot 改:
 *  - "+" 号不再"一键创建 chat-<ts>", 而是唤起行内输入框, 让用户输入名字后回车确认。
 *  - 输入为空时回车, fallback 到 "chat-<ts>" 自动生成名 (避免空名 / 与现有会话同名)。
 *  - 已有会话项仍可双击重命名 (原行为不变)。
 */

import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react';
import type { SessionSummary } from '../types';

interface SessionListProps {
  sessions: SessionSummary[];
  currentSession: string;
  onSelect: (_name: string) => void;
  onDelete: (_name: string) => void | Promise<void>;
  onNew: (_name?: string) => void;
  onRename: (_oldName: string, _newName: string) => Promise<boolean>;
  loading: boolean;
}

function genDefaultName(): string {
  // 与后端 quick-create 行为一致: chat-<timestamp>
  return `chat-${Date.now()}`;
}

export default function SessionList({
  sessions,
  currentSession,
  onSelect,
  onDelete,
  onNew,
  onRename,
  loading,
}: SessionListProps) {
  // 正在新建的输入框 (行内)
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const newInputRef = useRef<HTMLInputElement | null>(null);
  const creatingRef = useRef(false);

  // 已有会话的编辑 (重命名)
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const committingRef = useRef(false);

  // 点击 + 后 focus 输入框
  useEffect(() => {
    if (isCreating) newInputRef.current?.focus();
  }, [isCreating]);

  const startCreate = () => {
    setIsCreating(true);
    setNewName('');
  };

  const cancelCreate = () => {
    setIsCreating(false);
    setNewName('');
  };

  const commitCreate = () => {
    if (creatingRef.current) return;
    creatingRef.current = true;
    const trimmed = newName.trim();
    // 空名 → fallback 默认名
    const finalName = trimmed || genDefaultName();
    // 同步触发 onNew, 由上层 (ChatPage) 真正创建会话; 之后收起输入框
    setIsCreating(false);
    setNewName('');
    Promise.resolve(onNew(finalName)).finally(() => {
      creatingRef.current = false;
    });
  };

  const handleNewKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitCreate();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelCreate();
    }
  };

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
      void commitEdit();
    } else if (e.key === 'Escape') {
      setEditingName(null);
    }
  };

  // ZBot: only show "loading" placeholder if we have NO sessions yet (first mount).
  //       On subsequent refreshes (e.g. after create), keep showing the existing list
  //       so the user doesn't see the list disappear and reappear.
  if (loading && sessions.length === 0) {
    return (
      <div className="session-list">
        <p className="session-empty">加载中...</p>
      </div>
    );
  }

  return (
    <div className="session-list">
      {/* 头部: 标题 + 新建按钮 / 行内输入框 */}
      <div className="session-header">
        <span className="session-title">会话</span>
        {!isCreating && (
          <button
            className="session-new-btn"
            onClick={startCreate}
            title="新建会话"
            aria-label="新建会话"
          >
            +
          </button>
        )}
      </div>

      {/* 行内新建输入框 (点击 + 后出现) */}
      {isCreating && (
        <div className="session-create-row">
          <input
            ref={newInputRef}
            className="session-rename-input"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onBlur={commitCreate}
            onKeyDown={handleNewKeyDown}
            placeholder="给新会话起个名字"
            aria-label="新会话名字"
            maxLength={64}
          />
          <button
            type="button"
            className="session-create-confirm"
            onMouseDown={(e) => e.preventDefault()}
            onClick={commitCreate}
            title="确认新建 (Enter)"
            aria-label="确认新建"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <path d="M2 6.5l3 3 5-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </button>
        </div>
      )}

      {/* 会话列表 */}
      <ul className="session-items">
        {sessions.length === 0 && !isCreating ? (
          <li className="session-empty">还没有会话</li>
        ) : (
          sessions.map((session) => (
            <li
              key={session.name}
              className={`session-item ${session.name === currentSession ? 'active' : ''}`}
              onClick={() => onSelect(session.name)}
            >
              {/* 会话名称: 编辑态或显示态 */}
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
                aria-label="删除会话"
              >
                <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                  <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" fill="none" />
                </svg>
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}