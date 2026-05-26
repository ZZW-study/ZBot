import { useCallback, useMemo, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import Sidebar from '../components/Sidebar';
import MessageList from '../components/MessageList';
import Composer from '../components/Composer';
import ActivityPanel from '../components/ActivityPanel';

export default function ChatPage({ onOpenSettings }) {
  const [messages, setMessages] = useState([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [input, setInput] = useState('');
  const [sessionName, setSessionName] = useState('default');

  const wsUrl = useMemo(() => {
    if (import.meta.env.VITE_ZBOT_WS_URL) return import.meta.env.VITE_ZBOT_WS_URL;
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    // 开发模式下 WebSocket 直连后端 8000（Vite proxy 对 WS 转发不稳定）
    if (import.meta.env.DEV) {
      return `${protocol}://${window.location.hostname}:8000/api/agent/ws`;
    }
    return `${protocol}://${window.location.host}/api/agent/ws`;
  }, []);

  const handleCompleted = useCallback((event) => {
    const finalContent = event.payload?.final_content || event.message;
    setStreamingContent('');
    setMessages((prev) => [
      ...prev,
      {
        id: `${event.run_id}-${event.created_at}-assistant`,
        role: 'assistant',
        content: finalContent,
      },
    ]);
  }, []);

  const handleFailed = useCallback((event) => {
    setStreamingContent('');
    setMessages((prev) => [
      ...prev,
      {
        id: `${event.run_id}-${event.created_at}-error`,
        role: 'assistant',
        content: event.message,
      },
    ]);
  }, []);

  const handleStarted = useCallback(() => {
    setStreamingContent('');
  }, []);

  const handleDelta = useCallback((event) => {
    const delta = event.payload?.delta ?? event.message ?? '';
    if (!delta) return;
    setStreamingContent((prev) => `${prev}${delta}`);
  }, []);

  const {
    socketState,
    events,
    isRunning,
    activeRunId,
    sendMessage,
    stopRun,
    reconnect,
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

  const canSend = socketState === 'connected' && !isRunning && input.trim().length > 0;
  const latestEvent = events[0] || null;

  return (
    <main className="shell">
      <Sidebar
        sessionName={sessionName}
        setSessionName={setSessionName}
        socketState={socketState}
        isRunning={isRunning}
        activeRunId={activeRunId}
        onReconnect={reconnect}
        onOpenSettings={onOpenSettings}
      />

      <section className="chat">
        <header className="chat-header">
          <h2>对话</h2>
          <button className="stop-button" type="button" onClick={stopRun} disabled={!isRunning}>
            停止
          </button>
        </header>

        <MessageList
          messages={messages}
          isRunning={isRunning}
          latestEvent={latestEvent}
          streamingContent={streamingContent}
        />
        <Composer input={input} setInput={setInput} onSend={handleSend} disabled={!canSend} />
      </section>

      <ActivityPanel events={events} />
    </main>
  );
}
