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
import type { AttachedFile, ChatMessage, TaskCompleteEvent, Turn } from '../types';

export default function ChatPage() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sessionName, setSessionName] = useState('default');
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const sendingRef = useRef(false);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const activeSessionRef = useRef(sessionName);

  const { configured, reason, apiBase, model } = useConfigContext();
  const {
    sessions,
    loading: sessionsLoading,
    refreshSilent,
    getSession,
    createSessionByName,
    renameSession,
    deleteSession,
  } = useSessions(apiBase);
  const { push: pushToast } = useToasts();

  const api = useMemo(() => createApiClient(apiBase), [apiBase]);

  useEffect(() => {
    activeSessionRef.current = sessionName;
  }, [sessionName]);

  // ZBot 改: 把后端加载的 ChatMessage[] 转成 Turn[] (历史回放统一走 turns 渲染)。
  // 转换规则:
  //   - 相邻 [user, assistant, user, ...] 配对成 turns (user_message + message 配对)
  //   - 孤立的 user 消息 -> 单独一个 completed turn
  //   - 孤立的 assistant 消息 -> 单独一个 turn
  useEffect(() => {
    if (messages.length === 0) return;
    const converted: Turn[] = [];
    let current: Turn | null = null;
    let counter = 0;
    for (const m of messages) {
      if (m.role === 'user') {
        if (current) converted.push(current);
        current = {
          turnId: `history-${sessionName}-${counter++}`,
          status: 'completed',
          items: [{ kind: 'user_message', content: m.content }],
          startedAt: m.timestamp ? new Date(m.timestamp).getTime() : undefined,
        };
      } else if (m.role === 'assistant' && current) {
        current.items.push({ kind: 'message', content: m.content });
        current.endedAt = m.timestamp ? new Date(m.timestamp).getTime() : undefined;
        current.status = 'completed';
        converted.push(current);
        current = null;
      } else if (m.role === 'assistant') {
        converted.push({
          turnId: `history-${sessionName}-${counter++}`,
          status: 'completed',
          items: [{ kind: 'message', content: m.content }],
          startedAt: m.timestamp ? new Date(m.timestamp).getTime() : undefined,
          endedAt: m.timestamp ? new Date(m.timestamp).getTime() : undefined,
        });
      }
    }
    if (current) converted.push(current);
    setHistoryTurns(converted);
  }, [messages, sessionName]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let ignore = false;
    async function loadSessionMessages() {
      setMessagesLoading(true);
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
    livePhase, liveToolName,
    turns,
    sendMessage, stopRun, resetStream, clearTurns, setHistoryTurns,
  } = useAgentStream({ sessions: api.sessions }, {
    onCompleted: (_event: TaskCompleteEvent) => {
      sendingRef.current = false;
      // 用静默 refresh, 不翻转 loading -> 不让会话列表显示"加载中..."
      if (_event.session_name && _event.session_name !== activeSessionRef.current) {
        void refreshSilent();
        return;
      }
      void refreshSilent();
    },
    onDelta: (_content: string) => {
      // turn.message 已经累积了 delta
    },
    onFailed: (info: { message?: string; code?: string }) => {
      sendingRef.current = false;
      pushToast('error', info.message || '任务失败', { sticky: true });
    },
    onStarted: () => {
      sendingRef.current = false;
    },
  });

  // ZBot 改: 切会话时清空 turns (新一轮会话的历史), 重新拉 messages。
  // 之前 resetStream() 也会清 turns, 导致用户在同会话发第二条消息时
  // 第一条消息的回答一起被清掉, 表现为「第二条消息发出去之后, 第一条的回答
  // 不见了」。现在 turns 是"当前会话历史", 跨消息保留; 仅切会话时清空。
  useEffect(() => {
    clearTurns();
    resetStream();
    setMessages([]);
  }, [sessionName, clearTurns, resetStream]);

  const handleAddFile = useCallback(async (file: File) => {
    const FILE_MAX_BYTES = 10 * 1024 * 1024;
    if (file.size > FILE_MAX_BYTES) {
      pushToast('error', `文件 ${file.name} 超过 ${FILE_MAX_BYTES / 1024 / 1024} MB 上限`, { sticky: true });
      return;
    }
    const placeholder: AttachedFile = { file, uploading: true, error: null };
    setAttachedFiles((prev) => [...prev, placeholder]);
    try {
      const res = await api.files.upload([file], model);
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
  }, [api, pushToast, model]);

  const handleRemoveFile = useCallback((index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const canSend =
    !isRunning &&
    input.trim().length > 0 &&
    !attachedFiles.some((f) => f.uploading);

  const handleSend = useCallback(() => {
    const content = input.trim();
    if (!content) return;
    if (sendingRef.current) return;
    sendingRef.current = true;
    // ZBot 改: 不再把用户消息塞到 messages 数组 — 现在用户消息由 useAgentStream
    // 通过 user_message turn item 写进 turns, 与助手回答同一个 turn 渲染。
    // 之前双写到 messages 会出现「用户消息在 messages, 助手回答在 turns, 中间
    // 样式脱节」以及「切会话清 messages 之后用户消息丢失」两个 bug。
    setInput('');
    const fileId = attachedFiles.find((f) => f.fileId)?.fileId;
    sendMessage(content, sessionName.trim() || 'default', fileId);
    setAttachedFiles([]);
  }, [input, sessionName, sendMessage, attachedFiles]);

  const handleStop = useCallback(() => {
    void stopRun();
    pushToast('info', '已停止当前任务');
  }, [stopRun, pushToast]);

  const handleSelectSession = useCallback((name: string) => {
    setSessionName(name);
  }, []);

  const handleDeleteSession = useCallback(async (name: string) => {
    const ok = await deleteSession(name);
    if (ok && name === sessionName) {
      setSessionName('default');
    }
  }, [deleteSession, sessionName]);

  // ZBot 改: SessionList "+" 唤起行内输入框, 这里接收用户输入的名字 (或 undefined = 回车空 -> 后端自动生成)
  // ZBot: 不再因 sendingRef / isRunning 早返回 - 旧逻辑会导致用户在运行中创建新会话时什么都看不到。
  //       新会话创建与正在进行的 run 完全独立, useEffect 切 sessionName 时会 resetStream 关闭旧 stream。
  // ZBot 改: setMessages([]) 由 useEffect[sessionName] 负责, 不在这里重复清。
  const handleNewSession = useCallback(async (requestedName?: string) => {
    const name = await createSessionByName(requestedName);
    if (name) {
      setSessionName(name);
    }
  }, [createSessionByName]);

  const handleRenameSession = useCallback(async (oldName: string, newName: string) => {
    const ok = await renameSession(oldName, newName);
    if (ok && oldName === sessionName) {
      setSessionName(newName);
    }
    return ok;
  }, [renameSession, sessionName]);

  const handlePickExample = useCallback((picked: string) => {
    setInput(picked);
  }, []);

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
          <div className="chat-header-left">
            <h2 className="chat-header-title">{sessionName || '新会话'}</h2>
            {model && <p className="chat-header-model">{model}</p>}
            {configured === false && reason && (
              <p className="config-warning">{reason}</p>
            )}
          </div>
          {/* ZBot 改: 移除右上角重复停止按钮 (Composer 内部已有功能性停止按钮) */}
          <div className="chat-header-right" />
        </header>

        <MessageList
          messages={[]}
          turns={turns}
          isRunning={isRunning}
          loading={messagesLoading}
          livePhase={livePhase}
          liveToolName={liveToolName}
          onPickExample={handlePickExample}
          composerRef={composerRef}
        />
        <Composer
          ref={composerRef}
          input={input}
          setInput={setInput}
          onSend={handleSend}
          onStop={handleStop}
          isRunning={isRunning}
          canSend={canSend}
          attachedFiles={attachedFiles}
          onAddFile={handleAddFile}
          onRemoveFile={handleRemoveFile}
        />
      </section>
    </main>
  );
}