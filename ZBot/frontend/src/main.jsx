// ============================================
// main.jsx —— 应用的入口文件
// ============================================
// 这是整个 React 应用的"起点"，浏览器加载页面时最先执行这个文件

// 导入 React 核心库（创建组件必需）
import React from 'react';

// 导入 ReactDOM，它是 React 专门用于操作浏览器 DOM 的库
// react-dom/client 是 React 18 的新 API（并发模式）
import ReactDOM from 'react-dom/client';

// 导入全局样式文件，这个文件里的 CSS 会影响整个应用
import './index.css';

// 导入根组件 App，整个应用的 UI 都从这里开始
import App from './App';

// 获取 HTML 中 id 为 "root" 的 DOM 元素
// 这个元素通常在 index.html 里，类似：<div id="root"></div>
// createRoot() 是 React 18 的 API，创建一个"根节点"，React 会管理这个节点下的所有内容
const root = ReactDOM.createRoot(document.getElementById('root'));

// render() 方法把 <App /> 组件渲染到 root 节点中
// <App /> 是 JSX 语法，表示创建一个 App 组件的实例
// 执行后，浏览器页面上就会显示 App 组件的内容
root.render(<App />);
