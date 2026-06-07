/**
 * Markdown — wraps react-markdown with our standard plugins and a code-block
 * copy button. Pass `streaming` to render as plain text (used during streaming
 * to avoid re-parsing on every delta).
 */

import { useCallback, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github.css';

interface MarkdownProps {
  source: string;
  streaming?: boolean;
  className?: string;
}

export default function Markdown({ source, streaming = false, className }: MarkdownProps) {
  if (streaming) {
    return (
      <div className={`markdown streaming-text ${className ?? ''}`.trim()}>
        <span>{source}</span>
        <span className="cursor-blink" aria-hidden="true" />
      </div>
    );
  }

  return (
    <div className={`markdown ${className ?? ''}`.trim()}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
          pre: ({ children }) => <PreBlock>{children}</PreBlock>,
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

function PreBlock({ children }: { children: ReactNode }) {
  const onCopy = useCallback(() => {
    const text = extractText(children);
    if (!text) return;
    void navigator.clipboard?.writeText(text);
  }, [children]);

  return (
    <div className="md-codeblock">
      <button
        type="button"
        className="md-codeblock-copy"
        aria-label="Copy code to clipboard"
        onClick={onCopy}
      >
        <svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true">
          <rect x="3" y="3" width="8" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.2" fill="none" />
          <path d="M5 3V2a1 1 0 011-1h6a1 1 0 011 1v8a1 1 0 01-1 1h-1" stroke="currentColor" strokeWidth="1.2" fill="none" />
        </svg>
        Copy
      </button>
      <pre>{children}</pre>
    </div>
  );
}

function extractText(node: ReactNode): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (typeof node === 'object' && 'props' in node) {
    const props = (node as { props?: { children?: ReactNode } }).props;
    return extractText(props?.children);
  }
  return '';
}