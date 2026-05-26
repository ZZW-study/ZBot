import { useEffect, useState } from 'react';

const PROVIDER_OPTIONS = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'dashscope', label: 'DashScope（阿里通义）' },
  { value: 'siliconflow', label: 'SiliconFlow' },
];

export default function OnboardPage({ apiBase, onConfigured, onCancel, isSettings = false }) {
  const [provider, setProvider] = useState('deepseek');
  const [apiKey, setApiKey] = useState('');
  const [apiBaseInput, setApiBaseInput] = useState('');
  const [model, setModel] = useState('');
  const [defaults, setDefaults] = useState(null);
  const [hasExistingKey, setHasExistingKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // 加载各 provider 的默认 api_base
  useEffect(() => {
    let ignore = false;

    async function loadConfig() {
      try {
        const defaultsRes = await fetch(`${apiBase}/api/config/defaults`);
        const defaultsData = await defaultsRes.json();
        if (ignore) return;
        setDefaults(defaultsData);

        let current = null;
        const configRes = await fetch(`${apiBase}/api/config`);
        if (configRes.ok) {
          current = await configRes.json();
        }
        if (ignore) return;

        const currentProvider = current?.resolvedProvider
          || (current?.provider && current.provider !== 'auto' ? current.provider : 'deepseek');
        const providerData = current?.providers?.[currentProvider] || {};

        setProvider(currentProvider);
        setModel(current?.model || defaultsData[currentProvider]?.model_placeholder || '');
        setApiBaseInput(providerData.apiBase || defaultsData[currentProvider]?.api_base || '');
        setHasExistingKey(Boolean(providerData.apiKey));
      } catch {
        if (ignore) return;
        setApiBaseInput('');
        setModel('');
      }
    }

    loadConfig();
    return () => {
      ignore = true;
    };
  }, [apiBase]);

  // 切换 provider 时自动填充默认值
  const handleProviderChange = (value) => {
    setProvider(value);
    if (defaults && defaults[value]) {
      setApiBaseInput(defaults[value].api_base || '');
      setModel(defaults[value].model_placeholder || '');
    }
    setHasExistingKey(false);
    setApiKey('');
  };

  const canSave = model.trim().length > 0
    && apiBaseInput.trim().length > 0
    && (hasExistingKey || apiKey.trim().length > 0)
    && !saving;

  const handleSave = async () => {
    if (!canSave) return;
    setSaving(true);
    setError('');

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
      const res = await fetch(`${apiBase}/api/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        const message = typeof detail.detail === 'string'
          ? detail.detail
          : detail.detail?.message || detail.reason || '保存失败，请检查配置。';
        throw new Error(message);
      }
      onConfigured();
    } catch (err) {
      setError(err.message || '保存失败，请检查网络连接。');
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSave();
    }
  };

  return (
    <div className="onboard-page">
      <div className="onboard-card">
        <div className="onboard-brand">
          <div className="brand-mark">Z</div>
          <h1>{isSettings ? 'ZBot 设置' : 'ZBot 初始化配置'}</h1>
          <p>{isSettings ? '修改当前会话使用的 LLM 提供商、模型和 API 地址。' : '首次使用需要配置 LLM 提供商和模型。'}</p>
        </div>

        <div className="onboard-form" onKeyDown={handleKeyDown}>
          <label className="onboard-label">
            <span>LLM 提供商</span>
            <select value={provider} onChange={(e) => handleProviderChange(e.target.value)}>
              {PROVIDER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>

          <label className="onboard-label">
            <span>API Key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={hasExistingKey ? '留空则保留已有 API Key' : 'sk-...'}
              autoComplete="off"
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
              placeholder={defaults?.[provider]?.model_placeholder || 'deepseek-chat'}
            />
          </label>

          {error && <p className="onboard-error">{error}</p>}

          <button
            className="onboard-submit"
            type="button"
            onClick={handleSave}
            disabled={!canSave}
          >
            {saving ? '保存中...' : (isSettings ? '保存设置' : '保存配置并开始')}
          </button>
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
