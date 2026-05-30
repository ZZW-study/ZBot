/**
 * useWebSocket.js — WebSocket 连接管理 Hook
 * 负责：建立连接、接收事件、发送消息、重连
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AgentEvent, SocketState } from '../types';

// 常量：最多保留 80 个事件
const MAX_EVENTS = 80;

// { onCompleted, onDelta, onFailed, onStarted } = {} — 解构第二个参数
// = {} — 默认值：如果调用时不传第二个参数，用空对象（避免报错）
interface UseWebSocketCallbacks {
  onCompleted?: (_event: AgentEvent) => void;
  onDelta?: (_event: AgentEvent) => void;
  onFailed?: (_event: AgentEvent) => void;
  onStarted?: (_event: AgentEvent) => void;
}

export function useWebSocket(
  wsUrl: string,
  { onCompleted, onDelta, onFailed, onStarted }: UseWebSocketCallbacks = {},
) {

  // useRef — 创建一个"可变引用"，修改它不会触发重新渲染
  // 和 useState 的区别：useState 修改值会触发重新渲染，useRef 不会
  // 用途：保存 WebSocket 实例，需要在多个函数中访问
  // socketRef.current — 实际的值（初始为 null）
  const socketRef = useRef<WebSocket | null>(null);

  // WebSocket 连接状态
  const [socketState, setSocketState] = useState<SocketState>('connecting');

  // 事件列表（最新的在前面）
  const [events, setEvents] = useState<AgentEvent[]>([]);

  // 是否正在运行任务
  const [isRunning, setIsRunning] = useState(false);

  // 当前运行 ID
  const [activeRunId, setActiveRunId] = useState('');

  // 连接尝试次数（改变它会触发 useEffect 重新连接）
  const [connectionAttempt, setConnectionAttempt] = useState(0);


  // 添加事件到列表
  const appendEvent = useCallback((event: AgentEvent) => {
    // [event, ...prev] — 新事件放在数组最前面（最新的在前）
    // .slice(0, MAX_EVENTS) — 只保留前 80 个（防止列表无限增长）
    setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS));

    // 更新当前运行 ID
    // 'control' 是后端定义的特殊 run_id，表示控制消息（非实际运行），不需要显示
    // && 逻辑与：两个条件都为 true 才执行
    if (event.run_id && event.run_id !== 'control') setActiveRunId(event.run_id);
  }, []);


  // 处理从后端收到的事件
  // useCallback 的依赖项数组 [appendEvent, onCompleted, ...]：
  //   这些函数中任何一个变化，handleAgentEvent 就重新创建
  //   为什么重要？因为 handleAgentEvent 是下面 useEffect 的依赖项
  //   如果它重新创建 → useEffect 的依赖项变化 → 清理函数关闭旧 WebSocket → 重新连接
  //   所以用 useCallback 缓存，避免不必要的重连
  const handleAgentEvent = useCallback(
    (event: AgentEvent) => {
      // 更新运行 ID
      if (event.run_id && event.run_id !== 'control') setActiveRunId(event.run_id);

      // assistant.delta — 流式文本片段（逐字显示用）
      // ?. 可选链：onDelta 可能不存在（父组件没传），不报错
      if (event.type === 'assistant.delta') {
        onDelta?.(event);  // 调用回调（如果存在）
        return;            // 处理完直接返回，不执行后面的代码
      }

      // 把事件加入列表（除了 delta，其他事件都显示在事件面板）
      appendEvent(event);

      // turn.started — 一轮对话开始
      if (event.type === 'turn.started') {
        setIsRunning(true);
        onStarted?.(event);
        return;
      }

      // turn.completed — 一轮对话完成
      if (event.type === 'turn.completed') {
        setIsRunning(false);
        onCompleted?.(event);
        return;
      }

      // run.completed — 整个运行完成
      if (event.type === 'run.completed') {
        setIsRunning(false);
        return;
      }

      // run.failed 或 run.cancelled — 运行失败或被取消
      // || 逻辑或：任一条件为 true
      if (event.type === 'run.failed' || event.type === 'run.cancelled') {
        setIsRunning(false);
        onFailed?.(event);
      }
    },
    [appendEvent, onCompleted, onDelta, onFailed, onStarted],
  );


  // useEffect — 建立 WebSocket 连接
  // 依赖项包含 connectionAttempt：当 connectionAttempt 变化时，会重新执行（实现重连）
  useEffect(() => {
    // new WebSocket(url) — 创建 WebSocket 连接
    const socket = new WebSocket(wsUrl);

    // 把 socket 实例保存到 ref（跨函数访问）
    socketRef.current = socket;

    // addEventListener — 监听事件
    // 'open' — 连接建立成功
    socket.addEventListener('open', () => setSocketState('connected'));

    // 'close' — 连接关闭
    socket.addEventListener('close', () => {
      setSocketState('disconnected');
      setIsRunning(false);
    });

    // 'error' — 连接出错
    socket.addEventListener('error', () => setSocketState('error'));

    // 'message' — 收到消息
    // messageEvent.data — 消息内容（字符串）
    // JSON.parse() — 把 JSON 字符串转为 JS 对象
    socket.addEventListener('message', (messageEvent: MessageEvent<string>) => {
      try {
        handleAgentEvent(JSON.parse(messageEvent.data));
      } catch {
        // 如果 JSON 解析失败，记录一个错误事件
        // new Date().toISOString() — 当前时间的 ISO 格式字符串
        appendEvent({
          type: 'client.error',
          message: '收到无法解析的 WebSocket 消息。',
          created_at: new Date().toISOString(),
        });
      }
    });

    // return 的函数是"清理函数"，组件卸载或依赖项变化时执行
    // 关闭旧的 WebSocket 连接
    return () => socket.close();
  }, [appendEvent, connectionAttempt, handleAgentEvent, wsUrl]);


  // 发送消息给后端
  const sendMessage = useCallback(
    (message: string, sessionName: string) => {
      // 安全检查：socket 不存在、未连接、正在运行时，不发送
      if (!socketRef.current || socketState !== 'connected' || isRunning) return;

      // 清空事件列表（新对话开始）
      setEvents([]);

      // socket.send() — 发送数据
      // JSON.stringify() — 把 JS 对象转为 JSON 字符串
      socketRef.current.send(
        JSON.stringify({
          type: 'run.start',
          message,
          session_name: sessionName || 'default',
        }),
      );
    },
    [socketState, isRunning],  // 依赖项：这两个值变化时重新创建
  );


  // 停止运行
  const stopRun = useCallback(() => {
    if (!socketRef.current || socketState !== 'connected') return;
    socketRef.current.send(JSON.stringify({ type: 'run.cancel' }));
  }, [socketState]);


  // 重新连接
  // 实现方式：把 connectionAttempt +1，触发 useEffect 重新执行
  // (v) => v + 1 — 函数式更新，v 是当前值
  const reconnect = useCallback(() => {
    setSocketState('connecting');
    setConnectionAttempt((v) => v + 1);
  }, []);


  // 返回所有状态和函数
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
