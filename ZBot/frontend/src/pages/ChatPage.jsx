/**
 * ChatPage.jsx — 聊天页面
 * 管理消息、WebSocket 连接、会话名称，组合所有子组件
 */

// ═══════════════════════════════════════════════════════════
// 导入
// ═══════════════════════════════════════════════════════════

// { } 是解构导入：从包里只取出需要的函数
// 不写 { } 就是导入包的默认导出
import { useCallback, useMemo, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import Sidebar from '../components/Sidebar';
import MessageList from '../components/MessageList';
import Composer from '../components/Composer';
import ActivityPanel from '../components/ActivityPanel';


// ═══════════════════════════════════════════════════════════
// 组件定义
// ═══════════════════════════════════════════════════════════

// export default — 导出这个函数，其他文件 import ChatPage 就能用
// { onOpenSettings } — 解构赋值，从 props 对象中取出 onOpenSettings 属性
//   等价于：function ChatPage(props) { const onOpenSettings = props.onOpenSettings; }
export default function ChatPage({ onOpenSettings }) {


  // ═══════════════════════════════════════════════════════
  // useState — 定义响应式变量
  // ═══════════════════════════════════════════════════════

  // 语法：const [变量名, 修改变量的函数] = useState(初始值)
  // 为什么不能直接 messages = [] ？
  //   因为 React 需要知道"状态变了"才会重新渲染页面。
  //   只有调用 setMessages([...]) 才会触发重新渲染。

  // 消息列表，每个元素是 { id: string, role: string, content: string }
  const [messages, setMessages] = useState([]);

  // AI 正在生成的流式文本（逐字显示用）
  const [streamingContent, setStreamingContent] = useState('');

  // 用户输入框的内容
  const [input, setInput] = useState('');

  // 当前会话名称
  const [sessionName, setSessionName] = useState('default');


  // ═══════════════════════════════════════════════════════
  // useMemo — 缓存计算结果
  // ═══════════════════════════════════════════════════════

  // 语法：const 值 = useMemo(() => { return 计算结果 }, [依赖项])
  // 作用：只在依赖项变化时重新计算，否则返回上次缓存的结果
  // 第二个参数 [] 表示没有依赖项，只计算一次
  const wsUrl = useMemo(() => {
    // import.meta.env — Vite 的环境变量对象
    // .DEV — Vite 自动设置，开发模式为 true
    // .VITE_ 前缀 — Vite 要求自定义变量必须以 VITE_ 开头
    if (import.meta.env.VITE_ZBOT_WS_URL) return import.meta.env.VITE_ZBOT_WS_URL;

    // window.location — 浏览器当前页面的 URL 信息
    // .protocol — "http:" 或 "https:"
    // === 严格相等（不会自动类型转换）
    // ? : 三元运算符 — 条件 ? 真值 : 假值
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';

    if (import.meta.env.DEV) {
      // `反引号` 是模板字符串，${} 里可以写 JS 表达式
      // window.location.hostname — 主机名（如 "localhost"）
      return `${protocol}://${window.location.hostname}:8000/api/agent/ws`;
    }

    // window.location.host — 主机名+端口（如 "localhost:5173"）
    return `${protocol}://${window.location.host}/api/agent/ws`;
  }, []);


  // ═══════════════════════════════════════════════════════
  // useCallback — 缓存函数
  // ═══════════════════════════════════════════════════════

  // 语法：const 函数名 = useCallback(() => { ... }, [依赖项])
  // 和 useMemo 的区别：
  //   useMemo 缓存计算结果（值）
  //   useCallback 缓存函数本身
  // 第二个参数 [] 表示不依赖任何外部变量，函数只创建一次

  // AI 回复完成时调用
  const handleCompleted = useCallback((event) => {
    // ?. 可选链：如果 event.payload 是 null/undefined，不报错，返回 undefined
    // || 逻辑或：如果左边是假值（null/undefined/""/0/false），用右边的值
    const finalContent = event.payload?.final_content || event.message;

    setStreamingContent('');

    // setMessages((prev) => [...]) — 函数式更新
    //   prev 是当前最新的 messages 值
    //   这样保证基于最新状态操作，不会拿到旧值
    // ...prev — 展开运算符，把数组所有元素展开到新数组里
    //   [...prev, newItem] = 原有元素 + 新元素
    setMessages((prev) => [
      ...prev,
      {
        id: `${event.run_id}-${event.created_at}-assistant`, // 模板字符串拼接
        role: 'assistant',
        content: finalContent,
      },
    ]);
  }, []);


  // AI 回复失败时调用
  const handleFailed = useCallback((event) => {
    setStreamingContent('');
    setMessages((prev) => [
      ...prev,
      {
        id: `${event.run_id}-${event.created_at}-error`,
        role: 'assistant',
        content: event.message,
      },
    ]);
  }, []);


  // AI 开始回复时调用
  const handleStarted = useCallback(() => {
    setStreamingContent('');
  }, []);


  // 收到流式文本片段时调用（逐字显示效果）
  // ?? 空值合并运算符：只处理 null 和 undefined（比 || 更精确）
  //   || 会把 0 和 "" 也当成假值，?? 不会
  const handleDelta = useCallback((event) => {
    const delta = event.payload?.delta ?? event.message ?? '';

    // !delta — 如果是假值（空字符串/null/undefined），直接返回
    if (!delta) return;

    // (prev) => `${prev}${delta}` — 把新片段追加到已有内容末尾
    setStreamingContent((prev) => `${prev}${delta}`);
  }, []);


  // ═══════════════════════════════════════════════════════
  // 使用 useWebSocket Hook
  // ═══════════════════════════════════════════════════════

  // Hook 调用返回一个对象，用解构取出需要的属性
  // 等价于：
  //   const ws = useWebSocket(wsUrl, { ... });
  //   const socketState = ws.socketState;
  //   const events = ws.events;
  //   ...
  const {
    socketState,  // string: 'connecting' | 'connected' | 'disconnected' | 'error'
    events,       // array: 事件列表
    isRunning,    // boolean: 是否正在运行
    activeRunId,  // string: 当前运行 ID
    sendMessage,  // function: 发送消息
    stopRun,      // function: 停止运行
    reconnect,    // function: 重新连接
  } = useWebSocket(wsUrl, {
    // 把回调函数作为参数传给 Hook
    onCompleted: handleCompleted,
    onDelta: handleDelta,
    onFailed: handleFailed,
    onStarted: handleStarted,
  });


  // ═══════════════════════════════════════════════════════
  // 发送消息
  // ═══════════════════════════════════════════════════════

  // 依赖项 [input, sessionName, sendMessage]：
  //   这三个值任何一个变化，函数就重新创建
  //   因为函数体内用到了这三个变量
  const handleSend = useCallback(() => {
    // .trim() — 去掉首尾空格
    const content = input.trim();

    // 如果为空直接返回（不发送）
    if (!content) return;

    // crypto.randomUUID() — 浏览器内置 API，生成随机 UUID
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content }]);

    // 清空输入框
    setInput('');

    // || 'default' — 如果 sessionName 为空，用 'default'
    sendMessage(content, sessionName.trim() || 'default');
  }, [input, sessionName, sendMessage]);


  // ═══════════════════════════════════════════════════════
  // 派生状态（根据其他状态计算出来的值）
  // ═══════════════════════════════════════════════════════

  // && 逻辑与：全部为 true 才返回 true
  // ! 逻辑非：取反
  // .length 字符串长度
  const canSend = socketState === 'connected' && !isRunning && input.trim().length > 0;

  // events[0] — 数组第一个元素
  // || null — 如果 undefined 则用 null
  const latestEvent = events[0] || null;


  // ═══════════════════════════════════════════════════════
  // 渲染 JSX
  // ═══════════════════════════════════════════════════════

  // JSX 语法：
  //   <main> — HTML 标签
  //   className — CSS 类名（不是 class，因为 class 是 JS 保留字）
  //   <Sidebar /> — 自定义组件（首字母大写）
  //   onClick={fn} — 点击事件绑定
  //   disabled={bool} — 布尔属性，true 时禁用元素
  //   {value} — 在 JSX 里嵌入 JS 表达式
  //   {/* 注释 */} — JSX 里的注释写法
  return (
    <main className="shell">
      <Sidebar
        sessionName={sessionName}       // 当前会话名
        setSessionName={setSessionName} // 修改会话名的函数
        socketState={socketState}       // WebSocket 连接状态
        isRunning={isRunning}           // 是否正在运行
        activeRunId={activeRunId}       // 当前运行 ID
        onReconnect={reconnect}         // 重新连接回调
        onOpenSettings={onOpenSettings} // 打开设置回调
      />

      <section className="chat">
        <header className="chat-header">
          <h2>对话</h2>
          <button className="stop-button" type="button" onClick={stopRun} disabled={!isRunning}>
            停止
          </button>
        </header>

        <MessageList
          messages={messages}
          isRunning={isRunning}
          latestEvent={latestEvent}
          streamingContent={streamingContent}
        />

        <Composer
          input={input}       // 输入框当前值
          setInput={setInput} // 修改输入框值的函数
          onSend={handleSend} // 发送回调
          disabled={!canSend} // 是否禁用
        />
      </section>

      <ActivityPanel events={events} />
    </main>
  );
}
