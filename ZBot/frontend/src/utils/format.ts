/**
 * format.js — 工具函数
 * 纯函数：不依赖 React 状态，只根据输入返回输出
 * 类似 Python 的 utils.py
 */

// ═══════════════════════════════════════════════════════════
// socketStateLabel — WebSocket 状态转中文
// ═══════════════════════════════════════════════════════════

// export function — 具名导出
// 导入时：import { socketStateLabel } from '../utils/format'
import type { AgentEvent, SocketState } from '../types';

function payloadString(event: AgentEvent, key: string): string {
  const value = event.payload?.[key];
  return typeof value === 'string' ? value : '';
}

export function socketStateLabel(state: SocketState): string {
  // if-else 链：根据状态字符串返回对应的中文
  if (state === 'connected') return '已连接';
  if (state === 'connecting') return '连接中';
  if (state === 'error') return '异常';
  // 默认返回（前面都不匹配时执行）
  return '已断开';
}


// ═══════════════════════════════════════════════════════════
// eventTitle — 事件类型转中文标题
// ═══════════════════════════════════════════════════════════

export function eventTitle(event: AgentEvent): string {
  // || 默认值：如果 event.agent_label 是假值，用 'Agent'
  const agent = event.agent_label || 'Agent';

  // ?. 可选链 + 动态属性访问
  const toolName = payloadString(event, 'tool_name');

  // 模板字符串里可以嵌入三元运算符
  // ${toolName ? `：${toolName}` : ''} — 如果有工具名就显示，没有就显示空字符串
  if (event.type === 'model.started') return `${agent} 正在请求大模型`;
  if (event.type === 'model.completed') return `${agent} 大模型响应完成`;
  if (event.type === 'assistant.delta') return `${agent} 正在生成回答`;
  if (event.type === 'assistant.completed') return `${agent} 回答生成完成`;
  if (event.type === 'tool.started') return `正在调用工具${toolName ? `：${toolName}` : ''}`;
  if (event.type === 'tool.completed') return `工具调用完成${toolName ? `：${toolName}` : ''}`;
  if (event.type === 'tool.failed') return `工具调用失败${toolName ? `：${toolName}` : ''}`;
  if (event.type === 'tool.progress') return '工具调用进度';
  if (event.type === 'agent.progress') return `${agent} 正在处理`;
  if (event.type === 'subagent.started') return `${agent} 已启动`;
  if (event.type === 'subagent.completed') return `${agent} 已完成`;
  if (event.type === 'subagent.failed') return `${agent} 失败`;
  if (event.type === 'compaction.started') return '正在压缩上下文';
  if (event.type === 'compaction.completed') return '上下文压缩完成';
  if (event.type === 'turn.started') return '开始处理本轮消息';
  if (event.type === 'turn.completed') return '本轮消息处理完成';
  if (event.type === 'run.started') return '会话已启动';
  if (event.type === 'run.completed') return '任务完成';
  if (event.type === 'run.failed') return '任务失败';
  if (event.type === 'run.cancelled') return '任务已取消';

  // 兜底：返回事件类型原文，或 '运行事件'
  return event.type || '运行事件';
}


// ═══════════════════════════════════════════════════════════
// eventMessage — 事件转可读消息
// ═══════════════════════════════════════════════════════════

export function eventMessage(event: AgentEvent | null): string {
  // 如果 event 不存在（null/undefined），返回默认文本
  if (!event) return '正在处理任务...';

  // assistant.delta — 流式文本片段
  if (event.type === 'assistant.delta') return payloadString(event, 'delta') || event.message || '';

  // assistant.completed — 回答完成
  if (event.type === 'assistant.completed') return '回答生成完成';

  // 工具相关事件：有 message 就显示，没有就用 eventTitle
  // event.message ? ... : ... — 三元运算符
  if (event.type === 'tool.started') {
    return event.message ? `正在调用工具：${event.message}` : eventTitle(event);
  }
  if (event.type === 'tool.completed') {
    return event.message ? `工具调用完成：${event.message}` : eventTitle(event);
  }
  if (event.type === 'tool.failed') {
    return event.message ? `工具调用失败：${event.message}` : eventTitle(event);
  }

  // 兜底：有 message 就用，没有就用 eventTitle
  return event.message || eventTitle(event);
}


// ═══════════════════════════════════════════════════════════
// formatTime — ISO 时间戳转本地化时间
// ═══════════════════════════════════════════════════════════

export function formatTime(value?: string): string {
  // 空值检查
  if (!value) return '';

  // new Date(isoString) — 把 ISO 时间字符串转为 Date 对象
  const date = new Date(value);

  // Number.isNaN() — 检查是否是 NaN（无效日期）
  // date.getTime() — 获取时间戳（毫秒），无效日期返回 NaN
  if (Number.isNaN(date.getTime())) return '';

  // toLocaleTimeString — 转为本地化的时间字符串
  // [] — 使用默认 locale
  // { hour: '2-digit', minute: '2-digit', second: '2-digit' } — 格式选项
  // 输出如 "14:30:05"
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
