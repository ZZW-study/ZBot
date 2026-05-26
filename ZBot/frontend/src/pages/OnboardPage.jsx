/**
 * OnboardPage.jsx — 配置页面
 * 首次使用时的设置表单，也可以作为"设置"页面修改配置
 * 功能：选择 LLM 提供商、填写 API Key、API 地址、模型名称
 */

import { useEffect, useState } from 'react';

// const — 常量声明（值不能重新赋值，但对象/数组内部可以修改）
// PROVIDER_OPTIONS — 提供商选项列表，每个是 { value, label } 对象
// 这个数组在组件外面定义，不会随渲染重新创建
const PROVIDER_OPTIONS = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'dashscope', label: 'DashScope（阿里通义）' },
  { value: 'siliconflow', label: 'SiliconFlow' },
];

// { apiBase, onConfigured, onCancel, isSettings = false } — 解构 props
// isSettings = false — 默认值语法，如果父组件没传 isSettings，默认是 false
export default function OnboardPage({ apiBase, onConfigured, onCancel, isSettings = false }) {

  // 表单状态：每个输入框都有对应的 state
  const [provider, setProvider] = useState('deepseek');       // 当前选中的提供商
  const [apiKey, setApiKey] = useState('');                    // API Key 输入框
  const [apiBaseInput, setApiBaseInput] = useState('');        // API 地址输入框
  const [model, setModel] = useState('');                      // 模型名称输入框
  const [defaults, setDefaults] = useState(null);              // 各提供商的默认配置
  const [hasExistingKey, setHasExistingKey] = useState(false); // 是否已有 API Key
  const [saving, setSaving] = useState(false);                 // 是否正在保存
  const [error, setError] = useState('');                      // 错误信息


  // useEffect — 副作用钩子，组件挂载时执行一次（因为依赖项是 [apiBase]）
  // 作用：从后端加载当前配置和默认值
  useEffect(() => {
    // ignore 标志：防止组件卸载后还在更新状态（会导致内存泄漏警告）
    // 这是 React 的常见模式，叫做"cleanup function"
    let ignore = false;

    // async function — 异步函数，内部可以用 await
    // 为什么不在 useEffect 的回调上直接写 async？
    //   因为 useEffect 的回调必须返回 undefined 或清理函数，不能返回 Promise
    //   所以定义一个 async 函数再调用它，这是 React 的常见模式
    async function loadConfig() {
      try {
        // fetch — 浏览器内置的 HTTP 请求 API
        // await — 等待 Promise 完成（类似 Python 的 await）
        // .json() — 把响应体解析为 JSON 对象
        const defaultsRes = await fetch(`${apiBase}/api/config/defaults`);
        const defaultsData = await defaultsRes.json();

        // 如果组件已卸载，不更新状态
        if (ignore) return;
        setDefaults(defaultsData);

        // 加载当前配置
        let current = null;
        const configRes = await fetch(`${apiBase}/api/config`);
        if (configRes.ok) {  // .ok — HTTP 状态码 200-299 为 true
          current = await configRes.json();
        }
        if (ignore) return;

        // ?. 可选链 — 如果 current 是 null/undefined，不报错，返回 undefined
        // || 逻辑或 — 左边是假值时用右边
        const currentProvider = current?.resolvedProvider
          || (current?.provider && current.provider !== 'auto' ? current.provider : 'deepseek');

        // 对象的动态属性访问：current.providers[currentProvider]
        // [] 里可以放变量，. 后面只能放固定属性名
        const providerData = current?.providers?.[currentProvider] || {};

        setProvider(currentProvider);
        setModel(current?.model || defaultsData[currentProvider]?.model_placeholder || '');
        setApiBaseInput(providerData.apiBase || defaultsData[currentProvider]?.api_base || '');
        setHasExistingKey(Boolean(providerData.apiKey));  // Boolean() — 转为布尔值
      } catch {
        // catch — 捕获 try 块中的任何错误
        if (ignore) return;
        setApiBaseInput('');
        setModel('');
      }
    }

    loadConfig();

    // return 的函数是"清理函数"，组件卸载时执行
    // 作用：设置 ignore = true，阻止异步操作完成后更新已卸载组件的状态
    return () => {
      ignore = true;
    };
  }, [apiBase]);  // 依赖项 [apiBase]：apiBase 变化时重新执行


  // 切换提供商时自动填充默认值
  const handleProviderChange = (value) => {
    setProvider(value);
    // defaults[value] — 动态属性访问
    if (defaults && defaults[value]) {
      setApiBaseInput(defaults[value].api_base || '');
      setModel(defaults[value].model_placeholder || '');
    }
    setHasExistingKey(false);
    setApiKey('');
  };


  // canSave — 是否可以保存（派生状态，不需要 useState）
  // && 逻辑与：全部为 true 才返回 true
  // || 逻辑或：有一个为 true 就返回 true
  // .trim().length > 0 — 去掉空格后长度大于 0（即不为空）
  const canSave = model.trim().length > 0
    && apiBaseInput.trim().length > 0
    && (hasExistingKey || apiKey.trim().length > 0)
    && !saving;


  // handleSave — 保存配置（异步函数）
  const handleSave = async () => {
    if (!canSave) return;

    setSaving(true);   // 显示"保存中..."
    setError('');      // 清除之前的错误

    // 构造请求体对象
    // [provider] — 计算属性名（用变量的值作为对象的 key）
    //   例如 provider = 'deepseek' 时，结果是 { deepseek: { apiKey, apiBase } }
    const body = {
      model: model.trim(),
      provider,
      providers: {
        [provider]: {
          apiKey: apiKey.trim(),
          apiBase: apiBaseInput.trim(),
        },
      },
    };

    try {
      // fetch 发送 PUT 请求
      // method: 'PUT' — HTTP 方法
      // headers — 请求头
      // body: JSON.stringify(body) — 把对象转为 JSON 字符串
      const res = await fetch(`${apiBase}/api/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        // .catch(() => ({})) — 如果 JSON 解析失败，返回空对象
        const detail = await res.json().catch(() => ({}));

        // typeof — 获取值的类型（返回 "string"、"number"、"object" 等）
        // 三元运算符：条件 ? 真值 : 假值
        const message = typeof detail.detail === 'string'
          ? detail.detail
          : detail.detail?.message || detail.reason || '保存失败，请检查配置。';

        // throw new Error() — 抛出错误，会被外层 catch 捕获
        throw new Error(message);
      }

      // 保存成功，调用父组件传来的回调
      onConfigured();
    } catch (err) {
      // err.message — Error 对象的 message 属性
      setError(err.message || '保存失败，请检查网络连接。');
    } finally {
      // finally — 无论成功失败都执行（类似 Python 的 finally）
      setSaving(false);
    }
  };


  // 键盘事件处理：Ctrl+Enter 或 Cmd+Enter 触发保存
  // e 是事件对象，包含按键信息
  // e.key — 按下的键名（如 "Enter"）
  // e.ctrlKey — 是否按了 Ctrl
  // e.metaKey — 是否按了 Cmd（Mac）
  // e.preventDefault() — 阻止浏览器默认行为（如表单提交）
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSave();
    }
  };


  // ═══════════════════════════════════════════════════════
  // 渲染 JSX
  // ═══════════════════════════════════════════════════════

  // {} 花括号在 JSX 里嵌入 JS 表达式
  // {isSettings ? 'ZBot 设置' : 'ZBot 初始化配置'} — 三元运算符动态显示标题
  // {error && <p>...</p>} — 短路求值：error 为真值时才渲染 <p>
  // {onCancel && <button>...</button>} — onCancel 存在时才渲染按钮
  // onChange={(e) => setApiKey(e.target.value)} — 输入框变化时更新状态
  //   e.target — 触发事件的元素（即 <input>）
  //   e.target.value — 输入框的当前值
  return (
    <div className="onboard-page">
      <div className="onboard-card">
        <div className="onboard-brand">
          <div className="brand-mark">Z</div>
          <h1>{isSettings ? 'ZBot 设置' : 'ZBot 初始化配置'}</h1>
          <p>{isSettings ? '修改当前会话使用的 LLM 提供商、模型和 API 地址。' : '首次使用需要配置 LLM 提供商和模型。'}</p>
        </div>

        {/* onKeyDown — 键盘按下事件，绑在整个表单上 */}
        <div className="onboard-form" onKeyDown={handleKeyDown}>
          <label className="onboard-label">
            <span>LLM 提供商</span>
            {/* <select> — 下拉选择框 */}
            {/* value={provider} — 当前选中的值（受控组件） */}
            {/* onChange — 选项变化时调用 handleProviderChange */}
            <select value={provider} onChange={(e) => handleProviderChange(e.target.value)}>
              {/* .map() — 把数组的每个元素转换为 JSX */}
              {/* key={opt.value} — 列表项的唯一标识，React 用它高效更新 DOM */}
              {PROVIDER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>

          <label className="onboard-label">
            <span>API Key</span>
            <input
              type="password"                              // 密码输入框（显示圆点）
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={hasExistingKey ? '留空则保留已有 API Key' : 'sk-...'}
              autoComplete="off"                           // 关闭浏览器自动填充
            />
          </label>

          <label className="onboard-label">
            <span>API Base URL</span>
            <input
              type="text"
              value={apiBaseInput}
              onChange={(e) => setApiBaseInput(e.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </label>

          <label className="onboard-label">
            <span>模型名称</span>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              // defaults?.[provider] — 可选链 + 动态属性访问
              placeholder={defaults?.[provider]?.model_placeholder || 'deepseek-chat'}
            />
          </label>

          {/* 短路求值：error 为真值时才渲染错误提示 */}
          {error && <p className="onboard-error">{error}</p>}

          <button
            className="onboard-submit"
            type="button"
            onClick={handleSave}
            disabled={!canSave}  // 不能保存时禁用按钮
          >
            {/* 根据状态动态显示按钮文字 */}
            {saving ? '保存中...' : (isSettings ? '保存设置' : '保存配置并开始')}
          </button>

          {/* onCancel 存在时才显示"返回聊天"按钮 */}
          {onCancel && (
            <button className="onboard-secondary" type="button" onClick={onCancel} disabled={saving}>
              返回聊天
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
