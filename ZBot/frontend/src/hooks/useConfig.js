/**
 * useConfig.js — 配置检测 Hook
 * 应用启动时调用后端 API，检测是否已完成配置
 *
 * 自定义 Hook 的命名规则：必须以 "use" 开头
 * 这样 React 才知道它是一个 Hook，会应用 Hook 的规则
 */

import { useEffect, useMemo, useState } from 'react';

// export function — 具名导出（不是 default）
// 导入时需要写 import { useConfig } from './hooks/useConfig'
export function useConfig() {
  // configured 的三种状态：
  //   null — 正在检测（初始值）
  //   false — 未配置，需要引导用户设置
  //   true — 已配置，可以正常使用
  const [configured, setConfigured] = useState(null);

  // useMemo — 缓存计算结果，只在依赖项变化时重新计算
  // [] 空依赖项 = 只计算一次（组件生命周期内不变）
  const apiBase = useMemo(() => {
    // import.meta.env — Vite 注入的环境变量对象
    // VITE_ 前缀是 Vite 的要求，只有 VITE_ 开头的变量才会暴露给前端
    if (import.meta.env.VITE_ZBOT_API_URL) return import.meta.env.VITE_ZBOT_API_URL;

    // import.meta.env.DEV — 布尔值，开发模式为 true
    if (import.meta.env.DEV) {
      // window.location.protocol — "http:" 或 "https:"
      // window.location.hostname — 主机名（如 "localhost"）
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }

    // 生产模式：空字符串表示同源（前端和后端在同一域名下）
    return '';
  }, []);  // 空数组 = 不依赖任何变量，只执行一次


  // useEffect — 副作用钩子
  // 组件挂载时执行一次（依赖项 [apiBase] 只在挂载时变化一次）
  // 作用：调用后端 API 检测配置状态
  useEffect(() => {
    // fetch — 浏览器内置的 HTTP 请求 API
    // .then() — Promise 链式调用（另一种写法，等价于 async/await）
    //   .then((r) => r.json()) — 响应成功后，解析 JSON
    //   .then((data) => ...) — JSON 解析成功后，更新状态
    //   .catch(() => ...) — 请求失败时，设置为未配置
    // !!data.configured — 双重取反，把任意值转为布尔值
    //   !!null = false, !!undefined = false, !!true = true
    fetch(`${apiBase}/api/config/status`)
      .then((r) => r.json())
      .then((data) => setConfigured(!!data.configured))
      .catch(() => setConfigured(false));
  }, [apiBase]);


  // 返回一个对象，包含状态和修改状态的函数
  // 使用时：const { configured, setConfigured, apiBase } = useConfig();
  return { configured, setConfigured, apiBase };
}
