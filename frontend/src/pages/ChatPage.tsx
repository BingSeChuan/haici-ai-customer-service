import { useCallback, useEffect, useRef, useState } from "react";
import { chatStream, sessionApi } from "../api/client";
import { INTENT_COLORS, type MessageItem, type SessionItem, type Source } from "../api/types";

interface StreamState {
  content: string;
  sources: Source[];
  followups: string[];
  knowledgeBase?: string; // 多知识库路由结果
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [stream, setStream] = useState<StreamState | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const newSessionIdRef = useRef<number | null>(null); // 新会话创建后的 session id
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadSessions = useCallback(async () => {
    try {
      setSessions(await sessionApi.list());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const loadMessages = useCallback(async (sessionId: number) => {
    setMessages(await sessionApi.messages(sessionId));
    setStream(null);
  }, []);

  useEffect(() => {
    if (activeId) loadMessages(activeId);
  }, [activeId, loadMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, stream]);

  const send = async () => {
    const question = input.trim();
    if (!question || sending) return;
    setInput("");
    setError("");
    setSending(true);
    setStream({ content: "", sources: [], followups: [], knowledgeBase: undefined });

    // 乐观渲染用户消息
    const optimistic: MessageItem = {
      id: -Date.now(),
      session_id: activeId ?? 0,
      role: "user",
      content: question,
      intent: "",
      sources: [],
      followups: [],
      is_fallback: false,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await chatStream(
        { session_id: activeId, question },
        {
          onStart: (data) => {
            newSessionIdRef.current = data.session_id;
            if (!activeId) setActiveId(data.session_id);
            if (data.knowledge_base) {
              setStream((s) => (s ? { ...s, knowledgeBase: data.knowledge_base } : s));
            }
          },
          onDelta: (t) => setStream((s) => (s ? { ...s, content: s.content + t } : s)),
          onSources: (sources) => setStream((s) => (s ? { ...s, sources } : s)),
          onFollowups: (followups) => setStream((s) => (s ? { ...s, followups } : s)),
          onDone: () => {
            const sid = newSessionIdRef.current;
            loadSessions();
            if (sid) loadMessages(sid);
          },
          onError: (detail) => setError(detail),
        },
        controller.signal
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "网络错误");
    } finally {
      setSending(false);
      abortRef.current = null;
      if (activeId) loadMessages(activeId);
    }
  };

  const stop = () => abortRef.current?.abort();

  const submitFeedback = async (messageId: number, type: "like" | "dislike") => {
    // 选填文字反馈：直接确定则跳过
    const text = window.prompt("补充文字反馈（选填，直接点确定即可跳过）：", "") ?? "";
    try {
      await sessionApi.feedback(messageId, type, text.trim());
      setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, _feedback: type } : m)));
    } catch {
      /* ignore */
    }
  };

  const chooseFollowup = (q: string) => {
    setInput(q);
  };

  return (
    <div className="chat-layout">
      {/* 会话侧边栏 */}
      <aside className="session-bar">
        <button
          className="btn primary block"
          onClick={() => {
            setActiveId(null);
            setMessages([]);
            setStream(null);
          }}
        >
          ＋ 新对话
        </button>
        <div className="session-list">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`session-item ${s.id === activeId ? "active" : ""}`}
              onClick={() => setActiveId(s.id)}
            >
              <div className="session-title">{s.title}</div>
              <div className="session-meta">
                {s.intent && (
                  <span className="intent-badge" style={{ color: INTENT_COLORS[s.intent] ?? "#666" }}>
                    {s.intent}
                  </span>
                )}
              </div>
            </div>
          ))}
          {sessions.length === 0 && <div className="empty-tip">暂无历史会话</div>}
        </div>
      </aside>

      {/* 对话区 */}
      <section className="chat-main">
        <div className="chat-history">
          {messages.length === 0 && !stream && (
            <div className="welcome">
              <div className="welcome-logo">🌲</div>
              <h2>你好，我是云杉智能客服</h2>
              <p>我可以回答关于云杉ERP 产品、FAQ、退换货政策等问题</p>
              <div className="welcome-suggests">
                {["标准版多少钱一年？", "忘记密码怎么办？", "软件不想要了能退款吗？"].map((q) => (
                  <button key={q} className="chip" onClick={() => setInput(q)}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} className={`msg-row ${m.role}`}>
              <div className="avatar small">{m.role === "assistant" ? "🤖" : "我"}</div>
              <div className="bubble">
                {m.role === "assistant" && m.intent && (
                  <span className="intent-badge" style={{ color: INTENT_COLORS[m.intent] ?? "#666" }}>
                    意图：{m.intent}
                  </span>
                )}
                <div className="msg-text">{m.content}</div>
                {m.is_fallback && <div className="fallback-note">（知识库未检索到相关内容，未编造回答）</div>}
                {m.sources.length > 0 && (
                  <div className="sources">
                    {m.sources.map((s, i) => (
                      <div className="source-card" key={i}>
                        <span className="src-doc">📄 {s.doc_name}</span>
                        <span className="src-excerpt">{s.excerpt}</span>
                        {s.similarity !== undefined && (
                          <span className="src-score">相关度 {(s.similarity * 100).toFixed(0)}%</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {m.role === "assistant" && m.followups.length > 0 && (
                  <div className="followups">
                    <div className="followups-label">💡 猜你想问：</div>
                    {m.followups.map((q, i) => (
                      <button key={i} className="chip" onClick={() => chooseFollowup(q)}>
                        {q}
                      </button>
                    ))}
                  </div>
                )}
                {m.role === "assistant" && (
                  <div className="feedback-row">
                    <button className="fb-btn" onClick={() => submitFeedback(m.id, "like")}>
                      👍
                    </button>
                    <button className="fb-btn" onClick={() => submitFeedback(m.id, "dislike")}>
                      👎
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* 流式回答 */}
          {stream && (
            <div className="msg-row assistant">
              <div className="avatar small">🤖</div>
              <div className="bubble">
                {stream.knowledgeBase && (
                  <div className="routed-kb">📚 回答来自知识库：{stream.knowledgeBase}</div>
                )}
                <div className="msg-text">
                  {stream.content}
                  <span className="cursor" />
                </div>
                {stream.sources.length > 0 && (
                  <div className="sources">
                    {stream.sources.map((s, i) => (
                      <div className="source-card" key={i}>
                        <span className="src-doc">📄 {s.doc_name}</span>
                        <span className="src-excerpt">{s.excerpt}</span>
                        {s.similarity !== undefined && (
                          <span className="src-score">相关度 {(s.similarity * 100).toFixed(0)}%</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {stream.followups.length > 0 && (
                  <div className="followups">
                    <div className="followups-label">💡 猜你想问：</div>
                    {stream.followups.map((q, i) => (
                      <button key={i} className="chip" onClick={() => chooseFollowup(q)}>
                        {q}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {error && <div className="error-box chat-error">{error}</div>}

        <div className="composer">
          <textarea
            className="input composer-input"
            placeholder="请输入您的问题（不超过 500 字）…"
            value={input}
            maxLength={500}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          {sending ? (
            <button className="btn danger" onClick={stop}>
              ■ 停止
            </button>
          ) : (
            <button className="btn primary" onClick={send} disabled={!input.trim()}>
              发送
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
