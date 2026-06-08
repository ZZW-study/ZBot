import { useCallback, useEffect, useMemo, useState } from 'react';
import { createApiClient } from '../lib/api';
import type { SessionDetailResponse, SessionSummary } from '../types';

export function useSessions(apiBase: string) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const api = useMemo(() => createApiClient(apiBase), [apiBase]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.sessions.list();
      setSessions(data || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载会话失败');
      setSessions([]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  const createSession = useCallback(async (sessionName: string) => {
    try {
      await api.sessions.create(sessionName);
      await refresh();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建会话失败');
      return false;
    }
  }, [api, refresh]);

  const renameSession = useCallback(async (oldName: string, newName: string) => {
    try {
      await api.sessions.rename(oldName, newName);
      await refresh();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '重命名会话失败');
      return false;
    }
  }, [api, refresh]);

  const deleteSession = useCallback(async (sessionName: string) => {
    try {
      await api.sessions.delete(sessionName);
      setSessions((prev) => prev.filter((s) => s.name !== sessionName));
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除会话失败');
      return false;
    }
  }, [api]);

  const getSession = useCallback(async (sessionName: string): Promise<SessionDetailResponse | null> => {
    try {
      setError(null);
      return await api.sessions.get(sessionName);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载会话历史失败');
      return null;
    }
  }, [api]);

  useEffect(() => {
    let ignore = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);
        const data = await api.sessions.list();
        if (!ignore) setSessions(data || []);
      } catch (err) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : '加载会话失败');
          setSessions([]);
        }
      } finally {
        if (!ignore) setLoading(false);
      }
    }

    load();

    return () => {
      ignore = true;
    };
  }, [api]);

  return { sessions, loading, error, refresh, getSession, createSession, renameSession, deleteSession };
}
