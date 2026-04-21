import React, { useState, useEffect, useRef } from 'react';
import MessageBubble from './components/Chat/MessageBubble';
import InputArea from './components/Chat/InputArea';
import TypingIndicator from './components/Chat/TypingIndicator';
import './styles/global.css';

// Mock Endpoint - In production, this comes from ENV
const API_ENDPOINT = import.meta.env.VITE_BACKEND_URL ? `${import.meta.env.VITE_BACKEND_URL}/invocations` : "/invocations";

function App() {
  const [messages, setMessages] = useState(() => {
    const saved = localStorage.getItem('chat_history');
    if (saved) return JSON.parse(saved);
    const appName = import.meta.env.VITE_APP_TITLE || "AWS Migration Assistant";
    return [{
      role: 'assistant',
      content: `Hello! I'm your **${appName}**. \n\nI can help you plan your cloud journey, analyze architecture diagrams, or estimate costs. \n\n*How can I help you today?*`
    }];
  });

  // ... (lines 22-104 remain same, jumping to return)

  return (
    <div className="app-container">
      <header className="header glass-card">
        <div className="logo">🚀</div>
        <div style={{ flex: 1 }}>
          <h1>{import.meta.env.VITE_APP_TITLE || "AWS Migration Assistant"}</h1>
          <span className="badge">AgentCore Gateway</span>
        </div>

      </header>

      <main className="chat-area">
        <div className="messages-list">
          {messages.map((msg, idx) => (
            <MessageBubble key={idx} role={msg.role} content={msg.content} />
          ))}
          {isLoading && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>
      </main>

      <footer className="input-area-wrapper">
        <InputArea onSend={handleSendMessage} isDisabled={isLoading} />
      </footer>

      <style jsx="true">{`
        .app-container {
          display: flex;
          flex-direction: column;
          height: 100vh;
          background: radial-gradient(circle at 50% 10%, #1a1a2e 0%, #0f0f12 60%);
        }

        .header {
          padding: 16px 24px;
          display: flex;
          align-items: center;
          gap: 16px;
          z-index: 10;
          border-bottom: 1px solid var(--glass-border);
        }

        .logo {
          font-size: 24px;
          background: var(--bg-tertiary);
          width: 40px;
          height: 40px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 10px;
        }

        .header h1 {
          font-size: 1.1rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .badge {
          font-size: 0.75rem;
          background: rgba(99, 102, 241, 0.2);
          color: #818cf8;
          padding: 2px 8px;
          border-radius: 4px;
          border: 1px solid rgba(99, 102, 241, 0.3);
        }

        .chat-area {
          flex: 1;
          overflow-y: auto;
          position: relative;
        }

        .messages-list {
          padding: 24px;
          padding-bottom: 140px; /* Space for input area */
          max-width: 900px;
          margin: 0 auto;
        }

        .input-area-wrapper {
          position: absolute;
          bottom: 24px;
          left: 0;
          right: 0;
          padding: 0 24px;
          z-index: 20;
        }
        .sign-out-btn {
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid var(--glass-border);
          color: var(--text-primary);
          padding: 6px 12px;
          border-radius: 6px;
          cursor: pointer;
          font-size: 0.8rem;
          transition: all 0.2s;
        }
        .sign-out-btn:hover {
          background: rgba(239, 68, 68, 0.2);
          border-color: rgba(239, 68, 68, 0.4);
        }
      `}</style>
    </div>
  );
}

export default App;
