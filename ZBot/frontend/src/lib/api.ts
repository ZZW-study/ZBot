/**
 * api.js — 统一的 REST API 客户端
 * 集中处理 fetch 请求、基础 URL、错误处理和 JSON 解析。
 */

/**
 * 自定义 API 错误,包含 HTTP 状态码和后端错误码。
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
  model?: string;
  provider?: string;
  reason?: string;
}

interface OkResponse {
  ok?: boolean;
  name?: string;
  error?: string;
  [key: string]: unknown;
}

interface StartRunResponse {
  runId: string;
  sessionName: string;
  status: string;
  createdAt: string;
  eventsUrl: string;
  statusUrl: string;
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
 * 创建一个绑定到指定基础 URL 的 API 客户端。
 *
 * @param {string} apiBase — 例如 "http://localhost:8000"
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

  /**
   * 一些 RESTful 端点返回 204 No Content(删除 / 取消成功等)。
   * 该辅助函数把 204 当作成功,返回 undefined;非 2xx 仍走 request 的错误分支。
   */
  async function requestVoid(path: string, options: globalThis.RequestInit = {}): Promise<void> {
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
    // 204 / 空 body 视为成功
  }

  return {
    sessions: {
      list: () => request<SessionSummary[]>('/api/sessions'),
      get: (name: string) => request<SessionDetailResponse>(`/api/sessions/${encodeURIComponent(name)}`),
      delete: (name: string) => requestVoid(`/api/sessions/${encodeURIComponent(name)}`, { method: 'DELETE' }),
      create: (name: string) => request<SessionDetailResponse>('/api/sessions', {
        method: 'POST',
        body: JSON.stringify({ name }),
      }),
      rename: (oldName: string, newName: string) => request<OkResponse>(`/api/sessions/${encodeURIComponent(oldName)}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: newName }),
      }),
      runs: {
        start: (sessionName: string, message: string, fileId?: string) => request<StartRunResponse>(
          `/api/sessions/${encodeURIComponent(sessionName)}/runs`,
          {
            method: 'POST',
            body: JSON.stringify({ message, ...(fileId ? { file_id: fileId } : {}) }),
          },
        ),
        cancel: (sessionName: string, runId: string) => requestVoid(
          `/api/sessions/${encodeURIComponent(sessionName)}/runs/${encodeURIComponent(runId)}`,
          { method: 'DELETE' },
        ),
      },
    },
    files: {
      // ZBot 改:model 可选,后端在多模态能力不足时返回 400,前端 toast 提示。
      upload: (files: File[], model?: string) => {
        const form = new FormData();
        files.forEach((f) => form.append('files', f));
        if (model) form.append('model', model);
        return request<{ file_id: string }>('/api/agent/files', { method: 'POST', body: form });
      },
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
