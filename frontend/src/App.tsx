import { useState } from "react";
import { clearAuth, getStoredUser, getToken } from "./api/client";
import type { User } from "./api/types";
import ChatPage from "./pages/ChatPage";
import KnowledgePage from "./pages/KnowledgePage";
import AdminPage from "./pages/AdminPage";
import LoginPage from "./pages/LoginPage";

type Tab = "chat" | "knowledge" | "admin";

export default function App() {
  const [user, setUser] = useState<User | null>(getStoredUser());
  const [tab, setTab] = useState<Tab>("chat");

  const logout = () => {
    clearAuth();
    setUser(null);
  };

  if (!user || !getToken()) {
    return <LoginPage onLoggedIn={(u) => setUser(u)} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-logo">🌲</span>
          <span>云杉智能客服</span>
        </div>
        <nav className="tabs">
          <button className={tab === "chat" ? "tab active" : "tab"} onClick={() => setTab("chat")}>
            智能对话
          </button>
          <button
            className={tab === "knowledge" ? "tab active" : "tab"}
            onClick={() => setTab("knowledge")}
          >
            知识库
          </button>
          {user.is_admin && (
            <button
              className={tab === "admin" ? "tab active" : "tab"}
              onClick={() => setTab("admin")}
            >
              管理后台
            </button>
          )}
        </nav>
        <div className="userbox">
          <span className="avatar">{user.nickname.slice(0, 1)}</span>
          <span>{user.nickname}</span>
          <button className="link-btn" onClick={logout}>
            退出
          </button>
        </div>
      </header>
      <main className="content">
        {tab === "chat" && <ChatPage />}
        {tab === "knowledge" && <KnowledgePage />}
        {tab === "admin" && user.is_admin && <AdminPage />}
      </main>
    </div>
  );
}
