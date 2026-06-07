/**
 * useAgentStream
 *
 * Owns:
 *  - the active SSE EventSource
 *  - the current run state (turns, token usage, status)
 *  - per-run refs (runId / thread / completed)
 *
 * Builds a `Turn[]` view of the run so the UI can render reasoning + tool
 * calls + assistant text in order. Each turn is created on
 * `event_msg/task_started` and finalized on `event_msg/task_complete`
 * (status from payload). Tool call / output events are paired by `call_id`
 * and folded into the turn they belong to.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  AgentEvent,
  RunStatus,
  SocketState,
  TaskCompleteEvent,
  TokenUsage,
  Turn,
  TurnItem,
} from '../types';

const EMPTY_TOKEN_USAGE: TokenUsage = { inputTokens: 0, outputTokens: 0, cachedTokens: 0 };

interface StartRunResponse {
  runId: string;
  eventsUrl: string;
  threadName: string;
}

interface UseAgentStreamCallbacks {
  onCompleted?: (_event: TaskCompleteEvent) => void;
  onDelta?: (_content: string) => void;
  onFailed?: (_event: { message?: string; code?: string }) => void;
  onCronReminder?: (_message: string) => void;
  onStarted?: () => void;
  onSessionMeta?: (_payload: Record<string, unknown>) => void;
}

interface EventMsgPayloadShape {
  type?: string;
  turn_id?: string;
  status?: RunStatus;
  message?: string;
  final_content?: string;
  code?: string;
  input_tokens?: number;
  output_tokens?: number;
  cached_tokens?: number;
  model_context_window?: number;
}

export function useAgentStream(
  api: {
    threads: {
      runs: {
        start: (n: string, m: string, fid?: string) => Promise<StartRunResponse>;
        cancel: (n: string, id: string) => Promise<void>;
      };
    };
  },
  callbacks: UseAgentStreamCallbacks = {},
) {
  const [socketState, setSocketState] = useState<SocketState>('disconnected');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState('');
  const [activeThread, setActiveThread] = useState('');
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenUsage>(EMPTY_TOKEN_USAGE);
  const [modelContextWindow, setModelContextWindow] = useState(0);

  const sourceRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string>('');
  const threadRef = useRef<string>('');
  // Tracks whether the current SSE stream has emitted a terminal event
  // (task_complete or error payload). EventSource also fires 'error' on a
  // clean close, so we use this ref to ignore post-completion transport
  // errors in the 'error' listener below.
  const completedRef = useRef(false);
  // Mirror `turns` into a ref so the response_item handler (registered inside
  // sendMessage) can read the latest value without re-registering the handler.
  const turnsRef = useRef<Turn[]>([]);
  useEffect(() => {
    turnsRef.current = turns;
  }, [turns]);

  const closeStream = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  const resetStream = useCallback(() => {
    // Mark the stream as completed BEFORE closing so the EventSource\'s
    // 'error' listener (which fires on close) does not show a misleading
    // 'Connection lost' toast when the caller is just resetting state
    // (e.g. thread switch, new run). sendMessage clears the ref again
    // immediately after to start the new run with a fresh ref.
    completedRef.current = true;
    closeStream();
    setTurns([]);
    setError(null);
    setRunStatus(null);
    setIsRunning(false);
    setActiveRunId('');
    setActiveThread('');
    setTokenUsage(EMPTY_TOKEN_USAGE);
    setModelContextWindow(0);
    runIdRef.current = '';
    threadRef.current = '';
  }, [closeStream]);

  // Cleanup on unmount
  useEffect(() => {
    return () => closeStream();
  }, [closeStream]);

  const upsertItem = useCallback(
    (turnId: string, matcher: (item: TurnItem) => boolean, mutator: (item: TurnItem) => TurnItem) => {
      setTurns((prev) =>
        prev.map((t) => {
          if (t.turnId !== turnId) return t;
          const idx = t.items.findIndex(matcher);
          if (idx < 0) return t;
          const items = t.items.slice();
          items[idx] = mutator(items[idx]);
          return { ...t, items };
        }),
      );
    },
    [],
  );

  const appendItem = useCallback((turnId: string, item: TurnItem) => {
    setTurns((prev) =>
      prev.map((t) => (t.turnId === turnId ? { ...t, items: [...t.items, item] } : t)),
    );
  }, []);

  const sendMessage = useCallback(
    async (message: string, sessionName: string, fileId?: string) => {
      const thread = sessionName?.trim() || 'default';
      if (!message.trim()) return;
      // Reset hook state (closes previous stream + clears turns/error), then
      // prime for the new run. resetStream marks the previous stream as
      // completed to suppress the spurious 'Connection lost' toast from
      // the EventSource close; we clear the ref here so the upcoming
      // SSE connection can surface real errors again.
      resetStream();
      completedRef.current = false;
      setRunStatus('queued');
      setIsRunning(true);

      try {
        const res = await api.threads.runs.start(thread, message, fileId);
        runIdRef.current = res.runId;
        threadRef.current = thread;
        setActiveRunId(res.runId);
        setActiveThread(thread);

        setSocketState('connecting');
        const es = new EventSource(res.eventsUrl);
        sourceRef.current = es;
        es.addEventListener('open', () => {
          setSocketState('connected');
        });

        es.addEventListener('session_meta', (e: MessageEvent) => {
          if (sourceRef.current !== es) return;
          try {
            const data = JSON.parse(e.data) as AgentEvent;
            callbacks.onSessionMeta?.(data.payload ?? {});
          } catch { /* ignore */ }
        });

        es.addEventListener('event_msg', (e: MessageEvent) => {
          if (sourceRef.current !== es) return;
          try {
            const data = JSON.parse(e.data) as AgentEvent;
            const payload = (data.payload ?? {}) as EventMsgPayloadShape;

            if (payload.type === 'task_started') {
              const turnId = payload.turn_id || `t-${Date.now()}`;
              const ctxWindow = Number(payload.model_context_window || 0);
              setModelContextWindow(ctxWindow);
              setTurns((prev) =>
                prev.some((t) => t.turnId === turnId)
                  ? prev.map((t) => (t.turnId === turnId ? { ...t, status: 'running', modelContextWindow: ctxWindow || t.modelContextWindow } : t))
                  : [...prev, { turnId, status: 'running', items: [], startedAt: Date.now(), modelContextWindow: ctxWindow }],
              );
              setIsRunning(true);
              callbacks.onStarted?.();
            } else if (payload.type === 'task_complete') {
              const turnId = payload.turn_id || '';
              const nextStatus: Turn['status'] =
                payload.status === 'failed' ? 'failed'
                : payload.status === 'cancelled' ? 'cancelled'
                : 'completed';
              if (turnId) {
                setTurns((prev) =>
                  prev.map((t) => (t.turnId === turnId ? { ...t, status: nextStatus, endedAt: Date.now() } : t)),
                );
              }
              setIsRunning(false);
              setRunStatus(payload.status || 'completed');
              completedRef.current = true;
              callbacks.onCompleted?.(payload as unknown as TaskCompleteEvent);
            } else if (payload.type === 'error') {
              const turnId = payload.turn_id || '';
              if (turnId) {
                appendItem(turnId, { kind: 'error', message: payload.message || 'agent error', code: payload.code });
                setTurns((prev) =>
                  prev.map((t) => (t.turnId === turnId ? { ...t, status: 'failed', endedAt: Date.now() } : t)),
                );
              }
              setIsRunning(false);
              setRunStatus('failed');
              completedRef.current = true;
              // Surface to caller exactly once per error. The `error` state is
              // intentionally not set here so the caller can rely on
              // `onFailed` as the single notification path.
              callbacks.onFailed?.({ message: payload.message, code: payload.code });
            } else if (payload.type === 'cron_reminder') {
              // Cron reminders are system-level, not part of any turn's content.
              // Surface as a sticky info toast so the user can see them
              // without polluting the message list.
              const name = payload.message || 'Cron job';
              callbacks.onCronReminder?.(name);
            } else if (payload.type === 'token_count') {
              setTokenUsage({
                inputTokens: Number(payload.input_tokens || 0),
                outputTokens: Number(payload.output_tokens || 0),
                cachedTokens: Number(payload.cached_tokens || 0),
              });
            }
            // user_message echoes are informational; no-op.
          } catch { /* ignore */ }
        });

        es.addEventListener('response_item', (e: MessageEvent) => {
          if (sourceRef.current !== es) return;
          try {
            const data = JSON.parse(e.data) as AgentEvent;
            const payload = (data.payload ?? {}) as {
              type?: string;
              role?: string;
              content?: string;
              delta?: boolean;
              call_id?: string;
              name?: string;
              arguments?: string;
              output?: string;
              summary?: string;
            };
            const currentTurn = turnsRef.current[turnsRef.current.length - 1];
            const turnId = currentTurn?.turnId;

            if (payload.type === 'message' && payload.role === 'assistant') {
              const content = payload.content || '';
              const isFinal = payload.delta === false;
              if (content && !isFinal) {
                callbacks.onDelta?.(content);
              }
              if (turnId && content) {
                // Coalesce consecutive assistant message items into one.
                // For streaming chunks (delta !== false) we append to the
                // existing message. For the final frame (delta === false),
                // we REPLACE — the deltas already accumulated the full
                // content, so re-appending would double it.
                setTurns((prev) =>
                  prev.map((t) => {
                    if (t.turnId !== turnId) return t;
                    const existing = t.items.find((it) => it.kind === 'message');
                    if (existing && existing.kind === 'message') {
                      const next = isFinal
                        ? content
                        : existing.content + content;
                      return {
                        ...t,
                        items: t.items.map((it) => (it === existing ? { ...it, content: next } : it)),
                      };
                    }
                    return { ...t, items: [...t.items, { kind: 'message', content }] };
                  }),
                );
              }
            } else if (payload.type === 'function_call') {
              if (turnId && payload.call_id && payload.name) {
                let parsedArgs: Record<string, unknown> = {};
                try {
                  parsedArgs = payload.arguments ? JSON.parse(payload.arguments) : {};
                } catch { parsedArgs = { _raw: payload.arguments }; }
                appendItem(turnId, {
                  kind: 'tool_call',
                  callId: payload.call_id,
                  name: payload.name,
                  arguments: parsedArgs,
                  status: 'running',
                  startedAt: Date.now(),
                });
              }
            } else if (payload.type === 'function_call_output') {
              if (turnId && payload.call_id) {
                upsertItem(
                  turnId,
                  (it) => it.kind === 'tool_call' && it.callId === payload.call_id,
                  (it) =>
                    it.kind === 'tool_call'
                      ? { ...it, status: 'done', output: payload.output ?? '', endedAt: Date.now() }
                      : it,
                );
              }
            } else if (payload.type === 'reasoning') {
              if (turnId && payload.summary) {
                appendItem(turnId, { kind: 'reasoning', summary: payload.summary });
              }
            }
          } catch { /* ignore */ }
        });

        es.addEventListener('error', () => {
          // Ignore errors from stale EventSources. The browser may still
          // fire 'error' on a previous EventSource after closeStream()
          // returned and a new EventSource has been installed. Without
          // this guard, a stale transport error from a previous run would
          // be misattributed to the new run.
          if (sourceRef.current !== es) return;
          // EventSource fires 'error' on any disconnect, including the
          // normal close that follows a received 'done' event. Only treat
          // it as a failure if we never saw a terminal event for this run.
          if (!completedRef.current) {
            setSocketState('error');
            setIsRunning(false);
            // Surface to the caller so a sticky error toast appears.
            // Use a distinct message from agent-emitted errors so the user
            // can tell the stream died vs. the agent returned an error.
            callbacks.onFailed?.({ message: 'Connection lost', code: 'stream_disconnected' });
          }
        });

        es.addEventListener('done', () => {
          // Same stale-source guard as the 'error' listener.
          if (sourceRef.current !== es) return;
          es.close();
          setSocketState('disconnected');
        });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'failed to start run';
        setIsRunning(false);
        setRunStatus('failed');
        // Surface to caller exactly once.
        callbacks.onFailed?.({ message: msg });
      }
    },
    [api, callbacks, appendItem, resetStream, upsertItem],
  );

  const stopRun = useCallback(async () => {
    if (!runIdRef.current || !threadRef.current) return;
    try {
      await api.threads.runs.cancel(threadRef.current, runIdRef.current);
      setRunStatus('cancelled');
    } catch { /* ignore: best effort */ }
    setIsRunning(false);
    // Mark the stream as completed BEFORE closing so the EventSource's
    // 'error' listener (which fires on close) treats this as a clean
    // shutdown rather than a real network failure.
    completedRef.current = true;
    closeStream();
  }, [api, closeStream]);

  return {
    socketState,
    turns,
    isRunning,
    activeRunId,
    activeThread,
    runStatus,
    error,
    tokenUsage,
    modelContextWindow,
    sendMessage,
    stopRun,
    resetStream,
  };
}
