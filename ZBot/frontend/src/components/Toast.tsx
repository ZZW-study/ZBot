/**
 * Toast viewport — fixed bottom-right stack.
 * Auto-dismisses info toasts after 5s; error toasts are sticky.
 * Press Escape to dismiss the topmost toast.
 */

import { useEffect } from 'react';
import { useToasts } from '../hooks/useToasts';

const AUTO_DISMISS_MS = 5000;

export default function ToastViewport() {
  const { toasts, dismiss } = useToasts();

  useEffect(() => {
    const timers = toasts
      .filter((t) => !t.sticky)
      .map((t) =>
        window.setTimeout(() => {
          dismiss(t.id);
        }, AUTO_DISMISS_MS),
      );
    return () => {
      for (const id of timers) window.clearTimeout(id);
    };
  }, [toasts, dismiss]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && toasts.length > 0) {
        dismiss(toasts[toasts.length - 1].id);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toasts, dismiss]);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-viewport" role="region" aria-label="Notifications">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`toast ${t.kind}`}
          role={t.kind === 'error' ? 'alert' : 'status'}
          aria-live={t.kind === 'error' ? 'assertive' : 'polite'}
        >
          <div className="toast-body">
            <strong className="toast-message">{t.message}</strong>
            {t.detail && <span className="toast-detail">{t.detail}</span>}
          </div>
          <button
            type="button"
            className="toast-dismiss"
            aria-label="Dismiss notification"
            onClick={() => dismiss(t.id)}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" fill="none" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}