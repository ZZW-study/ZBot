/**
 * ReasoningBlock — collapsible "💭 Thinking" block for `response_item/reasoning`.
 * Default collapsed.
 */

import { useState } from 'react';

interface ReasoningBlockProps {
  summary: string;
}

export default function ReasoningBlock({ summary }: ReasoningBlockProps) {
  const [open, setOpen] = useState(false);
  if (!summary) return null;
  return (
    <div className={`reasoning-block ${open ? 'open' : ''}`}>
      <button
        type="button"
        className="reasoning-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="reasoning-emoji" aria-hidden="true">💭</span>
        <span>{open ? 'Hide thinking' : 'Show thinking'}</span>
        <svg className="reasoning-chevron" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        </svg>
      </button>
      {open && <div className="reasoning-content">{summary}</div>}
    </div>
  );
}