import { useState } from 'react';
import './App.css';
import { useConfig } from './hooks/useConfig';
import OnboardPage from './pages/OnboardPage';
import ChatPage from './pages/ChatPage';

function App() {
  const { configured, setConfigured, apiBase } = useConfig();
  const [showSettings, setShowSettings] = useState(false);

  if (configured === null) {
    return (
      <div className="onboard-page">
        <p style={{ color: '#69758a', fontSize: '1.1rem' }}>正在检测配置...</p>
      </div>
    );
  }

  if (!configured || showSettings) {
    return (
      <OnboardPage
        apiBase={apiBase}
        isSettings={configured}
        onConfigured={() => {
          setConfigured(true);
          setShowSettings(false);
        }}
        onCancel={configured ? () => setShowSettings(false) : undefined}
      />
    );
  }

  return <ChatPage apiBase={apiBase} onOpenSettings={() => setShowSettings(true)} />;
}

export default App;
