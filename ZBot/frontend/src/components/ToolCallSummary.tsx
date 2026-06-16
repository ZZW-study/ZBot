/**
 * ToolCallSummary - final answer 下方的紧凑工具调用摘要行.
 *
 * 默认折叠: 单行显示 "调用了 N 个工具 (web_search, create_sub_agent) [展开]"
 * 点击展开后, 复用 ToolCallCard 的 body 渲染显示每个 tool_call 的 args + output.
 *
 * 视觉风格: 浅灰底, 圆角 8px, 左侧 3px accent 条.
 */

import { useId, useMemo, useState } from 'react';
import type { ToolCallTurnItem } from '../types';
import ToolCallCard from './ToolCallCard';

interface Props {
  toolCalls: ToolCallTurnItem[];
}

const MAX_LABEL_LENGTH = 80;

export default function ToolCallSummary({ toolCalls }: Props) {
  const bodyId = useId();
  const [open, setOpen] = useState(false);

  const summary = useMemo(() => buildSummary(toolCalls), [toolCalls]);
  // ZBot 改: 调用次数按工具名去重计数 (调用了 2 种工具), 避免同一种工具
  // 调 7 次时显示 "调用了 7 个工具" 这种误导性文案。
  const distinctCount = useMemo(() => new Set(toolCalls.map((t) => t.name)).size, [toolCalls]);

  if (toolCalls.length === 0) return null;

  return (
    <section className="tool-summary" aria-label="本轮工具调用">
      <button
        type="button"
        className="tool-summary-header"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="tool-summary-emoji" aria-hidden="true">🔧</span>
        <span className="tool-summary-label">调用了 {distinctCount} 种工具（共 {toolCalls.length} 次）</span>
        <span className="tool-summary-names">{summary}</span>
        <svg
          className={`tool-summary-chevron ${open ? 'open' : ''}`}
          width="12"
          height="12"
          viewBox="0 0 12 12"
          aria-hidden="true"
        >
          <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        </svg>
      </button>

      {open && (
        <div className="tool-summary-body" id={bodyId}>
          {toolCalls.map((it) => (
            <ToolCallCard key={it.callId} item={it} />
          ))}
        </div>
      )}
    </section>
  );
}

function buildSummary(toolCalls: ToolCallTurnItem[]): string {
  // ZBot 改: 按工具名分组计数, 输出 "web_search × 3, read_file × 1" 形式。
  // 之前是列出每个独立调用名 (web_search, web_search, web_search), 同名工具
  // 全展开用户看不出「总共调了几次」, 用户原话: "应该这样显示, 某某工具调用次数"。
  if (toolCalls.length === 0) return '';
  const counts = new Map<string, number>();
  for (const t of toolCalls) {
    counts.set(t.name, (counts.get(t.name) ?? 0) + 1);
  }
  const parts: string[] = [];
  for (const [name, count] of counts) {
    parts.push(count > 1 ? `${name} × ${count}` : name);
  }
  const text = `(${parts.join(', ')})`;
  if (text.length <= MAX_LABEL_LENGTH) return text;
  return text.slice(0, MAX_LABEL_LENGTH) + '…';
}
