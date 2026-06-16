import { useCallback, useEffect, useMemo, useState } from 'react';
import { createApiClient } from '../lib/api';
import type { SessionDetailResponse, SessionSummary } from '../types';

export function useSessions(apiBase: string) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const api = useMemo(() => createApiClient(apiBase), [apiBase]);

  // ZBot 改: 合并本地 (含乐观插入) 与 server 返回的列表。
  // 规则:
  //   - 本地优先: 保留所有本地项 (按本地顺序), 因为本地有用户最新交互的位置
  //   - server 补充: 把 server 里有但本地没有的项追加在末尾 (例如别的端创建的)
  //   - 同名合并: server 项覆盖本地项的 createdAt/updatedAt/messageCount (用真实数据)
  function mergeSessions(local: SessionSummary[], server: SessionSummary[]): SessionSummary[] {
    const byName = new Map<string, SessionSummary>();
    // 先填本地
    for (const s of local) byName.set(s.name, s);
    // 用 server 数据覆盖/补充
    for (const s of server) {
      const existing = byName.get(s.name);
      if (existing) {
        // 同名: 用 server 的真实时间戳/messageCount 更新本地, 但保留本地的位置
        byName.set(s.name, {
          ...existing,
          createdAt: s.createdAt || existing.createdAt,
          updatedAt: s.updatedAt || existing.updatedAt,
          messageCount: s.messageCount ?? existing.messageCount,
        });
      } else {
        // server 独有 (例如其他端创建)
        byName.set(s.name, s);
      }
    }
    // 按本地顺序输出, server 独有的追加在末尾
    const result: SessionSummary[] = [];
    const seen = new Set<string>();
    for (const s of local) {
      const merged = byName.get(s.name);
      if (merged) {
        result.push(merged);
        seen.add(s.name);
      }
    }
    for (const s of server) {
      if (!seen.has(s.name)) {
        result.push(s);
        seen.add(s.name);
      }
    }
    return result;
  }

  // 静默 refresh: 用于创建/删除/重命名后的"对齐服务端数据", 不翻转 loading
  // (loading=true 会让 SessionList 显示"加载中..."并把已显示的会话列表隐藏掉,
  //  给用户的感觉是"刚创建的会话消失了", 这就是用户报的那个 bug)
  // ZBot 改: 用 mergeSessions 合并而非覆盖, 保护乐观插入。
  const refreshSilent = useCallback(async () => {
    setError(null);
    try {
      const data = await api.sessions.list();
      setSessions((prev) => mergeSessions(prev, data || []));
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载会话失败');
    }
  }, [api]);

  // loud refresh: 用于外部触发, 会翻转 loading, 给 UI 提示"加载中"
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

  // 用指定名字创建会话 (POST /api/sessions)
  // ZBot 改: 乐观插入 + 用 POST 响应更新, 不调用 refreshSilent。
  // 之前 refreshSilent 会用 list 接口的 server data 整体 setSessions(...) 覆盖本地,
  // 在 server list 还没拿到新会话(竞态)的场景下把乐观插入擦掉, 表现就是
  // 「点击 √ 之后侧边栏没有新会话, 必须刷新页面才看见」。
  // 现在: POST 响应里直接带了 createdAt/updatedAt/messageCount, 用它更新乐观项即可,
  // 信任 POST 已成功的事实, 不再 list 一次(避免竞态)。
  const createSession = useCallback(async (sessionName: string): Promise<boolean> => {
    const now = new Date().toISOString();
    // ZBot 改: 乐观插入 - 用户刚按 Enter 侧边栏就能立刻看到新会话
    setSessions((prev) => {
      if (prev.some((s) => s.name === sessionName)) return prev;
      const optimistic: SessionSummary = {
        name: sessionName,
        createdAt: now,
        updatedAt: now,
        messageCount: 0,
      };
      return [optimistic, ...prev];
    });
    try {
      const detail = await api.sessions.create(sessionName);
      // 用 POST 响应里的真实时间戳覆盖乐观值, 不再 list 一次
      setSessions((prev) =>
        prev.map((s) =>
          s.name === sessionName
            ? {
                ...s,
                createdAt: detail.createdAt || s.createdAt,
                updatedAt: detail.updatedAt || s.updatedAt,
                messageCount: detail.messageCount ?? 0,
              }
            : s,
        ),
      );
      return true;
    } catch (err) {
      // 创建失败: 回滚乐观插入
      setSessions((prev) => prev.filter((s) => s.name !== sessionName));
      setError(err instanceof Error ? err.message : '创建会话失败');
      return false;
    }
  }, [api]);

  // 一键创建空会话, 后端生成 chat-<ts> 名字 (POST /api/sessions/quick-create)
  // ZBot 改: 同 createSession, 移除 refreshSilent 调用避免竞态覆盖乐观插入。
  const createQuickSession = useCallback(async (): Promise<string | null> => {
    // 先发请求, 同时准备乐观插入 (后端 name 通常是 chat-<ts>)
    try {
      const res = await fetch(`${apiBase}/api/sessions/quick-create`, { method: 'POST' });
      if (!res.ok) {
        setError(`创建会话失败 (${res.status})`);
        return null;
      }
      const data = (await res.json()) as { session_name: string };
      const sessionName = data.session_name;
      // 乐观插入: 后端已经返回了名字, 立即入栈
      const now = new Date().toISOString();
      setSessions((prev) => {
        if (prev.some((s) => s.name === sessionName)) return prev;
        return [{
          name: sessionName,
          createdAt: now,
          updatedAt: now,
          messageCount: 0,
        }, ...prev];
      });
      // 不调用 refreshSilent, 信任 POST 已成功, 避免竞态覆盖
      return sessionName;
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建会话失败');
      return null;
    }
  }, [apiBase]);

  // ZBot 改: SessionList "+" 入口统一走这里。
  //   - 传了名字 -> 用指定名字创建 (后端 POST /api/sessions)
  //   - 没传名字 -> 后端自动生成 chat-<ts> (POST /api/sessions/quick-create)
  // 返回最终生效的会话名 (供 UI 切过去)。
  const createSessionByName = useCallback(async (sessionName?: string): Promise<string | null> => {
    const trimmed = (sessionName ?? '').trim();
    if (trimmed) {
      const ok = await createSession(trimmed);
      return ok ? trimmed : null;
    }
    return createQuickSession();
  }, [createSession, createQuickSession]);

  const renameSession = useCallback(async (oldName: string, newName: string) => {
    try {
      await api.sessions.rename(oldName, newName);
      await refreshSilent();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '重命名会话失败');
      return false;
    }
  }, [api, refreshSilent]);

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

  // ZBot 改: 严格模式下两次 effect 跑, 各自持 ignore 闭包变量, 第二次的
  // load() 是真正生效的那次, 其 finally 块会把 loading 翻成 false。
  // 用 mergeSessions 合并, 避免在 list 接口返回前用户已创建新会话的乐观
  // 插入被"擦掉"。
  useEffect(() => {
    let ignore = false;
    async function load() {
      try {
        setLoading(true);
        setError(null);
        const data = await api.sessions.list();
        // ZBot 改: 函数式 setState, 合并而非覆盖, 避免覆盖乐观插入的会话。
        if (!ignore) {
          setSessions((prev) => mergeSessions(prev, data || []));
        }
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

  return { sessions, loading, error, refresh, refreshSilent, getSession, createSession, createQuickSession, createSessionByName, renameSession, deleteSession };
}