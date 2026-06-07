/**
 * useToasts — tiny subscription-based toast store.
 *
 * One shared store for the whole app. Components subscribe via this hook;
 * ToastViewport re-renders on every change.
 */

import { useCallback, useSyncExternalStore } from 'react';
import type { Toast, ToastKind } from '../types';

let toasts: Toast[] = [];
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot() {
  return toasts;
}

function notify() {
  for (const l of listeners) l();
}

function push(toast: Omit<Toast, 'id'>): string {
  const id = `t-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  toasts = [...toasts, { id, ...toast }];
  notify();
  return id;
}

function dismiss(id: string) {
  toasts = toasts.filter((t) => t.id !== id);
  notify();
}

function clear() {
  toasts = [];
  notify();
}

export const toastStore = { push, dismiss, clear };

export function useToasts() {
  // useSyncExternalStore guarantees the component sees the latest snapshot
  // at commit time, even if push() was called between render and the
  // subscription effect. The previous useState+useEffect pair had a race
  // window where a push between mount and effect would be lost.
  const items = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const pushToast = useCallback((kind: ToastKind, message: string, opts?: { detail?: string; sticky?: boolean }) => {
    return push({
      kind,
      message,
      detail: opts?.detail,
      sticky: opts?.sticky ?? kind === 'error',
    });
  }, []);

  return {
    toasts: items,
    push: pushToast,
    dismiss,
    clear,
  };
}