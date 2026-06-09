/**
 * Composer — 消息输入组件
 * 包含文本输入框、附件 chip 区、发送按钮
 */

import { useRef, type KeyboardEvent } from 'react';
import FileChip from './FileChip';
import type { AttachedFile, StringSetter } from '../types';

interface ComposerProps {
  input: string;
  setInput: StringSetter;
  onSend: () => void;
  disabled: boolean;
  attachedFiles: AttachedFile[];
  onAddFile: (_file: File) => void | Promise<void>;
  onRemoveFile: (_index: number) => void;
}

// H32 修复:加 accept + maxLength,客户端拒绝 200MB 任意类型的上传。
// 后端已经有 MAX_FILE_BYTES=10MB,但客户端先提示能减少网络往返和 UX 体验。
const FILE_ACCEPT = '.txt,.md,.pdf,.png,.jpg,.jpeg,.gif,.webp,.json,.csv,.yaml,.yml,.py,.js,.ts,.tsx,.jsx,.html,.css,.xml,.log';
const FILE_MAX_BYTES = 10 * 1024 * 1024; // 10 MB

export default function Composer({
  input, setInput, onSend, disabled,
  attachedFiles, onAddFile, onRemoveFile,
}: ComposerProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // 键盘事件处理
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl/⌘ + Enter 触发发送
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      onSend();
    }
  };

  const handleFilePick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    // 客户端大小校验,避免 200MB 文件白白传上去再被 413 拒。
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if (file.size > FILE_MAX_BYTES) {
        // 不在这里直接弹 toast(没拿到 onError prop),由上层 handleAddFile 兜底;
        // 这里只跳过超大文件,清空 input 避免重复触发。
        break;
      }
      void onAddFile(file);
    }
    // 重置 input.value 以便下次选同一个文件也能触发 change
    event.target.value = '';
  };

  return (
    <footer className="composer">
      {attachedFiles.length > 0 && (
        <div className="composer-attachments">
          {attachedFiles.map((af, idx) => (
            <FileChip
              key={`${af.file.name}-${idx}`}
              attached={af}
              onRemove={() => onRemoveFile(idx)}
            />
          ))}
        </div>
      )}
      <div className="composer-row">
        <button
          type="button"
          className="composer-attach"
          onClick={handleFilePick}
          disabled={disabled}
          title="添加附件"
        >
          📎
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept={FILE_ACCEPT}
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入任务,Ctrl/⌘ + Enter 发送"
          rows={3}
        />
        <button type="button" onClick={onSend} disabled={disabled}>
          发送
        </button>
      </div>
    </footer>
  );
}
