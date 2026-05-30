/**
 * App.jsx — Root component with routing
 * Routes: / (ChatPage), /settings (OnboardPage)
 */

import './App.css';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useConfig } from './hooks/useConfig';
import OnboardPage from './pages/OnboardPage';
import ChatPage from './pages/ChatPage';

function App() {
  const { exists, setExists, configured, setConfigured, apiBase } = useConfig();

  if (exists === null) {
    return (
      <div className="onboard-page">
        <p style={{ color: 'var(--color-muted-foreground)', fontSize: '1.1rem' }}>正在检测配置...</p>
      </div>
    );
  }

  return (
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
    </BrowserRouter>
  );
}

export default App;
