/**
 * api.js — Unified REST API client
 * Centralizes fetch calls, base URL, error handling, and JSON parsing.
 */

/**
 * Custom API error with HTTP status and backend error code.
 */
import type { ConfigDefaults, ConfigPatch, ConfigResponse, SessionDetailResponse, SessionSummary } from '../types';

interface ApiErrorBody {
  detail?: string;
  message?: string;
  code?: string;
}

interface ConfigStatusResponse {
  exists: boolean;
  configured: boolean;
  provider?: string;
  reason?: string;
}

interface SessionsListResponse {
  sessions: SessionSummary[];
}

interface OkResponse {
  ok?: boolean;
  name?: string;
  error?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code = '') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/**
 * Create an API client bound to a specific base URL.
 *
 * @param {string} apiBase — e.g. "http://localhost:8000"
 * @returns {object} — { sessions, config, multimodal }
 */
export function createApiClient(apiBase: string) {
  async function request<T>(path: string, options: globalThis.RequestInit = {}): Promise<T> {
    const url = `${apiBase}${path}`;
    const isFormData = options.body instanceof FormData;
    const headers = isFormData
      ? { ...options.headers }
      : { 'Content-Type': 'application/json', ...options.headers };

    const res = await fetch(url, { ...options, headers });

    if (!res.ok) {
      const body = await res.json().catch(() => ({})) as ApiErrorBody;
      throw new ApiError(
        body.detail || body.message || res.statusText,
        res.status,
        body.code,
      );
    }

    return res.json() as Promise<T>;
  }

  return {
    sessions: {
      list: () => request<SessionsListResponse>('/api/sessions'),
      get: (name: string) => request<SessionDetailResponse>(`/api/sessions/${encodeURIComponent(name)}`),
      delete: (name: string) => request<OkResponse>(`/api/sessions/${encodeURIComponent(name)}`, { method: 'DELETE' }),
      create: (name: string) => request<OkResponse>('/api/sessions', {
        method: 'POST',
        body: JSON.stringify({ name }),
      }),
      rename: (oldName: string, newName: string) => request<OkResponse>(`/api/sessions/${encodeURIComponent(oldName)}`, {
        method: 'PUT',
        body: JSON.stringify({ name: newName }),
      }),
    },
    config: {
      status: () => request<ConfigStatusResponse>('/api/config/status'),
      get: () => request<ConfigResponse>('/api/config'),
      defaults: () => request<ConfigDefaults>('/api/config/defaults'),
      save: (patch: ConfigPatch) => request<ConfigResponse>('/api/config', {
        method: 'PUT',
        body: JSON.stringify(patch),
      }),
    },
    multimodal: {
      ask: (files: File[], question: string, sessionName: string) => {
        const form = new FormData();
        files.forEach((f) => form.append('files', f));
        form.append('question', question);
        form.append('session_name', sessionName);
        return request<OkResponse>('/api/multimodal/ask', { method: 'POST', body: form });
      },
    },
  };
}
