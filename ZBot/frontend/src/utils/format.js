/** WebSocket 连接状态 → 中文标签 */
export function socketStateLabel(state) {
  if (state === 'connected') return '已连接';
  if (state === 'connecting') return '连接中';
  if (state === 'error') return '异常';
  return '已断开';
}

export function eventTitle(event) {
  const agent = event.agent_label || 'Agent';
  const toolName = event.payload?.tool_name;

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
  return event.type || '运行事件';
}

export function eventMessage(event) {
  if (!event) return '正在处理任务...';
  if (event.type === 'assistant.delta') return event.payload?.delta || event.message || '';
  if (event.type === 'assistant.completed') return '回答生成完成';
  if (event.type === 'tool.started') {
    return event.message ? `正在调用工具：${event.message}` : eventTitle(event);
  }
  if (event.type === 'tool.completed') {
    return event.message ? `工具调用完成：${event.message}` : eventTitle(event);
  }
  if (event.type === 'tool.failed') {
    return event.message ? `工具调用失败：${event.message}` : eventTitle(event);
  }
  return event.message || eventTitle(event);
}

/** ISO 时间戳 → 本地化时间字符串 */
export function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
