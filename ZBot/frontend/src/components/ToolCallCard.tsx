/**
 * ToolCallCard - 工具调用卡片 (可折叠)
 * 头部: 工具图标 + 名称 + 状态 (运行中 / 完成 + 耗时 / 失败)
 * 主体: 命令 / 参数 / 输出 (深色代码块, 默认折叠)
 *
 * 'exec' 工具在主体顶部单独显示 "Command" 行。
 */

import { useId, useMemo, useState } from 'react';
import type { ToolCallTurnItem } from '../types';

const TOOL_OUTPUT_TRUNCATE_LIMIT = 5000;

interface ToolCallCardProps {
  item: ToolCallTurnItem;
}

export default function ToolCallCard({ item }: ToolCallCardProps) {
  const bodyId = useId();
  // ZBot: collapsed by default. User clicks to expand. Avoids the "huge card" feel.
  const [open, setOpen] = useState(false);

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
        onClick={() => setOpen((v) => !v)}
      >
        <span className="tool-icon" aria-hidden="true">{icon}</span>
        <span className="tool-name">{label}</span>
        <span className="tool-status">
          {item.status === 'running' && (
            <>
              <span className="spinner" aria-hidden="true" />
              <span>运行中</span>
            </>
          )}
          {item.status === 'done' && (
            <>
              <span className="status-dot ok" aria-hidden="true" />
              <span>{elapsed != null ? `${elapsed}ms` : '完成'}</span>
            </>
          )}
          {item.status === 'failed' && (
            <>
              <span className="status-dot err" aria-hidden="true" />
              <span>失败</span>
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
              <div className="tool-section-label">参数</div>
              <pre className="tool-mono">{argsText}</pre>
            </div>
          )}
          {outputDisplay !== undefined && (
            <div className="tool-section">
              <div className="tool-section-label">输出</div>
              <pre className={`tool-mono ${item.status === 'failed' ? 'is-failed' : ''}`}>{outputDisplay}</pre>
              {outputTruncated && (
                <div className="tool-section-hint">输出已截断到 {TOOL_OUTPUT_TRUNCATE_LIMIT} 字符。</div>
              )}
            </div>
          )}
          {item.status === 'running' && (
            <div className="tool-section-hint">正在等待工具结果...</div>
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