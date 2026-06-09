/**
 * ConfigContext — 把 useConfig 的结果用 React Context 共享,
 * 整个 app 只调一次,避免 ChatPage / App 各自 fetch 一次造成的竞态和重复请求。
 *
 * H31 修复:之前 useConfig 在 App 和 ChatPage 各调一次,
 * 两个 useConfig 实例并发请求 /api/config/status,导致：
 *   1. 网络请求翻倍
 *   2. ChatPage 拿到的 configured/exists 可能晚于 App 解析,
 *      出现闪屏(短暂跳到 onboard 页面再切回 chat)。
 * 现在:App 调一次,把值塞到 Context,ChatPage 通过 useConfigContext() 读。
 */
import { createContext, useContext } from 'react';

export interface ConfigContextValue {
  exists: boolean | null;
  configured: boolean | null;
  reason: string;
  apiBase: string;
  /** App 端的 setter,供 OnboardPage 保存后通知。 */
  setExists: (_v: boolean) => void;
  setConfigured: (_v: boolean) => void;
}

const ConfigContext = createContext<ConfigContextValue | null>(null);

export const ConfigContextProvider = ConfigContext.Provider;

export function useConfigContext(): ConfigContextValue {
  const ctx = useContext(ConfigContext);
  if (!ctx) {
    throw new Error('useConfigContext 必须在 ConfigContextProvider 内使用');
  }
  return ctx;
}
