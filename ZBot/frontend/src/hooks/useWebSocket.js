import { useCallback, useEffect, useRef, useState } from 'react';

const MAX_EVENTS = 80;

/**
 * 管理 WebSocket 连接与 Agent 事件。
 * 返回 { socketState, events, isRunning, activeRunId, sendMessage, stopRun, reconnect }
 */
export function useWebSocket(wsUrl, { onCompleted, onDelta, onFailed, onStarted } = {}) {
  const socketRef = useRef(null);
  const [socketState, setSocketState] = useState('connecting');
  const [events, setEvents] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState('');
  const [connectionAttempt, setConnectionAttempt] = useState(0);

  const appendEvent = useCallback((event) => {
    setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS));
    if (event.run_id && event.run_id !== 'control') setActiveRunId(event.run_id);
  }, []);

  const handleAgentEvent = useCallback(
    (event) => {
      if (event.run_id && event.run_id !== 'control') setActiveRunId(event.run_id);

      if (event.type === 'assistant.delta') {
        onDelta?.(event);
        return;
      }

      appendEvent(event);

      if (event.type === 'turn.started') {
        setIsRunning(true);
        onStarted?.(event);
        return;
      }

      if (event.type === 'turn.completed') {
        setIsRunning(false);
        onCompleted?.(event);
        return;
      }

      if (event.type === 'run.completed') {
        setIsRunning(false);
        return;
      }

      if (event.type === 'run.failed' || event.type === 'run.cancelled') {
        setIsRunning(false);
        onFailed?.(event);
      }
    },
    [appendEvent, onCompleted, onDelta, onFailed, onStarted],
  );

  useEffect(() => {
    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    socket.addEventListener('open', () => setSocketState('connected'));
    socket.addEventListener('close', () => {
      setSocketState('disconnected');
      setIsRunning(false);
    });
    socket.addEventListener('error', () => setSocketState('error'));
    socket.addEventListener('message', (messageEvent) => {
      try {
        handleAgentEvent(JSON.parse(messageEvent.data));
      } catch {
        appendEvent({
          type: 'client.error',
          message: '收到无法解析的 WebSocket 消息。',
          created_at: new Date().toISOString(),
        });
      }
    });

    return () => socket.close();
  }, [appendEvent, connectionAttempt, handleAgentEvent, wsUrl]);

  const sendMessage = useCallback(
    (message, sessionName) => {
      if (!socketRef.current || socketState !== 'connected' || isRunning) return;
      setEvents([]);
      socketRef.current.send(
        JSON.stringify({
          type: 'run.start',
          message,
          session_name: sessionName || 'default',
        }),
      );
    },
    [socketState, isRunning],
  );

  const stopRun = useCallback(() => {
    if (!socketRef.current || socketState !== 'connected') return;
    socketRef.current.send(JSON.stringify({ type: 'run.cancel' }));
  }, [socketState]);

  const reconnect = useCallback(() => {
    setSocketState('connecting');
    setConnectionAttempt((v) => v + 1);
  }, []);

  return {
    socketState,
    events,
    isRunning,
    activeRunId,
    sendMessage,
    stopRun,
    reconnect,
  };
}
