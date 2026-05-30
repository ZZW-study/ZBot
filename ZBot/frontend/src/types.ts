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

export interface AgentEvent {
  type?: string;
  run_id?: string;
  session_name?: string;
  message?: string;
  agent_label?: string | null;
  payload?: Record<string, unknown>;
  created_at?: string;
}

export interface SessionSummary {
  name: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
  [key: string]: unknown;
}

export interface SessionDetailResponse {
  name: string;
  created_at?: string;
  updated_at?: string;
  message_count: number;
  messages: ChatMessage[];
}

export interface ConfigDefaults {
  [provider: string]: {
    api_base?: string;
    model_placeholder?: string;
    [key: string]: unknown;
  } | undefined;
}

export interface ProviderConfig {
  apiKey?: string;
  apiBase?: string;
}

export interface ConfigResponse {
  model?: string;
  provider?: string;
  resolvedProvider?: string;
  providers?: Record<string, ProviderConfig | undefined>;
}

export interface ConfigPatch {
  model: string;
  provider: string;
  providers: Record<string, ProviderConfig>;
}

export type StringSetter = Dispatch<SetStateAction<string>>;
