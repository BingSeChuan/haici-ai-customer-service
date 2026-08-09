import { useState } from "react";
import { authApi, setAuth } from "../api/client";
import type { User } from "../api/types";

export default function LoginPage({ onLoggedIn }: { onLoggedIn: (u: User) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp =
        mode === "login"
          ? await authApi.login(account, password)
          : await authApi.register(account, password, nickname);
      setAuth(resp.access_token, resp.user);
      onLoggedIn(resp.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <span className="brand-logo lg">🌲</span>
          <h1>文博智能客服</h1>
          <p>企业级 LLM 智能客服系统 · RAG 知识问答</p>
        </div>

        <div className="mode-switch">
          <button type="button" className={mode === "login" ? "on" : ""} onClick={() => setMode("login")}>
            登录
          </button>
          <button
            type="button"
            className={mode === "register" ? "on" : ""}
            onClick={() => setMode("register")}
          >
            注册
          </button>
        </div>

        {mode === "register" && (
          <input
            className="input"
            placeholder="昵称（选填）"
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
          />
        )}
        <input
          className="input"
          placeholder="手机号或邮箱"
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          required
        />
        <input
          className="input"
          type="password"
          placeholder="密码（至少 6 位）"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && <div className="error-box">{error}</div>}
        <button className="btn primary block" disabled={loading}>
          {loading ? "请稍候…" : mode === "login" ? "登 录" : "注 册"}
        </button>
        <p className="login-tip">管理员账号：13800000000（密码为初始化时 ADMIN_PASSWORD 设置的值，可查看管理后台）</p>
      </form>
    </div>
  );
}
