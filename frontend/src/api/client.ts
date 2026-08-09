import type {
  AdminSession,
  AdminStats,
  DocumentItem,
  KnowledgeBaseItem,
  MessageItem,
  SessionItem,
  StreamHandlers,
  TokenResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

const TOKEN_KEY = "haici_token";
const USER_KEY = "haici_user";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setAuth(token: string, user: unknown) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) ?? "null");
  } catch {
    return null;
  }
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// ---------- 认证 ----------
export const authApi = {
  register: (account: string, password: string, nickname: string) =>
    request<TokenResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ account, password, nickname }),
    }),
  login: (account: string, password: string) =>
    request<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ account, password }),
    }),
};

// ---------- 会话 ----------
export const sessionApi = {
  list: () => request<SessionItem[]>("/api/sessions"),
  messages: (sessionId: number) =>
    request<MessageItem[]>(`/api/sessions/${sessionId}/messages`),
  feedback: (messageId: number, feedbackType: "like" | "dislike", text = "") =>
    request<{ ok: boolean }>(`/api/sessions/messages/${messageId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ feedback_type: feedbackType, text }),
    }),
};

// ---------- 知识库 ----------
export const knowledgeApi = {
  list: () => request<DocumentItem[]>("/api/knowledge"),
  get: (id: number) => request<DocumentItem>(`/api/knowledge/${id}`),
  remove: (id: number) =>
    request<{ ok: boolean }>(`/api/knowledge/${id}`, { method: "DELETE" }),
  bases: () => request<KnowledgeBaseItem[]>("/api/knowledge/bases"),
  createBase: (name: string, description = "") =>
    request<KnowledgeBaseItem>("/api/knowledge/bases", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  upload: (file: File, knowledgeBaseId?: number) => {
    const form = new FormData();
    form.append("file", file);
    if (knowledgeBaseId) form.append("knowledge_base_id", String(knowledgeBaseId));
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(`${API_BASE}/api/knowledge/upload`, { method: "POST", headers, body: form }).then(
      async (res) => {
        if (!res.ok) {
          let detail = `上传失败 (${res.status})`;
          try {
            const body = await res.json();
            if (body.detail) detail = body.detail;
          } catch {
            /* ignore */
          }
          throw new Error(detail);
        }
        return res.json() as Promise<DocumentItem>;
      }
    );
  },
};

// ---------- 管理后台 ----------
export const adminApi = {
  stats: () => request<AdminStats>("/api/admin/stats"),
  sessions: () => request<AdminSession[]>("/api/admin/sessions"),
  sessionMessages: (sessionId: number) =>
    request<MessageItem[]>(`/api/admin/sessions/${sessionId}/messages`),
};

// ---------- SSE 流式问答 ----------
export async function chatStream(
  body: { session_id?: number | null; question: string },
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (!res.body) throw new Error("浏览器不支持流式响应");

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const parseEvent = (raw: string) => {
    const lines = raw.split("\n");
    let event = "message";
    const dataLines: string[] = [];
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) return;
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    switch (event) {
      case "start":
        handlers.onStart(payload as never);
        break;
      case "delta":
        handlers.onDelta(String(payload.content ?? ""));
        break;
      case "sources":
        handlers.onSources((payload.sources ?? []) as never);
        break;
      case "followups":
        handlers.onFollowups((payload.suggestions ?? []) as never);
        break;
      case "done":
        handlers.onDone(Number(payload.message_id));
        break;
      case "error":
        handlers.onError(String(payload.detail ?? "未知错误"));
        break;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 事件以空行分隔
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (chunk.trim()) parseEvent(chunk);
    }
  }
  // 尾部残留（无空行结尾时）
  if (buffer.trim()) parseEvent(buffer);
}
