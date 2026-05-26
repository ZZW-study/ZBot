/**
 * App.jsx — 主组件（应用的"路由控制器"）
 * 作用：根据配置状态决定显示哪个页面
 *
 * 页面流转逻辑：
 *   configured === null  → 显示"正在检测配置..."（加载中）
 *   configured === false → 显示 OnboardPage（首次配置页面）
 *   configured === true  → 显示 ChatPage（聊天页面）
 *   showSettings === true → 显示 OnboardPage（设置页面，可取消）
 */

// useState — React 的状态管理钩子
// 值变了，页面自动更新
// 用法：const [变量名, 修改变量的函数] = useState(初始值)
import { useState } from 'react';

// 导入当前组件的样式
import './App.css';

// 导入自定义 Hook（封装了配置相关的状态逻辑）
import { useConfig } from './hooks/useConfig';

// 导入两个页面组件
import OnboardPage from './pages/OnboardPage';  // 配置页面
import ChatPage from './pages/ChatPage';          // 聊天页面

// App 是一个函数组件——函数返回 JSX（类似 HTML 的语法）就是页面内容
function App() {
  // useConfig() 是自定义 Hook，返回配置相关状态
  // configured: null=加载中, false=未配置, true=已配置
  // setConfigured: 修改 configured 的函数
  // apiBase: 后端 API 地址（如 http://localhost:8000）
  const { configured, setConfigured, apiBase } = useConfig();

  // showSettings: 是否显示设置页面（默认不显示）
  // setShowSettings: 修改 showSettings 的函数
  const [showSettings, setShowSettings] = useState(false);

  // ---- 以下三个 if/return 是条件渲染 ----

  // 状态1：配置检测中（configured === null）
  if (configured === null) {
    return (
      <div className="onboard-page">
        {/* style={{ }} — 内联样式，用 JS 对象表示 CSS */}
        {/* 外层 {} 是 JSX 里嵌入 JS 表达式，内层 {} 是样式对象 */}
        {/* 属性名用驼峰式 camelCase（如 fontSize），不是 CSS 的 kebab-case（font-size） */}
        <p style={{ color: '#69758a', fontSize: '1.1rem' }}>正在检测配置...</p>
      </div>
    );
  }

  // 状态2：未配置 或 用户点了"设置"按钮
  if (!configured || showSettings) {
    return (
      <OnboardPage
        apiBase={apiBase}                    // 传给子组件的 prop（属性）
        isSettings={configured}              // true=设置模式（有取消按钮）, false=首次配置
        // () => { ... } — 箭头函数作为回调传给子组件
        // 子组件在合适时机调用这个函数，实现"子组件通知父组件"
        onConfigured={() => {
          setConfigured(true);               // 标记为已配置
          setShowSettings(false);            // 关闭设置页面
        }}
        // 三元运算符：configured 为 true 时传回调函数，否则传 undefined
        // undefined 表示不传这个 prop，子组件收到 undefined（等同于没传）
        onCancel={configured ? () => setShowSettings(false) : undefined}
      />
    );
  }

  // 状态3：已配置，显示聊天页面
  return (
    <ChatPage
      apiBase={apiBase}
      onOpenSettings={() => setShowSettings(true)}  // 传给子组件，点击时打开设置
    />
  );
}

// export default — 导出这个组件，其他文件 import App 就能用
export default App;
