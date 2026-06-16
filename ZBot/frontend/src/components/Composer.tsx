/**
 * Composer - 消息输入区
 * ChatGPT 风格: 左侧圆形按钮 (idle=send, running=stop)
 */

import { forwardRef, useRef, type KeyboardEvent } from 'react';
import FileChip from './FileChip';
import type { AttachedFile, StringSetter } from '../types';

interface ComposerProps {
  input: string;
  setInput: StringSetter;
  onSend: () => void;
  onStop: () => void;
  isRunning: boolean;
  canSend: boolean;
  attachedFiles: AttachedFile[];
  onAddFile: (_file: File) => void | Promise<void>;
  onRemoveFile: (_index: number) => void;
}

const FILE_ACCEPT = '.txt,.md,.pdf,.png,.jpg,.jpeg,.gif,.webp,.json,.csv,.yaml,.yml,.py,.js,.ts,.tsx,.jsx,.html,.css,.xml,.log';
const FILE_MAX_BYTES = 10 * 1024 * 1024;

export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(
  { input, setInput, onSend, onStop, isRunning, canSend, attachedFiles, onAddFile, onRemoveFile },
  ref,
) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter 发送, Shift+Enter 换行, running 时 Enter 停止
    if (event.key === 'Enter' && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      if (isRunning) {
        onStop();
      } else if (canSend) {
        onSend();
      }
      return;
    }
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      if (!isRunning && canSend) onSend();
    }
  };

  const handleFilePick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      if (file.size > FILE_MAX_BYTES) {
        break;
      }
      void onAddFile(file);
    }
    event.target.value = '';
  };

  const handlePrimaryClick = () => {
    if (isRunning) {
      onStop();
    } else if (canSend) {
      onSend();
    }
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
      <div className="composer-pill">
        <button
          type="button"
          className="composer-attach"
          onClick={handleFilePick}
          disabled={isRunning}
          title="添加附件"
          aria-label="添加附件"
        >
          <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
            <path
              d="M14.5 8.5l-5 5a2.5 2.5 0 003.5 3.5l6-6a4.5 4.5 0 00-6.4-6.4l-7 7a6.5 6.5 0 009.2 9.2l3-3"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept={FILE_ACCEPT}
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
        <textarea
          ref={ref}
          className="composer-textarea"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isRunning ? 'ZBot 正在执行, 按 Enter 停止…' : '输入消息,Enter 发送,Shift+Enter 换行'}
          rows={1}
        />
        <button
          type="button"
          className={`composer-primary ${isRunning ? 'is-stop' : 'is-send'} ${canSend || isRunning ? '' : 'is-disabled'}`}
          onClick={handlePrimaryClick}
          disabled={!isRunning && !canSend}
          aria-label={isRunning ? '停止当前任务' : '发送消息'}
          title={isRunning ? '停止当前任务' : '发送消息'}
        >
          {isRunning ? (
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
              <rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="M3 8h10M9 4l4 4-4 4"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
              />
            </svg>
          )}
        </button>
      </div>
      <p className="composer-hint">Enter 发送 · Shift+Enter 换行 · 附件最大 10 MB</p>
    </footer>
  );
});

export default Composer;