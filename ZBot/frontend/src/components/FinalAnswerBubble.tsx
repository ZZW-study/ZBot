/**
 * FinalAnswerBubble - 任务完成后的白气泡, 用分块动画渐进显示 final_content.
 *
 * 行为:
 *   - 父组件传 finalContent 进来 (task_complete 时一次性写入 turn)
 *   - 组件内部用 useState 维护 displayed, 通过 requestAnimationFrame
 *     每帧推进几个字符, 模拟流式
 *   - 字符推进完成后, 切到普通 Markdown 渲染 (光标消失, 链接可点)
 *
 * 注意: 分块期间使用纯文本 + 流式光标, 不解析 Markdown. 这样可以避免
 * 字符在标签中间截断造成的渲染抖动 (spec 风险章节).
 */

import { useEffect, useRef, useState } from 'react';
import Markdown from './Markdown';

interface Props {
  finalContent: string;
}

const CHARS_PER_FRAME = 3;

export default function FinalAnswerBubble({ finalContent }: Props) {
  const [displayed, setDisplayed] = useState('');
  const [isChunking, setIsChunking] = useState(true);
  const rafRef = useRef<number | null>(null);
  const lastFrameTimeRef = useRef<number>(0);
  const targetRef = useRef<string>('');
  // ZBot 改: 记录上次已动画的 finalContent。相同内容不重置,新内容才重置。
  // 修复连续消息时偶发的「气泡空白闪烁」bug。
  const lastAnimatedContentRef = useRef<string>('');

  useEffect(() => {
    if (!finalContent) {
      setDisplayed('');
      setIsChunking(true);
      targetRef.current = '';
      lastAnimatedContentRef.current = '';
      return;
    }
    if (finalContent === lastAnimatedContentRef.current) {
      return; // 相同内容,跳过重置
    }
    // 新内容到达:重置
    lastAnimatedContentRef.current = finalContent;
    targetRef.current = finalContent;
    setDisplayed('');
    setIsChunking(true);
    lastFrameTimeRef.current = 0;
  }, [finalContent]);

  useEffect(() => {
    if (!isChunking) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      return;
    }

    const tick = (now: number) => {
      if (lastFrameTimeRef.current === 0 || now - lastFrameTimeRef.current >= 16) {
        lastFrameTimeRef.current = now;
        setDisplayed((prev) => {
          const target = targetRef.current;
          if (prev.length >= target.length) {
            return prev;
          }
          const next = target.slice(0, prev.length + CHARS_PER_FRAME);
          if (next.length >= target.length) {
            queueMicrotask(() => setIsChunking(false));
          }
          return next;
        });
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [isChunking]);

  if (!finalContent) return null;

  if (isChunking) {
    return (
      <div className="final-answer-bubble final-answer-bubble--chunking" role="status" aria-live="polite">
        <div className="markdown streaming-text">
          <span>{displayed}</span>
          <span className="cursor-blink" aria-hidden="true" />
        </div>
      </div>
    );
  }

  return (
    <div className="final-answer-bubble">
      <Markdown source={finalContent} />
    </div>
  );
}
