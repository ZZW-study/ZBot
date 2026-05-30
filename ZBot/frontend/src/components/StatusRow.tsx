/**
 * StatusRow.jsx — 状态行组件
 * 最简单的组件：显示一行状态信息（标签 + 值）
 *
 * 显示效果：
 *   连接    已连接
 *   运行    空闲
 *   Run ID  -
 */

type StatusTone = 'neutral' | 'connecting' | 'connected' | 'disconnected' | 'error' | 'running' | 'idle';

interface StatusRowProps {
  label: string;
  value: string;
  tone?: StatusTone;
}

// { label, value, tone = 'neutral' } — 解构 props
// tone = 'neutral' — 默认值：如果父组件没传 tone，默认是 'neutral'
export default function StatusRow({ label, value, tone = 'neutral' }: StatusRowProps) {
  return (
    <div className="status-row">
      {/* 标签文字 */}
      <span>{label}</span>

      {/* 值（带颜色） */}
      {/* 模板字符串拼接两个 CSS 类名：始终有 "tone"，再加上动态的 tone */}
      {/*   例如 "tone connected" 或 "tone error" */}
      {/* <strong> — 粗体标签 */}
      <strong className={`tone ${tone}`}>{value}</strong>
    </div>
  );
}
