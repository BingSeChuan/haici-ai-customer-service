import { useEffect, useState } from "react";
import { adminApi } from "../api/client";
import type { AdminSession, AdminStats, MessageItem } from "../api/types";

export default function AdminPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [sessions, setSessions] = useState<AdminSession[]>([]);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<{ session: AdminSession; messages: MessageItem[] } | null>(
    null
  );

  useEffect(() => {
    adminApi
      .stats()
      .then(setStats)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
    adminApi
      .sessions()
      .then(setSessions)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  const openDetail = async (s: AdminSession) => {
    try {
      const messages = await adminApi.sessionMessages(s.id);
      setDetail({ session: s, messages });
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  };

  if (error) return <div className="error-box">{error}</div>;

  return (
    <div className="admin-page">
      <h2>管理后台</h2>

      {stats && (
        <>
          <div className="stat-cards">
            {[
              { label: "注册用户", value: stats.total_users },
              { label: "会话总数", value: stats.total_sessions },
              { label: "消息总数", value: stats.total_messages },
              { label: "知识文档", value: stats.total_documents },
            ].map((c) => (
              <div className="stat-card" key={c.label}>
                <div className="stat-value">{c.value}</div>
                <div className="stat-label">{c.label}</div>
              </div>
            ))}
          </div>

          <div className="panel">
            <h3>用户反馈</h3>
            <div className="feedback-bars">
              {(
                [
                  ["👍 点赞", stats.feedback_counts.like, "like"],
                  ["👎 踩", stats.feedback_counts.dislike, "dislike"],
                ] as const
              ).map(([label, value, cls]) => {
                const total = stats.feedback_counts.like + stats.feedback_counts.dislike;
                return (
                  <div className="fb-bar" key={cls}>
                    <span>
                      {label} {value}
                    </span>
                    <div className="bar-track">
                      <div
                        className={`bar-fill ${cls}`}
                        style={{ width: `${(value / Math.max(1, total)) * 100}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="panel">
            <h3>近 7 日问答量</h3>
            <svg viewBox="0 0 640 200" className="line-chart" preserveAspectRatio="none">
              {(() => {
                const max = Math.max(1, ...stats.daily_stats.map((d) => d.question_count));
                return stats.daily_stats.map((d, i) => {
                  const x = 20 + i * (600 / 6);
                  const y = 170 - (d.question_count / max) * 140;
                  return (
                    <g key={d.date}>
                      {i > 0 && (
                        <line
                          x1={20 + (i - 1) * (600 / 6)}
                          y1={170 - (stats.daily_stats[i - 1].question_count / max) * 140}
                          x2={x}
                          y2={y}
                          stroke="#2563eb"
                          strokeWidth="2.5"
                        />
                      )}
                      <circle cx={x} cy={y} r="4.5" fill="#2563eb" />
                      <text x={x} y="192" textAnchor="middle" fontSize="11" fill="#888">
                        {d.date.slice(5)}
                      </text>
                      <text x={x} y={y - 8} textAnchor="middle" fontSize="11" fill="#444">
                        {d.question_count}
                      </text>
                    </g>
                  );
                });
              })()}
            </svg>
          </div>
        </>
      )}

      <div className="panel">
        <h3>全量会话记录</h3>
        {detail ? (
          <div className="session-detail">
            <button className="link-btn" onClick={() => setDetail(null)}>
              ← 返回列表
            </button>
            <div className="detail-head">
              <strong>{detail.session.title}</strong>
              <span>
                {detail.session.user.nickname}（{detail.session.user.account}）
                {detail.session.intent && ` · 意图：${detail.session.intent}`}
              </span>
            </div>
            <div className="detail-messages">
              {detail.messages.map((m) => (
                <div key={m.id} className={`msg-row ${m.role}`}>
                  <div className="avatar small">{m.role === "assistant" ? "🤖" : "我"}</div>
                  <div className="bubble">
                    <div className="msg-text">{m.content}</div>
                    {m.sources.length > 0 && (
                      <div className="sources">
                        {m.sources.map((s, i) => (
                          <div className="source-card" key={i}>
                            <span className="src-doc">📄 {s.doc_name}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="doc-table">
            <div className="doc-row doc-head">
              <span>用户</span>
              <span>会话标题</span>
              <span>意图</span>
              <span>消息数</span>
              <span>最近提问</span>
              <span>更新时间</span>
            </div>
            {sessions.map((s) => (
              <div className="doc-row clickable" key={s.id} onClick={() => openDetail(s)}>
                <span>
                  {s.user.nickname}
                  <span className="src-score">（{s.user.account}）</span>
                </span>
                <span className="doc-name">{s.title}</span>
                <span>
                  {s.intent && <span className="intent-badge">{s.intent}</span>}
                </span>
                <span>{s.message_count}</span>
                <span className="src-excerpt">{s.last_question}</span>
                <span>{new Date(s.updated_at).toLocaleString("zh-CN")}</span>
              </div>
            ))}
            {sessions.length === 0 && <div className="empty-tip">暂无会话记录</div>}
          </div>
        )}
      </div>
    </div>
  );
}
