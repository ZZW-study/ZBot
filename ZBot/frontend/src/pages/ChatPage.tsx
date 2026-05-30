import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWebSocket } from '../hooks/useWebSocket';
import { useConfig } from '../hooks/useConfig';
import { useSessions } from '../hooks/useSessions';
import Sidebar from '../components/Sidebar';
import MessageList from '../components/MessageList';
import Composer from '../components/Composer';
import type { AgentEvent, ChatMessage } from '../types';

export default function ChatPage() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [input, setInput] = useState('');
  const [sessionName, setSessionName] = useState('default');
  const [messagesLoading, setMessagesLoading] = useState(false);

  const { apiBase, configured, reason } = useConfig();
  const {
    sessions,
    loading: sessionsLoading,
    refresh,
    getSession,
    createSession,
    renameSession,
    deleteSession,
  } = useSessions(apiBase);

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

  const wsUrl = useMemo(() => {
    if (import.meta.env.VITE_ZBOT_WS_URL) return import.meta.env.VITE_ZBOT_WS_URL;
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    if (import.meta.env.DEV) {
      return `${protocol}://${window.location.hostname}:8000/api/agent/ws`;
    }
    return `${protocol}://${window.location.host}/api/agent/ws`;
  }, []);

  const handleCompleted = useCallback((event: AgentEvent) => {
    const payloadContent = event.payload?.final_content;
    const finalContent = typeof payloadContent === 'string' ? payloadContent : event.message || '';
    setStreamingContent('');
    setMessages((prev) => [
      ...prev,
      { id: `${event.run_id}-${event.created_at}-assistant`, role: 'assistant', content: finalContent },
    ]);
    refresh();
  }, [refresh]);

  const handleFailed = useCallback((event: AgentEvent) => {
    setStreamingContent('');
    setMessages((prev) => [
      ...prev,
      { id: `${event.run_id}-${event.created_at}-error`, role: 'assistant', content: event.message || '任务失败' },
    ]);
  }, []);

  const handleStarted = useCallback(() => {
    setStreamingContent('');
  }, []);

  const handleDelta = useCallback((event: AgentEvent) => {
    const payloadDelta = event.payload?.delta;
    const delta = (typeof payloadDelta === 'string' ? payloadDelta : event.message) ?? '';
    if (!delta) return;
    setStreamingContent((prev) => `${prev}${delta}`);
  }, []);

  const {
    socketState, events, isRunning, activeRunId,
    sendMessage, stopRun, reconnect,
  } = useWebSocket(wsUrl, {
    onCompleted: handleCompleted,
    onDelta: handleDelta,
    onFailed: handleFailed,
    onStarted: handleStarted,
  });

  const handleSend = useCallback(() => {
    const content = input.trim();
    if (!content) return;
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content }]);
    setInput('');
    sendMessage(content, sessionName.trim() || 'default');
  }, [input, sessionName, sendMessage]);

  const handleSelectSession = useCallback((name: string) => {
    setSessionName(name);
  }, []);

  const handleDeleteSession = useCallback(async (name: string) => {
    const ok = await deleteSession(name);
    if (ok && name === sessionName) {
      setSessionName('default');
    }
  }, [deleteSession, sessionName]);

  const handleNewSession = useCallback(async () => {
    const name = prompt('请输入新会话名称');
    if (!name || !name.trim()) return;

    const trimmed = name.trim();
    const ok = await createSession(trimmed);
    if (ok) {
      setSessionName(trimmed);
      setMessages([]);
      setStreamingContent('');
    }
  }, [createSession]);

  const handleRenameSession = useCallback(async (oldName: string, newName: string) => {
    const ok = await renameSession(oldName, newName);
    if (ok && oldName === sessionName) {
      setSessionName(newName);
    }
    return ok;
  }, [renameSession, sessionName]);

  const canSend = socketState === 'connected' && !isRunning && input.trim().length > 0;
  const latestEvent = events[0] || null;

  return (
    <main className="shell">
      <Sidebar
        sessionName={sessionName}
        socketState={socketState}
        isRunning={isRunning}
        activeRunId={activeRunId}
        onReconnect={reconnect}
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
          latestEvent={latestEvent}
          streamingContent={streamingContent}
          loading={messagesLoading}
        />
        <Composer input={input} setInput={setInput} onSend={handleSend} disabled={!canSend} />
      </section>
    </main>
  );
}
