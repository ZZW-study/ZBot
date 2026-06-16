/**
 * LiveStatusMachine - ZBot 改: 把状态机逻辑抽到独立 class.
 *
 * 状态机单向推进规则:
 *   - open 锁打开时, 允许: idle -> thinking -> tool -> finalizing -> idle
 *   - tool/finalizing 一旦进入, 拒绝回退到 thinking
 *   - streaming 阶段: 只压制 LiveStatus 行显示,不锁状态机,
 *     工具事件可以正常推进 (thinking -> streaming -> tool)
 *   - 只有 open() / close() / reset() 才能切换锁状态
 *   - subscribe / snapshot 供 useSyncExternalStore 同步
 *
 * 不依赖 React, 可单测
 */

export type LivePhase = "idle" | "thinking" | "tool" | "finalizing" | "streaming";
export type LockState = "open" | "closed";

export interface LiveStatusSnapshot {
  phase: LivePhase;
  toolName: string;
}

const INITIAL: LiveStatusSnapshot = { phase: "idle", toolName: "" };

export class LiveStatusMachine {
  private _phase: LivePhase = "idle";
  private _toolName: string = "";
  private _lock: LockState = "closed";
  private _listeners = new Set<() => void>();
  private _cachedSnapshot: LiveStatusSnapshot | null = null;

  snapshot(): LiveStatusSnapshot {
    // useSyncExternalStore 内部用 Object.is 比较 snapshot。
    // 每次返回新对象会触发无限渲染循环(React "Maximum update depth exceeded")。
    // 所以 phase/toolName 没变时必须返回上次同一个引用。
    if (
      this._cachedSnapshot === null ||
      this._cachedSnapshot.phase !== this._phase ||
      this._cachedSnapshot.toolName !== this._toolName
    ) {
      this._cachedSnapshot = { phase: this._phase, toolName: this._toolName };
    }
    return this._cachedSnapshot;
  }

  subscribe(listener: () => void): () => void {
    this._listeners.add(listener);
    return () => {
      this._listeners.delete(listener);
    };
  }

  private _notify(): void {
    for (const l of this._listeners) l();
  }

  open(): void {
    this._lock = "open";
    this._phase = "thinking";
    this._toolName = "";
    this._notify();
  }


  /**
   * ZBot 改: 幂等 open - 仅在锁关闭时打开。
   * 作用: task_started 在流式阶段会再次收到,不能无条件重置。
   */
  openIfClosed(): void {
    if (this._lock === "closed") {
      this.open();
    }
  }
  close(): void {
    this._lock = "closed";
    this._phase = "idle";
    this._toolName = "";
    this._notify();
  }

  reset(): void {
    this._lock = "closed";
    this._phase = "idle";
    this._toolName = "";
    this._notify();
  }

  apply(next: LivePhase, nextToolName?: string): LiveStatusSnapshot | null {
    if (this._lock === "closed") return null;

    // 'streaming' 阶段: 只压制 LiveStatus 行显示,不锁状态机。
    // 规则: 仅当处于 thinking 时可进入 streaming; 其它情况拒绝(防止完成后再抖)。
    if (next === "streaming") {
      if (this._phase === "thinking") {
        this._phase = "streaming";
        this._toolName = "";
        this._notify();
        return this.snapshot();
      }
      return null;
    }

    // streaming 是 "假" thinking, 允许随时切到 tool / finalizing (解锁工具事件)
    if (this._phase === "streaming") {
      if (next === "tool") {
        this._phase = "tool";
        if (nextToolName !== undefined) this._toolName = nextToolName;
        this._notify();
        return this.snapshot();
      }
      if (next === "finalizing") {
        this._phase = "finalizing";
        this._toolName = "";
        this._notify();
        return this.snapshot();
      }
      // 其它 (thinking / idle) 拒绝 — 已经在流式, 不需要回退
      return null;
    }

    if (next === "thinking" && (this._phase === "tool" || this._phase === "finalizing")) {
      return null;
    }
    if (next === this._phase) {
      if (next === "tool" && nextToolName !== undefined && nextToolName !== this._toolName) {
        this._toolName = nextToolName;
        this._notify();
        return this.snapshot();
      }
      return null;
    }
    this._phase = next;
    if (next === "tool") {
      if (nextToolName !== undefined) this._toolName = nextToolName;
    } else {
      this._toolName = "";
    }
    this._notify();
    return this.snapshot();
  }
}

export const INITIAL_LIVE_STATUS: LiveStatusSnapshot = INITIAL;

