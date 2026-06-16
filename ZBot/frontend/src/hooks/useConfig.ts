/**
 * useConfig —— 启动时拉一次 /api/config/status 决定路由（onboard 还是 chat）。
 *
 * 实现细节：
 *   1) 用 module-level cache + useSyncExternalStore 共享整个应用的状态，
 *      避免 App / ChatPage 各自 fetch 一次造成的竞态闪屏。
 *   2) 暴露 refetch() —— OnboardPage 保存配置成功后调用，重新拉 status 决定路由。
 *   3) apiBase 在 DEV 模式下默认走 :8000（Vite 代理是次优选——某些浏览器对
 *      EventSource 经 http-proxy 的 keep-alive 行为不一致；直连后端更稳）。
 */
import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { createApiClient } from '../lib/api';

export interface ConfigStore {
  /** null = 尚未拉取（启动期），true/false = 后端真实状态 */
  exists: boolean | null;
  /** 同上；exists && configured 才是真正"可对话"的状态 */
  configured: boolean | null;
  reason: string;
  apiBase: string;
  // ZBot 改:当前选中的模型名,前端用来做多模态能力拦截
  model: string;
  refetch: () => Promise<void>;
}

type Listener = () => void;

interface InternalState {
  exists: boolean | null;
  configured: boolean | null;
  reason: string;
  model: string;
}

let state: InternalState = { exists: null, configured: null, reason: '', model: '' };
const listeners = new Set<Listener>();
let inflight: Promise<void> | null = null;

function emit(): void {
  for (const l of listeners) l();
}

function subscribe(l: Listener): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

function getSnapshot(): InternalState {
  return state;
}

function resolveApiBase(): string {
  if (typeof window === 'undefined') return '';
  // 显式 env 覆盖（生产或自定义部署）
  const envBase = (import.meta.env.VITE_ZBOT_API_URL as string | undefined) || '';
  if (envBase) return envBase;
  if (import.meta.env.DEV) {
    // Vite dev 时默认直连 8000，避免 EventSource 经 Vite 代理在某些浏览器
    // 出现的 keep-alive 超时断流。EventSource 是同源策略限制相对路径。
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  // 生产构建：同源
  return '';
}

function getApiBaseSnapshot(): string {
  // apiBase 在模块加载时一次性解析
  if (!(getApiBaseSnapshot as unknown as { _v?: string })._v) {
    (getApiBaseSnapshot as unknown as { _v?: string })._v = resolveApiBase();
  }
  return (getApiBaseSnapshot as unknown as { _v: string })._v;
}

async function loadFromBackend(apiBase: string): Promise<void> {
  if (inflight) return inflight;
  const api = createApiClient(apiBase);
  inflight = (async () => {
    try {
      const data = await api.config.status();
      state = {
        exists: !!data.exists,
        configured: !!data.configured,
        reason: data.reason || '',
        model: data.model || '',
      };
    } catch {
      // 后端完全不可达：把 exists/configured 都设为 false，让 App 路由到 onboard
      state = { exists: false, configured: false, reason: '', model: '' };
    } finally {
      inflight = null;
      emit();
    }
  })();
  return inflight;
}

export function useConfig(): ConfigStore {
  const apiBase = useMemo(() => getApiBaseSnapshot(), []);
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    // 第一次进入时拉一次；后续 OnboardPage 会通过 refetch 显式触发
    void loadFromBackend(apiBase);
  }, [apiBase]);

  const refetch = useMemo(
    () => () => loadFromBackend(apiBase),
    [apiBase],
  );

  return {
    exists: snapshot.exists,
    configured: snapshot.configured,
    reason: snapshot.reason,
    apiBase,
    // ZBot 改:暴露 model 给前端能力检查
    model: snapshot.model,
    refetch,
  };
}
