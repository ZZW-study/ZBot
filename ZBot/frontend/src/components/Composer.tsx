/**
 * Composer.jsx — 消息输入组件
 * 包含文本输入框和发送按钮
 */

import type { KeyboardEvent } from 'react';
import type { StringSetter } from '../types';

interface ComposerProps {
  input: string;
  setInput: StringSetter;
  onSend: () => void;
  disabled: boolean;
}

// 函数组件，接收 4 个 props
export default function Composer({ input, setInput, onSend, disabled }: ComposerProps) {

  // 键盘事件处理
  // event — 事件对象，包含按了什么键、有没有按修饰键等信息
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // event.key — 按下的键名（字符串，如 "Enter"、"a"、"Escape"）
    // event.ctrlKey — 是否按了 Ctrl（布尔值）
    // event.metaKey — 是否按了 Cmd（Mac 的 Command 键）
    // === 严格相等（不自动类型转换）
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      // preventDefault() — 阻止浏览器默认行为
      // 这里阻止的是：按 Enter 时 textarea 默认会换行
      event.preventDefault();
      onSend();  // 调用父组件传来的发送函数
    }
  };

  return (
    // <footer> — HTML 语义标签，表示"底部区域"
    <footer className="composer">
      {/* <textarea> — 多行文本输入框 */}
      {/* value={input} — 受控组件：输入框的值由 React 的 state 控制 */}
      {/* onChange — 输入框内容变化时，调用 setInput 更新 state */}
      {/* placeholder — 输入框为空时显示的提示文字 */}
      {/* rows={3} — 默认显示 3 行高度（JSX 里数字用 {} 包裹，不加引号） */}
      <textarea
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入任务，Ctrl/⌘ + Enter 发送"
        rows={3}
      />

      {/* 发送按钮 */}
      {/* disabled={disabled} — 父组件控制是否禁用 */}
      <button type="button" onClick={onSend} disabled={disabled}>
        发送
      </button>
    </footer>
  );
}
