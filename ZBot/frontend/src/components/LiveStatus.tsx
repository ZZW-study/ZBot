/**
 * LiveStatus - 单一状态卡片 (过程 vs 结果 分离 spec).
 *
 * 阶段 -> 文案:
 *   thinking    -> "🤔💭 ZBot 正在思考..."
 *   tool        -> "🛠️ <icon> ZBot 正在调用 <name>..." (按工具名匹配图标)
 *   finalizing  -> "✨📝 ZBot 正在整理结果..."
 *   streaming   -> "✍️ ZBot 正在分析结果..." (中间文字触发, 不再隐藏)
 *
 * 父组件 MessageList 只在 isRunning 时挂载本组件。
 * 文字切换通过 React key 触发 CSS crossfade 动画。
 */
import type { ReactElement } from 'react';

interface Props {
  // 'idle' 也在范围内: 父组件可能在 run 刚启动时拿到 'idle', LiveStatus 内部
  // fallback 到 'thinking' 文案 (start 阶段用户感知不到差别).
  phase: 'idle' | 'thinking' | 'tool' | 'finalizing' | 'streaming';
  toolName?: string;
}

interface PhaseView {
  emoji: string;
  text: string;
}

/**
 * ZBot 改: 按工具名匹配更具体的图标, 让用户一眼看出调的是哪类工具。
 * 匹配规则 (大小写不敏感, 子串匹配):
 *   search / web / fetch / http  -> 🔍 搜索类
 *   read / file / open / load    -> 📄 文件读取
 *   write / save / create / edit -> ✏️ 文件写入
 *   exec / shell / run / cmd / bash -> 💻 命令执行
 *   git                          -> 🔀 Git 操作
 *   memory / recall              -> 🧠 记忆
 *   think / reason / plan        -> 💡 推理
 *   sub_agent / subagent / agent -> 🤖 子 Agent
 *   cron / schedule / timer      -> ⏰ 定时任务
 *   code / analyze / grep        -> 🔬 代码分析
 *   image / vision / screenshot  -> 🖼️ 图像
 *   math / calc / compute        -> 🔢 计算
 * 其它未知工具 -> 🛠️ 通用工具图标
 */
function toolEmoji(name: string): string {
  const n = (name || '').toLowerCase();
  if (/(search|web|fetch|http|scrape|crawl|browse)/.test(n)) return '🔍';
  if (/(read|file|open|load|cat|view)/.test(n)) return '📄';
  if (/(write|save|create|edit|update|append)/.test(n)) return '✏️';
  if (/(exec|shell|run|cmd|bash|sh)/.test(n)) return '💻';
  if (/git/.test(n)) return '🔀';
  if (/(memory|recall|remember)/.test(n)) return '🧠';
  if (/(think|reason|plan|reflect)/.test(n)) return '💡';
  if (/(sub_agent|subagent|agent)/.test(n)) return '🤖';
  if (/(cron|schedule|timer|remind)/.test(n)) return '⏰';
  if (/(code|analyze|grep|inspect)/.test(n)) return '🔬';
  if (/(image|vision|screenshot|photo)/.test(n)) return '🖼️';
  if (/(math|calc|compute)/.test(n)) return '🔢';
  return '🛠️';
}

function phaseView(phase: Props['phase'], toolName: string): PhaseView {
  switch (phase) {
    case 'thinking':
      return { emoji: '🤔', text: 'ZBot 正在思考' };
    case 'tool':
      return { emoji: toolEmoji(toolName), text: `ZBot 正在调用 ${toolName || '工具'}` };
    case 'finalizing':
      return { emoji: '✨', text: 'ZBot 正在整理结果' };
    case 'streaming':
      return { emoji: '✍️', text: 'ZBot 正在分析结果' };
    case 'idle':
    default:
      return { emoji: '🤔', text: 'ZBot 正在思考' };
  }
}

export default function LiveStatus({ phase, toolName = '' }: Props): ReactElement {
  const view = phaseView(phase, toolName);
  return (
    <div className="live-status live-status--card" role="status" aria-live="polite">
      <span className="live-status-pulse" aria-hidden="true" />
      <span key={`${phase}-${view.text}`} className="live-status-text live-status-text--animated">
        <span className="live-status-emoji" aria-hidden="true">{view.emoji}</span>
        {view.text}
        <span className="live-status-dots" aria-hidden="true">…</span>
      </span>
    </div>
  );
}