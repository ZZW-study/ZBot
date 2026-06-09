/**
 * ToolCallCard — collapsible card for a single `function_call` + its `output`.
 * Header shows: tool icon + name + status (running spinner / done with elapsed
 * time / failed). Body shows args (JSON) and output (monospace, default
 * collapsed if > 500 chars, truncated if > 5000 chars).
 *
 * `exec` gets a dedicated "Command" line at the top of the body.
 */

import { useEffect, useId, useMemo, useState } from 'react';
import type { ToolCallTurnItem } from '../types';

const TOOL_OUTPUT_COLLAPSE_THRESHOLD = 500;
const TOOL_OUTPUT_TRUNCATE_LIMIT = 5000;

interface ToolCallCardProps {
  item: ToolCallTurnItem;
}

export default function ToolCallCard({ item }: ToolCallCardProps) {
  const bodyId = useId();
  const hasLongOutput = !!item.output && item.output.length > TOOL_OUTPUT_COLLAPSE_THRESHOLD;
  // Default: expanded while running, collapsed once a long output arrives.
  const [userOverride, setUserOverride] = useState<boolean | null>(null);
  const open = userOverride ?? !(item.status === 'done' && hasLongOutput);

  // If output grows past the threshold after mount and the user hasn't
  // manually expanded the card, snap it closed. This matches the "500+ chars
  // collapses" rule for the initial render.
  useEffect(() => {
    if (item.status === 'done' && hasLongOutput && userOverride === null) {
      setUserOverride(false);
    }
  }, [item.status, hasLongOutput, userOverride]);

  const { icon, label } = useMemo(() => toolPresentation(item.name), [item.name]);

  const elapsed = item.endedAt && item.startedAt ? item.endedAt - item.startedAt : null;
  const argsText = useMemo(() => formatArgs(item.arguments), [item.arguments]);
  const { outputDisplay, outputTruncated } = useMemo(
    () => truncateOutput(item.output),
    [item.output],
  );

  return (
    <article className={`tool-card status-${item.status}`}>
      <button
        type="button"
        className="tool-card-header"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setUserOverride((v) => (v === null ? !open : !v))}
      >
        <span className="tool-icon" aria-hidden="true">{icon}</span>
        <span className="tool-name">{label}</span>
        <span className="tool-status">
          {item.status === 'running' && (
            <>
              <span className="spinner" aria-hidden="true" />
              <span>running</span>
            </>
          )}
          {item.status === 'done' && (
            <>
              <span className="status-dot ok" aria-hidden="true" />
              <span>{elapsed != null ? `${elapsed}ms` : 'done'}</span>
            </>
          )}
          {item.status === 'failed' && (
            <>
              <span className="status-dot err" aria-hidden="true" />
              <span>failed</span>
            </>
          )}
        </span>
        <svg className={`tool-chevron ${open ? 'open' : ''}`} width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        </svg>
      </button>

      {open && (
        <div className="tool-card-body" id={bodyId}>
          {item.name === 'exec' && typeof item.arguments.command === 'string' && (
            <div className="tool-section">
              <div className="tool-section-label">Command</div>
              <pre className="tool-mono">$ {item.arguments.command}</pre>
            </div>
          )}
          {argsText && (
            <div className="tool-section">
              <div className="tool-section-label">Arguments</div>
              <pre className="tool-mono">{argsText}</pre>
            </div>
          )}
          {outputDisplay !== undefined && (
            <div className="tool-section">
              <div className="tool-section-label">Output</div>
              <pre className={`tool-mono ${item.status === 'failed' ? 'is-failed' : ''}`}>{outputDisplay}</pre>
              {outputTruncated && (
                <div className="tool-section-hint">Output truncated to {TOOL_OUTPUT_TRUNCATE_LIMIT} characters.</div>
              )}
            </div>
          )}
          {item.status === 'running' && (
            <div className="tool-section-hint">Waiting for tool result...</div>
          )}
        </div>
      )}
    </article>
  );
}

function truncateOutput(text: string | undefined): { outputDisplay: string | undefined; outputTruncated: boolean } {
  if (text === undefined) return { outputDisplay: undefined, outputTruncated: false };
  if (text.length > TOOL_OUTPUT_TRUNCATE_LIMIT) {
    return { outputDisplay: text.slice(0, TOOL_OUTPUT_TRUNCATE_LIMIT), outputTruncated: true };
  }
  return { outputDisplay: text, outputTruncated: false };
}

function formatArgs(args: Record<string, unknown>): string {
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

function toolPresentation(name: string): { icon: string; label: string } {
  if (name === 'exec') return { icon: '\u26a1', label: 'exec' };
  if (name === 'read_file') return { icon: '\ud83d\udcc4', label: 'read_file' };
  if (name === 'write_file' || name === 'edit_file') return { icon: '\u270f\ufe0f', label: name };
  if (name === 'list_dir') return { icon: '\ud83d\udcc1', label: 'list_dir' };
  if (name === 'grep_search' || name === 'glob_search') return { icon: '\ud83d\udd0d', label: name };
  if (name === 'web_search' || name === 'web_fetch') return { icon: '\ud83c\udf10', label: name };
  if (name === 'create_sub_agent') return { icon: '\ud83e\udd16', label: 'create_sub_agent' };
  if (name === 'cron') return { icon: '\u23f0', label: 'cron' };
  return { icon: '\u2753', label: name };
}
