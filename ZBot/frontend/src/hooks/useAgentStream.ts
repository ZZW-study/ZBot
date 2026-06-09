/**
 * useAgentStream
 *
 * Owns:
 *  - the active SSE EventSource
 *  - the current run state (turns, token usage, status)
 *  - per-run refs (runId / session / completed)
 *
 * Builds a `Turn[]` view of the run so the UI can render reasoning + tool
 * calls + assistant text in order. Each turn is created on
 * `event_msg/task_started` and finalized on `event_msg/task_complete`
 * (status from payload). Tool call / output events are paired by `call_id`
 * and folded into the turn they belong to.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  RunStatus,
  SocketState,
  TaskCompleteEvent,
  TokenUsage,
  Turn,
  TurnItem,
} from '../types';

const EMPTY_TOKEN_USAGE: TokenUsage = { inputTokens: 0, outputTokens: 0, cachedTokens: 0 };

interface UseAgentStreamCallbacks {
  onCompleted?: (_event: TaskCompleteEvent & { session_name: string }) => void;
  onDelta?: (_content: string) => void;
  onFailed?: (_event: { message?: string; code?: string }) => void;
  onStarted?: () => void;
  onCronReminder?: (_message: string) => void;
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

interface SessionsApi {
  runs: {
    start: (n: string, m: string, fid?: string) => Promise<{ runId: string; eventsUrl: string; sessionName: string }>;
    cancel: (n: string, id: string) => Promise<void>;
  };
}

export function useAgentStream(
  api: { sessions: SessionsApi },
  callbacks: UseAgentStreamCallbacks = {},
) {
  const [socketState, setSocketState] = useState<SocketState>('disconnected');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState('');
  const [activeSession, setActiveSession] = useState('');
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  // 之前声明过 `error` 死状态,现在完全移除:错误统一走 callbacksRef.current.onFailed,
  // 单一通知路径,不会有"error state 实际从来没被 set"的混乱。
  const [tokenUsage, setTokenUsage] = useState<TokenUsage>(EMPTY_TOKEN_USAGE);
  const [modelContextWindow, setModelContextWindow] = useState(0);

  const sourceRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string>('');
  const sessionRef = useRef<string>('');
  // 同步 in-flight 守卫:在 sendMessage 入口立刻置 true,直到 setIsRunning(false)
  // 之前的窗口内拒绝并发 sendMessage(避免双击/连点导致的后端开多个 run)。
  // setIsRunning 是异步更新,React 18 批处理下同一 render 内多次 sendMessage
  // 都会通过 isRunning 守卫,所以必须用 ref 同步翻转。
  const startingRef = useRef(false);
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
  // C5 修复:每次 sendMessage 自增,闭包 es 内对比。保证旧 es 的延迟事件不会归到新 run。
  const generationRef = useRef(0);
  // C4 修复:累积 assistant 文本流。onCompleted 时若 final_content 为空,fallback 到此处累积,
  // 避免"流式看着有内容,完成时清空"的丢消息 bug。
  const streamingAccumulatorRef = useRef('');
  // H26 修复:把 callbacks 包成 ref,listener 内读 ref,避免 useCallback dep 过期。
  // 每次渲染都同步一次,listener 始终能拿到最新的 callbacks。
  const callbacksRef = useRef<UseAgentStreamCallbacks>(callbacks);
  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  const closeStream = useCallback(() => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }, []);

  const resetStream = useCallback(() => {
    // Mark the stream as completed BEFORE closing so the EventSource's
    // 'error' listener (which fires on close) does not show a misleading
    // 'Connection lost' toast when the caller is just resetting state
    // (e.g. session switch, new run). sendMessage clears the ref again
    // immediately after to start the new run with a fresh ref.
    completedRef.current = true;
    closeStream();
    setTurns([]);
    setRunStatus(null);
    setIsRunning(false);
    setActiveRunId('');
    setActiveSession('');
    setTokenUsage(EMPTY_TOKEN_USAGE);
    setModelContextWindow(0);
    runIdRef.current = '';
    sessionRef.current = '';
  }, [closeStream]);

  // Cleanup on unmount
  useEffect(() => {
    return () => closeStream();
  }, [closeStream]);

  // isRunning 翻 false 时清同步守卫;sendMessage 入口先翻 true,所有终态分支
  // 都会 setIsRunning(false) → 本 effect 清 startingRef,允许下次再发。
  useEffect(() => {
    if (!isRunning) {
      startingRef.current = false;
    }
  }, [isRunning]);

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
      const session = sessionName?.trim() || 'default';
      if (!message.trim()) return;
      // 同步守卫:防止连点/双击/键盘事件竞态导致同 render 内多次 sendMessage 都通过 isRunning 检查。
      if (startingRef.current) return;
      startingRef.current = true;
      // C5 修复:每次 sendMessage 自增 generation。闭包 es 内对比,
      // 旧 es 的延迟事件不会归到新 run。
      const myGeneration = ++generationRef.current;
      // C4 修复:重置流式累积器,准备接收新一轮的 deltas。
      streamingAccumulatorRef.current = '';
      // H26 修复:listener 内通过 callbacksRef.current 读最新 callbacks,
      // 这里不需要局部变量。
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
        const res = await api.sessions.runs.start(session, message, fileId);
        runIdRef.current = res.runId;
        sessionRef.current = session;
        setActiveRunId(res.runId);
        setActiveSession(session);

        setSocketState('connecting');
        const es = new EventSource(res.eventsUrl);
        sourceRef.current = es;
        es.addEventListener('open', () => {
          if (myGeneration !== generationRef.current) return;
          setSocketState('connected');
        });

        es.addEventListener('session_meta', (e: MessageEvent) => {
          if (myGeneration !== generationRef.current) return;
          try {
            const data = JSON.parse(e.data) as { type: string; payload?: Record<string, unknown> };
            callbacksRef.current.onSessionMeta?.(data.payload ?? {});
          } catch { /* ignore */ }
        });

        es.addEventListener('event_msg', (e: MessageEvent) => {
          if (myGeneration !== generationRef.current) return;
          try {
            const data = JSON.parse(e.data) as { type: string; payload?: Record<string, unknown> };
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
              callbacksRef.current.onStarted?.();
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
              // C4 修复:final_content 为空时,fallback 到流式累积器,避免"流式看到文字、完成时清空"。
              const finalFromPayload = typeof payload.final_content === 'string' ? payload.final_content : '';
              const finalContent = finalFromPayload || streamingAccumulatorRef.current;
              streamingAccumulatorRef.current = '';
              callbacksRef.current.onCompleted?.({
                type: 'task_complete',
                turn_id: payload.turn_id || '',
                status: (payload.status || 'completed') as TaskCompleteEvent['status'],
                ended_at: Date.now() / 1000,
                final_content: finalContent,
                session_name: sessionRef.current,
              });
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
              streamingAccumulatorRef.current = '';
              callbacksRef.current.onFailed?.({ message: payload.message, code: payload.code });
            } else if (payload.type === 'cron_reminder') {
              // Cron reminders are system-level, not part of any turn's content.
              // Surface as a sticky info toast so the user can see them
              // without polluting the message list.
              const name = payload.message || 'Cron job';
              callbacksRef.current.onCronReminder?.(name);
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
          if (myGeneration !== generationRef.current) return;
          try {
            const data = JSON.parse(e.data) as { type: string; payload?: Record<string, unknown> };
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
            // H29 修复:优先用 payload.turn_id(后端已注入)定位 turn,fallback 到最后一个。
            // 之前只用最后一个 turn 会导致跨 turn race 时 deltas 粘到上一个 turn。
            const payloadTurnId = (payload as { turn_id?: string }).turn_id;
            const currentTurn = turnsRef.current[turnsRef.current.length - 1];
            const turnId = payloadTurnId || currentTurn?.turnId;

            if (payload.type === 'message' && payload.role === 'assistant') {
              const content = payload.content || '';
              const isFinal = payload.delta === false;
              if (content && !isFinal) {
                // C4 修复:累积 streaming,供 task_complete 时 fallback。
                streamingAccumulatorRef.current += content;
                callbacksRef.current.onDelta?.(content);
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
                      // C4 修复:空 final 帧不覆盖累积的流式内容。
                      if (isFinal && content === '') return t;
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
          // C5 修复:用 generation 替代 sourceRef !== es,语义更清晰。
          if (myGeneration !== generationRef.current) return;
          // EventSource fires 'error' on any disconnect, including the
          // normal close that follows a received 'done' event. Only treat
          // it as a failure if we never saw a terminal event for this run.
          if (!completedRef.current) {
            setSocketState('error');
            setIsRunning(false);
            streamingAccumulatorRef.current = '';
            // Surface to the caller so a sticky error toast appears.
            // Use a distinct message from agent-emitted errors so the user
            // can tell the stream died vs. the agent returned an error.
            callbacksRef.current.onFailed?.({ message: 'Connection lost', code: 'stream_disconnected' });
          }
        });

        es.addEventListener('done', () => {
          // Same generation-based stale guard as the 'error' listener.
          if (myGeneration !== generationRef.current) return;
          es.close();
          setSocketState('disconnected');
        });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'failed to start run';
        setIsRunning(false);
        setRunStatus('failed');
        streamingAccumulatorRef.current = '';
        // Surface to caller exactly once.
        callbacksRef.current.onFailed?.({ message: msg });
      }
    },
    // H26 修复:不再依赖 callbacks 本身(改用 callbacksRef),sendMessage 不再每次重建。
    [api, appendItem, resetStream, upsertItem],
  );

  const stopRun = useCallback(async () => {
    if (!runIdRef.current || !sessionRef.current) return;
    try {
      await api.sessions.runs.cancel(sessionRef.current, runIdRef.current);
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
    activeSession,
    runStatus,
    tokenUsage,
    modelContextWindow,
    sendMessage,
    stopRun,
    resetStream,
  };
}
