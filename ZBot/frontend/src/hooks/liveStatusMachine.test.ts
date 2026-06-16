/**
 * LiveStatusMachine 单测
 *
 * 零依赖(node --experimental-strip-types 直接跑),覆盖状态机的核心不变量:
 *   - 初始 close 锁拒所有 apply
 *   - thinking -> tool 允许
 *   - tool/finalizing -> thinking 一律拒绝
 *   - tool 同名 no-op 不触发 listener
 *   - tool 换名只更名
 *   - close/reset 后所有 apply 拒
 *   - 多轮工具调用 + 中途推 thinking 不回退
 *   - streaming 阶段正确门控
 *   - useSyncExternalStore contract: stable reference
 *
 * 跑法: node --experimental-strip-types liveStatusMachine.test.ts
 */
// @ts-expect-error -- node --experimental-strip-types 下需要显式 .ts 后缀
import { LiveStatusMachine } from "./liveStatusMachine.ts";

let pass = 0, fail = 0;
function eq(label: string, actual: unknown, expected: unknown): void {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) { pass++; console.log(`  PASS  ${label}: ${a}`); }
  else { fail++; console.log(`  FAIL  ${label}: actual=${a} expected=${e}`); }
}

{ const m = new LiveStatusMachine();
  eq("init phase=idle", m.snapshot().phase, "idle");
  eq("init close 锁拒 apply", m.apply("thinking"), null);
  eq("close 锁后 仍 idle", m.snapshot().phase, "idle");
}
{ const m = new LiveStatusMachine(); m.open();
  eq("open -> thinking", m.snapshot().phase, "thinking");
  eq("open -> toolName=''", m.snapshot().toolName, "");
}
{ const m = new LiveStatusMachine(); m.open();
  const r = m.apply("tool", "search_web");
  eq("thinking -> tool ok", r?.phase, "tool");
  eq("thinking -> tool name", r?.toolName, "search_web");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web");
  const r = m.apply("thinking");
  eq("tool -> thinking 拒", r, null);
  eq("拒后 仍 tool", m.snapshot().phase, "tool");
  eq("拒后 仍 search_web", m.snapshot().toolName, "search_web");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web");
  let n = 0; m.subscribe(() => n++);
  const r = m.apply("tool", "search_web");
  eq("tool 同名 no-op=null", r, null);
  eq("tool 同名 不触发 listener", n, 0);
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web");
  const r = m.apply("tool", "read_file");
  eq("tool 换名 -> read_file", r?.toolName, "read_file");
  eq("tool 换名 仍 tool", r?.phase, "tool");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web");
  const r = m.apply("finalizing");
  eq("tool -> finalizing", r?.phase, "finalizing");
  eq("tool -> finalizing 清 toolName", r?.toolName, "");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web"); m.apply("finalizing");
  eq("finalizing -> thinking 拒", m.apply("thinking"), null);
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web"); m.apply("finalizing");
  const r = m.apply("tool", "read_file");
  eq("finalizing -> tool 允许", r?.phase, "tool");
  eq("finalizing -> tool 换名", r?.toolName, "read_file");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web"); m.close();
  eq("close 后 idle", m.snapshot().phase, "idle");
  eq("close 后 toolName=''", m.snapshot().toolName, "");
  eq("close 后 apply(tool) 拒", m.apply("tool", "x"), null);
  eq("close 后 apply(thinking) 拒", m.apply("thinking"), null);
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web"); m.reset();
  eq("reset -> idle", m.snapshot().phase, "idle");
  eq("reset -> ''", m.snapshot().toolName, "");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web");
  m.apply("tool", "read_file");
  m.apply("finalizing");
  m.apply("tool", "curl");
  eq("多轮 终态=tool", m.snapshot().phase, "tool");
  eq("多轮 终态=curl", m.snapshot().toolName, "curl");
  m.apply("thinking");
  eq("中途 thinking 不回退 仍 tool", m.snapshot().phase, "tool");
  eq("中途 thinking 不回退 仍 curl", m.snapshot().toolName, "curl");
}
{ const m = new LiveStatusMachine();
  let n = 0; m.subscribe(() => n++);
  m.open(); m.apply("tool", "x"); m.apply("tool", "y"); m.close();
  eq("listener 触发 4 次", n, 4);
}

// 14) useSyncExternalStore contract: stable reference
{ const m = new LiveStatusMachine();
  const a = m.snapshot();
  const b = m.snapshot();
  eq("idle 状态 snapshot() === snapshot()", a === b, true);
  m.open();
  const c = m.snapshot();
  eq("open 后 snapshot 是新对象", c !== a, true);
  const d = m.snapshot();
  eq("open 后第二次 snapshot 稳定", c === d, true);
  m.apply("tool", "search_web");
  const e2 = m.snapshot();
  eq("切到 tool 后 snapshot 是新对象", e2 !== c, true);
  const f = m.snapshot();
  eq("tool 状态稳定", e2 === f, true);
  m.apply("tool", "search_web"); // 同名 no-op
  const g = m.snapshot();
  eq("tool 同名 apply 不出新对象", g === f, true);
  m.apply("tool", "read_file"); // 换名
  const h = m.snapshot();
  eq("tool 换名出新对象", h !== g, true);
  eq("换名后 name 正确", h.toolName, "read_file");
  m.apply("finalizing");
  const i2 = m.snapshot();
  eq("finalizing 出新对象", i2 !== h, true);
  const j = m.snapshot();
  eq("finalizing 稳定", i2 === j, true);
  m.close();
  const k = m.snapshot();
  eq("close 出新对象", k !== i2, true);
  eq("close 后 phase=idle", k.phase, "idle");
}
{ const m = new LiveStatusMachine();
  m.open();
  m.apply("tool", "curl");
  const a = m.snapshot();
  m.reset();
  const b = m.snapshot();
  eq("reset 出新对象", b !== a, true);
  eq("reset 后 phase=idle", b.phase, "idle");
  const c = m.snapshot();
  eq("reset 后 idle 稳定", c === b, true);
}
{ const m = new LiveStatusMachine();
  const a = m.snapshot();
  const b = m.snapshot();
  const c = m.snapshot();
  eq("从未 open 状态 snapshot 三次都同引用", a === b && b === c, true);
}

// 17-20) streaming 阶段门控
{ const m = new LiveStatusMachine(); m.open();
  const r = m.apply("streaming");
  eq("thinking -> streaming 允许", r?.phase, "streaming");
  eq("streaming -> toolName=''", r?.toolName, "");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web");
  const r = m.apply("streaming");
  eq("tool -> streaming 拒", r, null);
  eq("拒后 仍 tool", m.snapshot().phase, "tool");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("streaming");
  const r = m.apply("tool", "read_file");
  eq("streaming -> tool 允许", r?.phase, "tool");
  eq("streaming -> tool 换名", r?.toolName, "read_file");
}
{ const m = new LiveStatusMachine(); m.open();
  m.apply("tool", "search_web"); m.close();
  const r = m.apply("streaming");
  eq("close 后 apply(streaming) 拒", r, null);
  eq("拒后 idle", m.snapshot().phase, "idle");
}

console.log(`\n=== ${pass} pass, ${fail} fail ===`);
if (fail > 0) {
  throw new Error(`${fail} state machine test(s) failed`);
}
