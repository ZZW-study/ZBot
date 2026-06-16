/**
 * useMcpConnection - ZBot 改: 缓存后端 MCP 工具连接状态.
 *
 * 设计:
 *   - 模块级 cache + useSyncExternalStore, 整个 app 只 fetch 一次 /api/mcp/status
 *   - 启动时立即读 localStorage (zbot.mcp.connected) 做秒级显示,
 *     后台 fetch 校准 (避免每次 sendMessage 都要查后端)
 *   - 暴露 connected / connecting / servers 状态, 以及 refresh()
 */
import { useEffect, useSyncExternalStore } from 'react';

export interface McpState {
  connected: boolean | null; // null = 未知 / 加载中
  connecting: boolean;
  servers: string[];
  fetchedAt: number | null;
}

const STORAGE_KEY = 'zbot.mcp.connected';

let state: McpState = {
  connected: null,
  connecting: false,
  servers: [],
  fetchedAt: null,
};

// 启动时从 localStorage 同步读 (秒级"已连接"指示)
try {
  if (typeof window !== 'undefined') {
    const cached = window.localStorage.getItem(STORAGE_KEY);
    if (cached === '1') {
      state = { ...state, connected: true };
    } else if (cached === '0') {
      state = { ...state, connected: false };
    }
  }
} catch {
  /* ignore: SSR or quota */
}

const listeners = new Set<() => void>();

function emit(): void {
  for (const l of listeners) l();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

function getSnapshot(): McpState {
  return state;
}

function persist(): void {
  try {
    if (typeof window === 'undefined') return;
    if (state.connected === true) {
      window.localStorage.setItem(STORAGE_KEY, '1');
    } else if (state.connected === false) {
      window.localStorage.setItem(STORAGE_KEY, '0');
    }
  } catch {
    /* ignore */
  }
}

let inflight: Promise<void> | null = null;

export async function refreshMcpStatus(apiBase: string): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      const res = await fetch(`${apiBase}/api/mcp/status`, { method: 'GET' });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = (await res.json()) as {
        connected: boolean;
        connecting: boolean;
        servers: string[];
      };
      state = {
        connected: !!data.connected,
        connecting: !!data.connecting,
        servers: Array.isArray(data.servers) ? data.servers : [],
        fetchedAt: Date.now(),
      };
      persist();
      emit();
    } catch {
      // 后端不可达: 保持上一次状态, 不弹错
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

export function useMcpConnection(apiBase: string): McpState & { refresh: () => Promise<void> } {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    // mount 时如果还没拉过, 立即拉一次
    if (snapshot.fetchedAt === null) {
      void refreshMcpStatus(apiBase);
    }
  }, [apiBase, snapshot.fetchedAt]);

  return {
    ...snapshot,
    refresh: () => refreshMcpStatus(apiBase),
  };
}
