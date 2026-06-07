/**
 * ToolCallList — renders all tool_call items of a turn in order.
 */

import type { TurnItem } from '../types';
import ToolCallCard from './ToolCallCard';

interface ToolCallListProps {
  items: TurnItem[];
}

export default function ToolCallList({ items }: ToolCallListProps) {
  const toolCalls = items.filter((it) => it.kind === 'tool_call');
  if (toolCalls.length === 0) return null;
  return (
    <div className="tool-list">
      {toolCalls.map((it) =>
        it.kind === 'tool_call' ? <ToolCallCard key={it.callId} item={it} /> : null,
      )}
    </div>
  );
}