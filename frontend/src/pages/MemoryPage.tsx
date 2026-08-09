import { useCallback, useEffect, useState } from "react";
import { memoryApi } from "../api/client";
import type { MemoryItem, ProfileItem } from "../api/types";

const TYPE_META: Record<string, { label: string; cls: string }> = {
  fact: { label: "事实", cls: "mem-fact" },
  preference: { label: "偏好", cls: "mem-preference" },
  event: { label: "事件", cls: "mem-event" },
};

export default function MemoryPage() {
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await memoryApi.get();
      setProfiles(data.profiles);
      setMemories(data.memories);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onForget = async (id: number, content: string) => {
    if (!window.confirm(`遗忘这条记忆？\n「${content.slice(0, 50)}…」`)) return;
    try {
      await memoryApi.remove(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    }
  };

  return (
    <div className="kb-page">
      <div className="kb-header">
        <div>
          <h2>我的记忆</h2>
          <p className="sub">
            Agent 长期记忆：画像（语义记忆，Upsert+冲突检测）+ 情景记忆（LLM 从对话提取，按 user_id 隔离）
          </p>
        </div>
        <button className="btn" onClick={load}>
          刷新
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      <div className="panel">
        <h3>🧑 用户画像（L3 · 语义记忆）</h3>
        <div className="profile-grid">
          {profiles.map((p) => (
            <div className="profile-chip" key={p.key}>
              <span className="profile-key">{p.key}</span>
              <span className="profile-value">{p.value}</span>
            </div>
          ))}
          {profiles.length === 0 && <div className="empty-tip">暂无画像——多聊几句，Agent 会自动记住你</div>}
        </div>
      </div>

      <div className="panel">
        <h3>🧠 情景记忆（L1/L2 · 向量检索）</h3>
        <div className="doc-table">
          <div className="doc-row doc-head">
            <span>类型</span>
            <span>内容</span>
            <span>重要性</span>
            <span>时间</span>
            <span>操作</span>
          </div>
          {memories.map((m) => {
            const meta = TYPE_META[m.memory_type] ?? TYPE_META.fact;
            return (
              <div className="doc-row" key={m.id}>
                <span>
                  <span className={`status-badge ${meta.cls}`}>{meta.label}</span>
                </span>
                <span className="doc-name">{m.content}</span>
                <span>{"★".repeat(m.importance)}</span>
                <span>{new Date(m.created_at).toLocaleString("zh-CN")}</span>
                <span>
                  <button className="link-btn danger-text" onClick={() => onForget(m.id, m.content)}>
                    遗忘
                  </button>
                </span>
              </div>
            );
          })}
          {memories.length === 0 && <div className="empty-tip">暂无记忆——Agent 会在对话后自动提取</div>}
        </div>
      </div>
    </div>
  );
}
