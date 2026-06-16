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
 *
 * ZBot 改: LiveStatus 状态机集成, 引入 'streaming' 阶段避免
 * "助手开始吐字就 close()" 误锁工具事件, 详见 liveStatusMachine.ts。
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { LiveStatusMachine } from './liveStatusMachine';
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
  // ZBot 改: LiveStatus 状态事件字段 (后端 _to_status / _to_tool_hint 注入)
  phase?: 'thinking' | 'tool' | 'finalizing' | 'streaming' | string;
  tool_name?: string;
  text?: string;
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
  const [tokenUsage, setTokenUsage] = useState<TokenUsage>(EMPTY_TOKEN_USAGE);
  const [modelContextWindow, setModelContextWindow] = useState(0);
  // ZBot 改: LiveStatus 状态机抽到独立 class, 用 useSyncExternalStore 同步 phase + toolName
  const liveStatusMachineRef = useRef<LiveStatusMachine | null>(null);
  if (liveStatusMachineRef.current === null) liveStatusMachineRef.current = new LiveStatusMachine();
  const liveStatus = useSyncExternalStore(
    liveStatusMachineRef.current.subscribe.bind(liveStatusMachineRef.current),
    () => liveStatusMachineRef.current!.snapshot(),
  );

  const sourceRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string>('');
  const sessionRef = useRef<string>('');
  // 同步 in-flight 守卫: 在 sendMessage 入口立刻置 true, 直到 setIsRunning(false)
  const startingRef = useRef(false);
  const completedRef = useRef(false);
  // Mirror `turns` into a ref so the response_item handler can read the latest
  // value without re-registering the handler.
  const turnsRef = useRef<Turn[]>([]);
  useEffect(() => {
    turnsRef.current = turns;
  }, [turns]);
  // C5 修复: 每次 sendMessage 自增, 闭包 es 内对比。保证旧 es 的延迟事件不会归到新 run。
  const generationRef = useRef(0);
  // C4 修复: 累积 assistant 文本流。onCompleted 时若 final_content 为空, fallback 到此处累积。
  const streamingAccumulatorRef = useRef('');
  // H26 修复: 把 callbacks 包成 ref, listener 内读 ref, 避免 useCallback dep 过期。
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

  // ZBot 改: resetStream 只重置"正在进行的 run"的 in-flight 状态 (SSE / status),
  // 不再清空 turns —— turns 是当前会话的"对话历史", 包括已完成的所有 turn,
  // 必须保留, 否则:
  //   (1) 用户在同会话发第二条消息 -> 第一条消息的回答从 turns 里消失
  //   (2) 切换会话后切回来 -> 历史里也看不到之前的回答
  // turns 的清空专门由 clearTurns 负责, 外部 (切会话时) 调用。
  const resetStream = useCallback(() => {
    liveStatusMachineRef.current?.reset();
    completedRef.current = true;
    closeStream();
    // 注意: 不再 setTurns([]) —— 历史 turn 保留
    setRunStatus(null);
    setIsRunning(false);
    setActiveRunId('');
    setActiveSession('');
    setTokenUsage(EMPTY_TOKEN_USAGE);
    setModelContextWindow(0);
    runIdRef.current = '';
    sessionRef.current = '';
  }, [closeStream]);

  // ZBot 改: 显式清空 turns, 仅在切换会话时调用。resetStream 不再做这件事。
  const clearTurns = useCallback(() => {
    setTurns([]);
  }, []);

  // ZBot 改: 用历史 turns 替换当前 turns (历史会话加载时由 ChatPage 调用)。
  // 与 clearTurns 不同, 这个保留所有 turn, 只是替换数据。
  const setHistoryTurns = useCallback((historyTurns: Turn[]) => {
    setTurns(historyTurns);
  }, []);

  useEffect(() => {
    return () => closeStream();
  }, [closeStream]);

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
      // 同步守卫: 防止连点/双击/键盘事件竞态
      if (startingRef.current) return;
      startingRef.current = true;
      const myGeneration = ++generationRef.current;
      streamingAccumulatorRef.current = '';

      resetStream();
      completedRef.current = false;
      setRunStatus('queued');
      setIsRunning(true);
      // ZBot 改: LiveStatus 状态机打开, 立即进入 thinking, 不等后端 status 事件
      liveStatusMachineRef.current?.open();

      // ZBot 改: 在发起 POST 之前先为"本轮 turn"占位 + 把用户消息写进 turn.items,
      // 这样用户消息和助手回答都在同一个 turn 里, MessageList 只渲染 turns 也能
      // 完整看到一轮对话 (用户问 + 助手答)。同时 turn.turnId 用本地占位 id,
      // task_started 来了之后 setTurns 会按 turnId 合并 / 替换 (见 line 215-219)。
      const placeholderTurnId = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      setTurns((prev) => [
        ...prev,
        {
          turnId: placeholderTurnId,
          status: 'running',
          items: [{ kind: 'user_message', content: message } as TurnItem],
          startedAt: Date.now(),
        },
      ]);

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
              // ZBot 改: 幂等 open - 如果锁已开(例如上一轮 streaming 还没结束),
              // 不要强行重置回 thinking, 否则工具事件会被状态机拒掉。
              liveStatusMachineRef.current?.openIfClosed();
              const turnId = payload.turn_id || `t-${Date.now()}`;
              const ctxWindow = Number(payload.model_context_window || 0);
              setModelContextWindow(ctxWindow);
              setTurns((prev) => {
                // 1) 真实 turnId 已存在 (重连 / 重复 event): 标记 running
                const realTurnIdx = prev.findIndex((t) => t.turnId === turnId);
                if (realTurnIdx >= 0) {
                  return prev.map((t) => (t.turnId === turnId
                    ? { ...t, status: 'running', modelContextWindow: ctxWindow || t.modelContextWindow }
                    : t));
                }
                // 2) 找到本地占位 turn (我们 sendMessage 时提前插入的, turnId 是
                //    "local-...", 里面有 user_message 项): 把占位的 turnId 替换成
                //    真实 turnId, 保留 user_message。
                const placeholderIdx = prev.findIndex(
                  (t) => t.turnId.startsWith('local-') && t.status === 'running'
                );
                if (placeholderIdx >= 0) {
                  return prev.map((t, i) => i === placeholderIdx
                    ? { ...t, turnId, modelContextWindow: ctxWindow || t.modelContextWindow }
                    : t);
                }
                // 3) 没有占位 (异常路径 / race): 全新建一个空 turn
                return [
                  ...prev,
                  { turnId, status: 'running', items: [], startedAt: Date.now(), modelContextWindow: ctxWindow },
                ];
              });
              setIsRunning(true);
              callbacksRef.current.onStarted?.();
            } else if (payload.type === 'task_complete') {
              // 终态: 关 LiveStatus 锁
              liveStatusMachineRef.current?.close();
              const turnId = payload.turn_id || '';
              const nextStatus: Turn['status'] =
                payload.status === 'failed' ? 'failed'
                : payload.status === 'cancelled' ? 'cancelled'
                : 'completed';
              const finalFromPayload = typeof payload.final_content === 'string' ? payload.final_content : '';
              const finalContent = finalFromPayload || streamingAccumulatorRef.current;
              streamingAccumulatorRef.current = '';
              if (turnId) {
                // ZBot 改: task_complete 时把 finalContent 作为 message item 写入 turn
                //   - 如果 turn 已有 message item (旧逻辑遗留), 覆盖内容
                //   - 否则在 items 末尾追加一个 message item
                //   - cancelled / failed 时 finalContent 通常为空, 不追加
                // ZBot 改: 顺手把任何仍处于 "running" 状态的 tool_call 收尾 —
                //   function_call_output 没到 / call_id 不匹配 / 工具超时 等场景
                //   会让 tool_call 永远卡在 running, 既然任务已结束, 这些孤儿
                //   必须标 cancelled, 否则用户看到 "7 个工具 1 个永远运行中"。
                setTurns((prev) =>
                  prev.map((t) => {
                    if (t.turnId !== turnId) return t;
                    const now = Date.now();
                    const reconciledItems = t.items.map((it) =>
                      it.kind === 'tool_call' && it.status === 'running'
                        ? { ...it, status: 'failed' as const, output: it.output || '[未返回结果 — 任务已结束]', endedAt: now }
                        : it,
                    );
                    const baseTurn = { ...t, status: nextStatus, endedAt: now, items: reconciledItems };
                    if (!finalContent) {
                      return baseTurn;
                    }
                    const messageIdx = baseTurn.items.findIndex((it) => it.kind === 'message');
                    const messageItem = { kind: 'message' as const, content: finalContent };
                    if (messageIdx >= 0) {
                      const items = baseTurn.items.slice();
                      items[messageIdx] = messageItem;
                      return { ...baseTurn, items };
                    }
                    return { ...baseTurn, items: [...baseTurn.items, messageItem] };
                  }),
                );
              }
              setIsRunning(false);
              setRunStatus(payload.status || 'completed');
              completedRef.current = true;
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
              // 终态: 关 LiveStatus 锁
              liveStatusMachineRef.current?.close();
              streamingAccumulatorRef.current = '';
              callbacksRef.current.onFailed?.({ message: payload.message, code: payload.code });
            } else if (payload.type === 'cron_reminder') {
              const name = payload.message || 'Cron job';
              callbacksRef.current.onCronReminder?.(name);
            } else if (payload.type === 'status') {
              // ZBot 改: 走状态机, 含 'streaming' 阶段
              const phase = String(payload.phase || 'thinking');
              if (phase === 'thinking' || phase === 'finalizing' || phase === 'tool' || phase === 'streaming') {
                liveStatusMachineRef.current?.apply(phase as 'thinking' | 'tool' | 'finalizing' | 'streaming');
              }
            } else if (payload.type === 'tool_hint') {
              liveStatusMachineRef.current?.apply('tool', String(payload.tool_name || payload.text || ''));
            } else if (payload.type === 'token_count') {
              setTokenUsage({
                inputTokens: Number(payload.input_tokens || 0),
                outputTokens: Number(payload.output_tokens || 0),
                cachedTokens: Number(payload.cached_tokens || 0),
              });
            }
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
            const payloadTurnId = (payload as { turn_id?: string }).turn_id;
            const currentTurn = turnsRef.current[turnsRef.current.length - 1];
            const turnId = payloadTurnId || currentTurn?.turnId;

            if (payload.type === 'message' && payload.role === 'assistant') {
              const content = payload.content || '';
              if (content) {
                // ZBot 改: 中间文字(工具间吐出的 token) 不再写入 turn.items
                // 原因: spec 要求 "过程 vs 结果 严格分离", 中间 token 只作为
                //       状态卡片文案切换的触发器, 不会单独渲染为白文字.
                //       真正的 final answer 在 task_complete 时由 final_content
                //       (或 streamingAccumulatorRef fallback) 一次性写入 turn.
                streamingAccumulatorRef.current += content;
                callbacksRef.current.onDelta?.(content);
                // ZBot 改: 守卫 — 仅在当前 phase==='thinking' 时才切到 'streaming'。
                // 工具在飞时 (phase==='tool') 不切, 避免「正在调用 XX 工具」闪烁成
                // 「正在分析结果」。 finalizing/tool 阶段也保持锁定状态。
                if (liveStatusMachineRef.current?.snapshot().phase === 'thinking') {
                  liveStatusMachineRef.current?.apply('streaming');
                }
              }
            } else if (payload.type === 'function_call') {
              liveStatusMachineRef.current?.apply('tool', String(payload.name || ''));
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
              // ZBot 改: 不在这里 apply('finalizing')。
              // 之前每个工具返回都强切 finalizing, 导致多工具场景下「正在整理结果」闪烁多次。
              // 统一由后端 status 事件在「最后一次 model.completed (无 tool_calls)」时驱动。
              if (turnId && payload.call_id) {
                // ZBot 改: 区分 done vs failed — 后端 _to_function_call_output_error
                // 会发 status='failed', 这里读出来更新到 tool_call item。
                const isFailed = (payload as { status?: string }).status === 'failed';
                upsertItem(
                  turnId,
                  (it) => it.kind === 'tool_call' && it.callId === payload.call_id,
                  (it) =>
                    it.kind === 'tool_call'
                      ? {
                          ...it,
                          status: isFailed ? 'failed' : 'done',
                          output: payload.output ?? '',
                          endedAt: Date.now(),
                        }
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
          if (myGeneration !== generationRef.current) return;
          if (!completedRef.current) {
            setSocketState('error');
            setIsRunning(false);
            streamingAccumulatorRef.current = '';
            // 终态: 关 LiveStatus 锁
            liveStatusMachineRef.current?.close();
            callbacksRef.current.onFailed?.({ message: 'Connection lost', code: 'stream_disconnected' });
          }
        });

        es.addEventListener('done', () => {
          if (myGeneration !== generationRef.current) return;
          es.close();
          setSocketState('disconnected');
        });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'failed to start run';
        setIsRunning(false);
        setRunStatus('failed');
        // 终态: 关 LiveStatus 锁
        liveStatusMachineRef.current?.close();
        streamingAccumulatorRef.current = '';
        callbacksRef.current.onFailed?.({ message: msg });
      }
    },
    [api, appendItem, resetStream, upsertItem],
  );

  const stopRun = useCallback(async () => {
    if (!runIdRef.current || !sessionRef.current) return;
    try {
      await api.sessions.runs.cancel(sessionRef.current, runIdRef.current);
      setRunStatus('cancelled');
    } catch { /* ignore: best effort */ }
    setIsRunning(false);
    // 终态: 关 LiveStatus 锁
    liveStatusMachineRef.current?.close();
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
    livePhase: liveStatus.phase,
    liveToolName: liveStatus.toolName,
    sendMessage,
    stopRun,
    resetStream,
    // ZBot 改: 切会话时显式清空 turns, 取代之前 resetStream 隐式清空。
    clearTurns,
    // ZBot 改: 把 ChatMessage[] 历史加载成 Turn[], 替换当前 turns。
    setHistoryTurns,
  };
}
