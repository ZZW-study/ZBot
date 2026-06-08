import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAgentStream } from '../hooks/useAgentStream';
import { useConfigContext } from '../hooks/useConfigContext';
import { useSessions } from '../hooks/useSessions';
import { useToasts } from '../hooks/useToasts';
import { createApiClient } from '../lib/api';
import Sidebar from '../components/Sidebar';
import MessageList from '../components/MessageList';
import Composer from '../components/Composer';
import type { AttachedFile, ChatMessage, TaskCompleteEvent } from '../types';

export default function ChatPage() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [input, setInput] = useState('');
  const [sessionName, setSessionName] = useState('default');
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  // MEDIUM 修复:inline 弹层输入框,替代 window.prompt(后者阻塞主线程)。
  const [newSessionDialog, setNewSessionDialog] = useState<{ open: boolean; name: string; error: string }>({
    open: false, name: '', error: '',
  });
  const activeSessionRef = useRef(sessionName);
  // C2 修复:同步守卫,防止连点/双击/键盘事件竞态导致同 render 内多次 sendMessage。
  // setIsRunning 是异步的,React 18 自动批处理下,同 render 内多次 sendMessage
  // 都会通过 isRunning 守卫,所以必须用 ref 同步翻转。
  const sendingRef = useRef(false);

  // H31 修复:从 ConfigContext 读,不再自己调 useConfig。
  const { configured, reason, apiBase } = useConfigContext();
  const {
    sessions,
    loading: sessionsLoading,
    refresh,
    getSession,
    createSession,
    renameSession,
    deleteSession,
  } = useSessions(apiBase);
  const { push: pushToast } = useToasts();

  const api = useMemo(() => createApiClient(apiBase), [apiBase]);

  useEffect(() => {
    activeSessionRef.current = sessionName;
  }, [sessionName]);

  useEffect(() => {
    let ignore = false;

    async function loadSessionMessages() {
      setMessagesLoading(true);
      setStreamingContent('');
      const detail = await getSession(sessionName);
      if (!ignore) {
        setMessages(detail?.messages || []);
        setMessagesLoading(false);
      }
    }

    loadSessionMessages();

    return () => {
      ignore = true;
    };
  }, [getSession, sessionName]);

  const {
    socketState, isRunning, activeRunId,
    sendMessage, stopRun, resetStream,
  } = useAgentStream({ sessions: api.sessions }, {
    onCompleted: (event: TaskCompleteEvent) => {
      sendingRef.current = false;
      if (event.session_name && event.session_name !== activeSessionRef.current) {
        refresh();
        return;
      }
      // task_complete 一次性给出 final_content,与 WS 路径的双事件(turn.completed + run.completed)不同,
      // 不需要去重。直接追加一条 assistant 消息。
      const finalContent = event.final_content || '';
      if (!finalContent) return;
      setStreamingContent('');
      setMessages((prev) => {
        const msgId = `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        return [
          ...prev,
          { id: msgId, role: 'assistant', content: finalContent },
        ];
      });
      refresh();
    },
    onDelta: (content: string) => {
      setStreamingContent((prev) => `${prev}${content}`);
    },
    onFailed: (info: { message?: string; code?: string }) => {
      sendingRef.current = false;
      // 不再把错误塞进 messages — 改用 toast,让消息列表只展示真实对话。
      pushToast('error', info.message || '任务失败', { sticky: true });
      setStreamingContent('');
    },
    onStarted: () => {
      sendingRef.current = false;
      setStreamingContent('');
    },
  });

  // 切换 session 时主动清状态,防止旧 session 的 turns 残留
  useEffect(() => {
    resetStream();
  }, [sessionName, resetStream]);

  const handleAddFile = useCallback(async (file: File) => {
    // H32 修复:客户端先校验大小,避免大文件空跑网络往返被后端 413。
    // 后端 MAX_FILE_BYTES = 10 MB,这里和 Composer 保持一致。
    const FILE_MAX_BYTES = 10 * 1024 * 1024;
    if (file.size > FILE_MAX_BYTES) {
      pushToast('error', `文件 ${file.name} 超过 ${FILE_MAX_BYTES / 1024 / 1024} MB 上限`, { sticky: true });
      return;
    }
    const placeholder: AttachedFile = { file, uploading: true, error: null };
    setAttachedFiles((prev) => [...prev, placeholder]);
    try {
      const res = await api.files.upload([file]);
      setAttachedFiles((prev) =>
        prev.map((f) => (f === placeholder ? { ...f, uploading: false, fileId: res.file_id } : f))
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : '文件上传失败';
      setAttachedFiles((prev) =>
        prev.map((f) => (f === placeholder ? { ...f, uploading: false, error: msg } : f))
      );
      pushToast('error', `文件上传失败: ${msg}`, { sticky: true });
    }
  }, [api, pushToast]);

  const handleRemoveFile = useCallback((index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const canSend =
    socketState === 'connected' &&
    !isRunning &&
    input.trim().length > 0 &&
    !attachedFiles.some((f) => f.uploading);

  const handleSend = useCallback(() => {
    const content = input.trim();
    if (!content) return;
    // C2 修复:同步守卫防双发。startingRef 守卫由 useAgentStream 内部也有,
    // 但 setIsRunning 是异步的,React 18 自动批处理下同 render 内多次 sendMessage
    // 都会通过 isRunning 检查,所以必须这里再用 ref 同步翻转。
    if (sendingRef.current) return;
    sendingRef.current = true;
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content }]);
    setInput('');
    // 取第一个已上传完成的文件 id 透传 — 多个文件场景等 Composer UX PR 一起做。
    const fileId = attachedFiles.find((f) => f.fileId)?.fileId;
    sendMessage(content, sessionName.trim() || 'default', fileId);
    setAttachedFiles([]);
  }, [input, sessionName, sendMessage, attachedFiles]);

  const handleSelectSession = useCallback((name: string) => {
    setSessionName(name);
  }, []);

  const handleDeleteSession = useCallback(async (name: string) => {
    const ok = await deleteSession(name);
    if (ok && name === sessionName) {
      setSessionName('default');
    }
  }, [deleteSession, sessionName]);

  const handleNewSession = useCallback(() => {
    // MEDIUM 修复:打开 inline 弹层(替代阻塞主线程的 window.prompt)。
    setNewSessionDialog({ open: true, name: '', error: '' });
  }, []);

  const handleConfirmNewSession = useCallback(async () => {
    const trimmed = newSessionDialog.name.trim();
    if (!trimmed) {
      setNewSessionDialog((prev) => ({ ...prev, error: '会话名不能为空' }));
      return;
    }
    if (!/^[\w\-.]{1,200}$/.test(trimmed)) {
      setNewSessionDialog((prev) => ({
        ...prev,
        error: '只能包含字母、数字、下划线、连字符、点,长度 1-200',
      }));
      return;
    }
    const ok = await createSession(trimmed);
    if (ok) {
      setSessionName(trimmed);
      setMessages([]);
      setStreamingContent('');
      setNewSessionDialog({ open: false, name: '', error: '' });
    } else {
      setNewSessionDialog((prev) => ({ ...prev, error: '创建会话失败' }));
    }
  }, [newSessionDialog.name, createSession]);

  const handleRenameSession = useCallback(async (oldName: string, newName: string) => {
    const ok = await renameSession(oldName, newName);
    if (ok && oldName === sessionName) {
      setSessionName(newName);
    }
    return ok;
  }, [renameSession, sessionName]);

  return (
    <main className="shell">
      <Sidebar
        sessionName={sessionName}
        socketState={socketState}
        isRunning={isRunning}
        activeRunId={activeRunId}
        onReset={resetStream}
        onOpenSettings={() => navigate('/onboard')}
        sessions={sessions}
        sessionsLoading={sessionsLoading}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onNewSession={handleNewSession}
        onRenameSession={handleRenameSession}
      />

      <section className="chat">
        <header className="chat-header">
          <div>
            <h2>对话</h2>
            {configured === false && reason && (
              <p className="config-warning">{reason}</p>
            )}
          </div>
          <button className="stop-button" type="button" onClick={stopRun} disabled={!isRunning}>
            停止
          </button>
        </header>

        <MessageList
          messages={messages}
          isRunning={isRunning}
          streamingContent={streamingContent}
          loading={messagesLoading}
        />
        <Composer
          input={input}
          setInput={setInput}
          onSend={handleSend}
          disabled={!canSend}
          attachedFiles={attachedFiles}
          onAddFile={handleAddFile}
          onRemoveFile={handleRemoveFile}
        />
      </section>

      {newSessionDialog.open && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <h3>新建会话</h3>
            <input
              autoFocus
              type="text"
              value={newSessionDialog.name}
              onChange={(e) => setNewSessionDialog((prev) => ({ ...prev, name: e.target.value, error: '' }))}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleConfirmNewSession();
                else if (e.key === 'Escape') setNewSessionDialog({ open: false, name: '', error: '' });
              }}
              placeholder="例如:weekly-report"
              maxLength={200}
            />
            {newSessionDialog.error && <p className="modal-error">{newSessionDialog.error}</p>}
            <div className="modal-actions">
              <button type="button" onClick={() => setNewSessionDialog({ open: false, name: '', error: '' })}>
                取消
              </button>
              <button type="button" onClick={() => void handleConfirmNewSession()}>
                创建
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
