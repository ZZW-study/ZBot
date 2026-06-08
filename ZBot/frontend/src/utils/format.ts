/**
 * format.ts — 工具函数
 * 纯函数:不依赖 React 状态,只根据输入返回输出
 */

// ═══════════════════════════════════════════════════════════
// connectionStateLabel — 连接状态转中文
// ═══════════════════════════════════════════════════════════

import type { SocketState } from '../types';

export function connectionStateLabel(state: SocketState): string {
  if (state === 'connected') return '已连接';
  if (state === 'connecting') return '连接中';
  if (state === 'error') return '异常';
  return '已断开';
}


// ═══════════════════════════════════════════════════════════
// formatTime — ISO 时间戳转本地化时间
// ═══════════════════════════════════════════════════════════

export function formatTime(value?: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
