/**
 * ChatHeader — extracted from ChatPage. Shows thread title, model + token
 * usage, and a Stop button when a run is active.
 */

import type { TokenUsage } from '../types';

interface ChatHeaderProps {
  title: string;
  modelLabel?: string;
  tokenUsage?: TokenUsage;
  modelContextWindow: number;
  configWarning?: string;
  isRunning: boolean;
  onStop: () => void;
  onOpenDrawer?: () => void;
  onCloseDrawer?: () => void;
  isNarrow?: boolean;
  isDrawerOpen?: boolean;
}

export default function ChatHeader({
  title,
  modelLabel,
  tokenUsage,
  modelContextWindow,
  configWarning,
  isRunning,
  onStop,
  onOpenDrawer,
  onCloseDrawer,
  isNarrow,
  isDrawerOpen,
}: ChatHeaderProps) {
  const usedTokens = (tokenUsage?.inputTokens ?? 0) + (tokenUsage?.outputTokens ?? 0);
  const showMeter = !!tokenUsage && modelContextWindow > 0;
  return (
    <header className="chat-header">
      <div className="chat-header-left">
        {isNarrow && (
          <button
            type="button"
            className="hamburger-button"
            aria-label={isDrawerOpen ? 'Close session list' : 'Open session list'}
            aria-expanded={!!isDrawerOpen}
            aria-controls="session-drawer"
            onClick={() => (isDrawerOpen ? onCloseDrawer?.() : onOpenDrawer?.())}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <path d="M3 5h12M3 9h12M3 13h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        )}
        <div>
          <h2 className="chat-header-title">{title || 'New thread'}</h2>
          {modelLabel && <p className="chat-header-model">{modelLabel}</p>}
          {configWarning && <p className="config-warning">{configWarning}</p>}
        </div>
      </div>
      <div className="chat-header-right">
        {showMeter && (
          <span className="token-meter" aria-label="Token usage">
            <span className="token-meter-text">
              {formatTokens(usedTokens)} / {formatTokens(modelContextWindow)}
            </span>
            <span
              className="token-meter-bar"
              aria-hidden="true"
              style={{
                width: `${Math.min(100, (usedTokens / modelContextWindow) * 100).toFixed(1)}%`,
              }}
            />
          </span>
        )}
        {isRunning && (
          <button type="button" className="stop-button" onClick={onStop} aria-label="Stop current run">
            <span className="stop-button-dot" aria-hidden="true" />
            Stop
          </button>
        )}
      </div>
    </header>
  );
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
