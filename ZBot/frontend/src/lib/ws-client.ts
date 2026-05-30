/**
 * ws-client.ts — WebSocket connection management
 * Extracted from useWebSocket.js. Handles connect/disconnect/send/event routing.
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
 * ZBot WebSocket client.
 *
 * Usage:
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
   * Connect to the WebSocket server.
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
   * Disconnect from the WebSocket server.
   */
  disconnect(): void {
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
  }

  /**
   * Send a command to the WebSocket server.
   * @param {object} command — JSON-serializable command object
   */
  send(command: WebSocketCommand): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(command));
    }
  }

  /**
   * Register an event listener.
   * @param {string} eventType — e.g. "run.started"
   * @param {Function} handler — (event) => void
   */
  on(eventType: string, handler: AgentEventHandler): void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set());
    }
    this.listeners.get(eventType)?.add(handler);
  }

  /**
   * Remove an event listener.
   * @param {string} eventType
   * @param {Function} handler
   */
  off(eventType: string, handler: AgentEventHandler): void {
    this.listeners.get(eventType)?.delete(handler);
  }

  /**
   * Internal: dispatch event to registered listeners.
   * @param {object} event
   */
  private _dispatch(event: AgentEvent): void {
    const eventType = event.type || 'unknown';
    const handlers = this.listeners.get(eventType);
    if (handlers) {
      handlers.forEach((handler) => handler(event));
    }
    // Also dispatch on '*' for wildcard listeners
    const wildcardHandlers = this.listeners.get('*');
    if (wildcardHandlers) {
      wildcardHandlers.forEach((handler) => handler(event));
    }
  }
}
