import { useEffect, useMemo, useState } from 'react';

/**
 * 启动时检测后端配置状态。
 * 返回 { configured, apiBase }
 *   configured: null=检测中, false=需引导, true=可用
 */
export function useConfig() {
  const [configured, setConfigured] = useState(null);

  const apiBase = useMemo(() => {
    if (import.meta.env.VITE_ZBOT_API_URL) return import.meta.env.VITE_ZBOT_API_URL;
    // 开发模式下直连后端 8000（Vite proxy 不稳定）
    if (import.meta.env.DEV) {
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
    return '';
  }, []);

  useEffect(() => {
    fetch(`${apiBase}/api/config/status`)
      .then((r) => r.json())
      .then((data) => setConfigured(!!data.configured))
      .catch(() => setConfigured(false));
  }, [apiBase]);

  return { configured, setConfigured, apiBase };
}
