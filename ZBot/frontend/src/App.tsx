/**
 * App.jsx — 带路由的根组件
 * 路由:/ (ChatPage), /onboard (OnboardPage)
 */

import './App.css';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useConfig } from './hooks/useConfig';
import { ConfigContextProvider } from './hooks/useConfigContext';
import OnboardPage from './pages/OnboardPage';
import ChatPage from './pages/ChatPage';
import ToastViewport from './components/Toast';

function App() {
  // H31 修复:useConfig 只在 App 调一次,值通过 ConfigContext 共享给 ChatPage。
  // 之前 ChatPage 也调一次,导致重复请求 + 闪屏(两个 useEffect 竞态)。
  const { exists, setExists, setConfigured, apiBase, reason } = useConfig();

  if (exists === null) {
    return (
      <div className="onboard-page">
        <p style={{ color: 'var(--color-muted-foreground)', fontSize: '1.1rem' }}>正在检测配置...</p>
      </div>
    );
  }

  return (
    <ConfigContextProvider
      value={{
        exists,
        configured: exists,
        reason,
        apiBase,
        setExists,
        setConfigured,
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={exists ? <ChatPage /> : <Navigate to="/onboard" replace />}
          />
          <Route
            path="/onboard"
            element={
              <OnboardPage
                apiBase={apiBase}
                isSettings={exists}
                onConfigured={() => {
                  setExists(true);
                  setConfigured(true);
                }}
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
