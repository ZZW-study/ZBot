import type { Dispatch, SetStateAction } from 'react';

export type SocketState = 'connecting' | 'connected' | 'disconnected' | 'error';

export type MessageRole = 'user' | 'assistant';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp?: string;
  tools_used?: string[];
}

export interface SessionSummary {
  name: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
}

export interface SessionDetailResponse {
  name: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
  messages: ChatMessage[];
}

export interface ConfigDefaults {
  [provider: string]: {
    api_base?: string;
    model_placeholder?: string;
  } | undefined;
}

export interface ProviderConfig {
  apiKey?: string;
  apiBase?: string;
}

export interface ConfigResponse {
  model: string;
  provider: string;
  resolvedProvider?: string | null;
  configured?: boolean;
  reason?: string;
  workspace?: string;
  maxTokens?: number;
  temperature?: number;
  reasoningEffort?: string | null;
  hasKey?: boolean;
  providers?: Record<string, ProviderConfig | undefined>;
}

export interface ConfigPatch {
  model?: string;
  provider?: string;
  workspace?: string;
  maxTokens?: number;
  temperature?: number;
  reasoningEffort?: string | null;
  providers?: Record<string, ProviderConfig>;
}

export type StringSetter = Dispatch<SetStateAction<string>>;

// ---------------------------------------------------------------------------
// 通用 token / run / toast / 附件 类型
// ---------------------------------------------------------------------------

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  cachedTokens: number;
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface TaskCompleteEvent {
  type: 'task_complete';
  turn_id?: string;
  status: RunStatus;
  ended_at: number;
  final_content?: string;
  // useAgentStream 内部由 task_complete + session_meta 合并而成,带上当前 session 名。
  session_name?: string;
}

export interface AttachedFile {
  file: File;
  uploading: boolean;
  error: string | null;
  fileId?: string;
}

export type ToastKind = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: string;
  kind: ToastKind;
  message: string;
  detail?: string;
  sticky?: boolean;
}

// ---------------------------------------------------------------------------
// Turn / TurnItem — 单个 agent run 内一组"助手输出单元"的视图。
// 供 useAgentStream 累积事件后用,Message 组件按 turn 渲染。
// 当前前端用 SSE + MessageList 走 ChatMessage 路径;
// 这套类型是给将来的"按 turn 渲染"留的接口。
// ---------------------------------------------------------------------------

export type TurnStatus = 'running' | 'completed' | 'failed' | 'cancelled';

export interface MessageTurnItem {
  kind: 'message';
  content: string;
}

export interface ReasoningTurnItem {
  kind: 'reasoning';
  summary: string;
}

export interface ToolCallTurnItem {
  kind: 'tool_call';
  callId: string;
  name: string;
  arguments: Record<string, unknown>;
  status: 'running' | 'done' | 'failed';
  startedAt?: number;
  endedAt?: number;
  output?: string;
}

export interface ErrorTurnItem {
  kind: 'error';
  message: string;
  code?: string;
}

export type TurnItem = MessageTurnItem | ReasoningTurnItem | ToolCallTurnItem | ErrorTurnItem;

export interface Turn {
  turnId: string;
  status: TurnStatus;
  items: TurnItem[];
  startedAt?: number;
  endedAt?: number;
  modelContextWindow?: number;
}
