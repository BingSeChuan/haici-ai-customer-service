export interface User {
  id: number;
  nickname: string;
  is_admin: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface SessionItem {
  id: number;
  title: string;
  intent: string;
  created_at: string;
  updated_at: string;
}

export interface Source {
  doc_name: string;
  excerpt: string;
  similarity?: number;
}

export interface MessageItem {
  id: number;
  session_id: number;
  role: "user" | "assistant";
  content: string;
  intent: string;
  sources: Source[];
  followups: string[];
  is_fallback: boolean;
  created_at: string;
  _feedback?: "like" | "dislike"; // 本地标记反馈状态
}

export interface DocumentItem {
  id: number;
  knowledge_base_id: number;
  name: string;
  doc_type: string;
  status: "processing" | "ready" | "failed";
  chunk_count: number;
  error_msg: string;
  created_at: string;
}

export interface AdminStats {
  total_users: number;
  total_sessions: number;
  total_messages: number;
  total_documents: number;
  feedback_counts: { like: number; dislike: number };
  daily_stats: { date: string; question_count: number }[];
}

export interface AdminSession {
  id: number;
  user: { id: number; nickname: string; account: string };
  title: string;
  intent: string;
  message_count: number;
  last_question: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBaseItem {
  id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface ProfileItem {
  key: string;
  value: string;
  updated_at: string;
}

export interface MemoryItem {
  id: number;
  memory_type: "fact" | "preference" | "event";
  content: string;
  importance: number;
  created_at: string;
}

/** 意图徽标颜色 */
export const INTENT_COLORS: Record<string, string> = {
  产品咨询: "#2563eb",
  售后问题: "#d97706",
  闲聊: "#059669",
  投诉: "#dc2626",
};

// ---------- SSE 流式事件 ----------
export interface StreamStart {
  session_id: number;
  message_id: number;
  intent: string;
  knowledge_base?: string; // 多知识库路由结果
}

export interface StreamHandlers {
  onStart: (data: StreamStart) => void;
  onDelta: (text: string) => void;
  onSources: (sources: Source[]) => void;
  onFollowups: (suggestions: string[]) => void;
  onDone: (messageId: number) => void;
  onError: (detail: string) => void;
}
