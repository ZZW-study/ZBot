/**
 * App —— 带路由的根组件
 * 路由:/  -> ChatPage（已配置时）,/onboard -> OnboardPage
 *
 * 关键设计：useConfig 用模块级单例 + useSyncExternalStore 共享 config status。
 * 整个应用只拉一次 /api/config/status。OnboardPage 保存配置后调 refetch(),
 * App 重新评估路由,自动从 /onboard 跳到 /。
 */
import './App.css';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useConfig } from './hooks/useConfig';
import { useMcpConnection } from './hooks/useMcpConnection';
import { ConfigContextProvider } from './hooks/useConfigContext';
import OnboardPage from './pages/OnboardPage';
import ChatPage from './pages/ChatPage';
import ToastViewport from './components/Toast';

function App() {
  const { exists, configured, reason, apiBase, model, refetch } = useConfig();
  useMcpConnection(apiBase);

  if (exists === null) {
    return (
      <div className="onboard-page">
        <p style={{ color: 'var(--color-muted-foreground)', fontSize: '1.1rem' }}>正在检测配置...</p>
      </div>
    );
  }

  return (
    <ConfigContextProvider
      value={{ exists, configured, reason, apiBase, model, refetch }}
    >
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={configured ? <ChatPage /> : <Navigate to="/onboard" replace />}
          />
          <Route
            path="/onboard"
            element={
              <OnboardPage
                apiBase={apiBase}
                isSettings={configured}
                onConfigured={() => { void refetch(); }}
              />
            }
          />
        </Routes>
        <ToastViewport />
      </BrowserRouter>
    </ConfigContextProvider>
  );
}

export default App;