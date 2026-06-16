/**
 * useConfigContext —— 读取 useConfig 的结构（用模块级 store 共享）。
 * 全应用只拉一次 /api/config/status 并写入全局 cache，避免 App 与 ChatPage
 * 各自 fetch 一次造成的竞态。
 */
import { createContext, useContext } from 'react';
import type { ConfigStore } from './useConfig';

export type ConfigContextValue = ConfigStore;

const ConfigContext = createContext<ConfigContextValue | null>(null);

export const ConfigContextProvider = ConfigContext.Provider;

export function useConfigContext(): ConfigContextValue {
  const ctx = useContext(ConfigContext);
  if (!ctx) {
    throw new Error('useConfigContext 必须在 ConfigContextProvider 内使用');
  }
  return ctx;
}
