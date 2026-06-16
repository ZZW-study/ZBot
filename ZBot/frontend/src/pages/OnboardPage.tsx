/**
 * OnboardPage.jsx — 配置页面
 * 同时用于初始配置和修改设置。
 */

import { useEffect, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { createApiClient } from '../lib/api';
import type { ConfigDefaults, ConfigPatch } from '../types';

const PROVIDER_OPTIONS = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'dashscope', label: 'DashScope（阿里通义）' },
  { value: 'siliconflow', label: 'SiliconFlow' },
  { value: 'minimax', label: 'MiniMax (default)' },
];

// 后端 /api/config/defaults 没列出的 provider 时，前端兌底。
// 关键：minimax 实际上是一个 provider 名，后端会原样写进 config.json。
const FALLBACK_DEFAULTS: Record<string, { api_base: string; model_placeholder: string }> = {
  minimax: { api_base: 'https://api.MiniMax.chat/v1', model_placeholder: 'MiniMax-M3' },
};

interface OnboardPageProps {
  apiBase: string;
  isSettings?: boolean | null;
  onConfigured?: () => void;
}

export default function OnboardPage({ apiBase, isSettings = false, onConfigured }: OnboardPageProps) {
  const navigate = useNavigate();
  const [provider, setProvider] = useState('deepseek');
  const [apiKey, setApiKey] = useState('');
  const [apiBaseInput, setApiBaseInput] = useState('');
  const [model, setModel] = useState('');
  const [defaults, setDefaults] = useState<ConfigDefaults | null>(null);
  const [hasExistingKey, setHasExistingKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let ignore = false;
    const api = createApiClient(apiBase);

    async function loadConfig() {
      try {
        const defaultsData = await api.config.defaults();
        if (ignore) return;
        setDefaults(defaultsData);

        let current = null;
        try {
          current = await api.config.get();
        } catch (err) {
          // 配置可能尚未存在 — 但如果是非 404 错误(网络、500 等),
          // 要给用户提示,而不是静默回退到默认值。
          const status = (err as { status?: number })?.status;
          if (status && status !== 404) {
            setError(`读取现有配置失败: ${err instanceof Error ? err.message : '未知错误'}`);
          }
        }
        if (ignore) return;

        const currentProvider = current?.resolvedProvider
          || (current?.provider && current.provider !== 'auto' ? current.provider : 'deepseek');

        const providerData = current?.providers?.[currentProvider] || {};

        setProvider(currentProvider);
        setModel(current?.model || defaultsData[currentProvider]?.model_placeholder || '');
        setApiBaseInput(providerData.apiBase || defaultsData[currentProvider]?.api_base || '');
        setHasExistingKey(Boolean(providerData.apiKey));

        // 智能修复：后端 status 说 provider 不可识别时,
        // 优先选 dashscope(用户最常用且 base 真实),其他有非空 key 的也可用.
        const reason = current?.reason || '';
        if (reason.includes('provider') && current?.providers) {
          // 优先级: dashscope > 其他有非空 key 的
          const candidate = ['dashscope', ...Object.keys(defaultsData)].find(
            (k) => k !== 'dashscope' || (current.providers?.[k]?.apiKey || '').length > 0,
          ) || Object.keys(defaultsData).find((k) => (current.providers?.[k]?.apiKey || '').length >= 8);
          const knownWithKey = candidate && (current.providers?.[candidate]?.apiKey || '').length >= 8 ? candidate : null;
          if (knownWithKey && knownWithKey !== currentProvider) {
            setProvider(knownWithKey);
            const fb2 = FALLBACK_DEFAULTS[knownWithKey];
            setApiBaseInput(
              (current.providers[knownWithKey]?.apiBase) || defaultsData[knownWithKey]?.api_base || fb2?.api_base || '',
            );
            setModel(
              current?.model || defaultsData[knownWithKey]?.model_placeholder || fb2?.model_placeholder || '',
            );
            setHasExistingKey(true);
            setError(`检测到当前 provider (${currentProvider || 'unknown'}) 无法识别，已自动切换到 ${knownWithKey}（已有 API Key）。请检查 base URL / model 后保存。`);
          }
        }
      } catch (err) {
        if (ignore) return;
        setError(err instanceof Error ? err.message : '加载配置失败');
        setApiBaseInput('');
        setModel('');
      }
    }

    loadConfig();
    return () => { ignore = true; };
  }, [apiBase]);


  const handleProviderChange = (value: string) => {
    setProvider(value);
    const fromBackend = defaults && defaults[value];
    const fallback = FALLBACK_DEFAULTS[value];
    setApiBaseInput(fromBackend?.api_base || fallback?.api_base || '');
    setModel(fromBackend?.model_placeholder || fallback?.model_placeholder || '');
    setHasExistingKey(false);
  };

  const canSave = model.trim().length > 0
    && apiBaseInput.trim().length > 0
    && (hasExistingKey || apiKey.trim().length > 0)
    && !saving;

  const handleSave = async () => {
    if (!canSave) return;

    setSaving(true);
    setError('');

    const api = createApiClient(apiBase);
    const body: ConfigPatch = {
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
      await api.config.save(body);
      onConfigured?.();
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败，请检查网络连接。');
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
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
              placeholder={FALLBACK_DEFAULTS[provider]?.model_placeholder || 'deepseek-chat'}
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

          {isSettings && (
            <button
              className="onboard-secondary"
              type="button"
              onClick={() => navigate('/')}
              disabled={saving}
            >
              返回聊天
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
