/**
 * ws-client.ts — WebSocket 连接管理
 * 从 useWebSocket.js 中抽取而来。处理连接/断开/发送/事件路由。
 */

import type { AgentEvent, SocketState } from '../types';

export interface RunStartCommand {
  type: 'run.start';
  message: string;
  session_name: string;
}

export interface RunCancelCommand {
  type: 'run.cancel';
}

export type WebSocketCommand = RunStartCommand | RunCancelCommand | Record<string, unknown>;
export type AgentEventHandler = (_event: AgentEvent) => void;
export type SocketStateHandler = (_state: SocketState) => void;

/**
 * ZBot WebSocket 客户端。
 *
 * 用法:
 *   const ws = new ZBotWebSocket(url);
 *   ws.connect();
 *   ws.on('run.started', (event) => { ... });
 *   ws.send({ type: 'run.start', message: '...', session_name: '...' });
 *   ws.disconnect();
 */
export class ZBotWebSocket {
  private readonly url: string;
  private socket: WebSocket | null;
  private readonly listeners: Map<string, Set<AgentEventHandler>>;
  onStateChange: SocketStateHandler | null;

  constructor(url: string) {
    this.url = url;
    this.socket = null;
    this.listeners = new Map();
    this.onStateChange = null;
  }

  /**
   * 连接到 WebSocket 服务器。
   */
  connect(): void {
    this.socket = new WebSocket(this.url);

    this.socket.addEventListener('open', () => {
      this.onStateChange?.('connected');
    });

    this.socket.addEventListener('close', () => {
      this.onStateChange?.('disconnected');
    });

    this.socket.addEventListener('error', () => {
      this.onStateChange?.('error');
    });

    this.socket.addEventListener('message', (messageEvent: MessageEvent<string>) => {
      try {
        const event = JSON.parse(messageEvent.data) as AgentEvent;
        this._dispatch(event);
      } catch {
        this._dispatch({
          type: 'client.error',
          message: '收到无法解析的 WebSocket 消息。',
          created_at: new Date().toISOString(),
        });
      }
    });
  }

  /**
   * 断开与 WebSocket 服务器的连接。
   */
  disconnect(): void {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }

  /**
   * 向 WebSocket 服务器发送命令。
   * @param {object} command — 可序列化为 JSON 的命令对象
   */
  send(command: WebSocketCommand): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(command));
    }
  }

  /**
   * 注册一个事件监听器。
   * @param {string} eventType — 例如 "run.started"
   * @param {Function} handler — (event) => void
   */
  on(eventType: string, handler: AgentEventHandler): void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set());
    }
    this.listeners.get(eventType)?.add(handler);
  }

  /**
   * 移除一个事件监听器。
   * @param {string} eventType
   * @param {Function} handler
   */
  off(eventType: string, handler: AgentEventHandler): void {
    this.listeners.get(eventType)?.delete(handler);
  }

  /**
   * 内部方法:将事件分发给已注册的监听器。
   * @param {object} event
   */
  private _dispatch(event: AgentEvent): void {
    const eventType = event.type || 'unknown';
    const handlers = this.listeners.get(eventType);
    if (handlers) {
      handlers.forEach((handler) => handler(event));
    }
    // 同时分发给 '*' 通配符监听器
    const wildcardHandlers = this.listeners.get('*');
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => handler(event));
    }
  }
}
