/**
 * main.jsx — JavaScript 入口文件
 *
 * 执行流程：
 * 1. 浏览器加载 index.html
 * 2. 发现 <script src="/src/main.jsx">，加载并执行此文件
 * 3. ReactDOM.createRoot 找到 HTML 中的 <div id="root">
 * 4. .render(<App />) 把 App 组件渲染进去
 *
 * 注意：React 是单页面应用（SPA），整个项目只有一个 index.html
 * 所有"页面切换"都是 JS 在 #root 里动态替换组件，不是真正的页面跳转
 */

// 导入 npm 包（从 node_modules/ 自动查找）
// 带 'react' 这种不带 ./ 的是 npm 包名，Vite 会自动去 node_modules/ 找
// 带 ./ 的是文件路径（如 './App'）
import React from 'react';
import ReactDOM from 'react-dom/client';

// 导入全局 CSS（带 ./ 的是文件路径）
import './index.css';

// 导入主组件
import App from './App';

// 把 React 应用渲染到 index.html 的 #root div 里
ReactDOM.createRoot(document.getElementById('root')).render(
  // React.StrictMode — 开发模式额外检查（如重复渲染检测），生产环境自动移除
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
