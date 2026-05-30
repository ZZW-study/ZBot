import { useEffect, useMemo, useState } from 'react';
import { createApiClient } from '../lib/api';

export function useConfig() {
  const [exists, setExists] = useState<boolean | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [reason, setReason] = useState('');

  const apiBase = useMemo(() => {
    if (import.meta.env.VITE_ZBOT_API_URL) return import.meta.env.VITE_ZBOT_API_URL;
    if (import.meta.env.DEV) {
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
    return '';
  }, []);

  useEffect(() => {
    const api = createApiClient(apiBase);
    api.config.status()
      .then((data) => {
        setExists(!!data.exists);
        setConfigured(!!data.configured);
        setReason(data.reason || '');
      })
      .catch(() => {
        setExists(false);
        setConfigured(false);
        setReason('');
      });
  }, [apiBase]);

  return { exists, setExists, configured, setConfigured, reason, setReason, apiBase };
}
