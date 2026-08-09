import { useCallback, useEffect, useRef, useState } from "react";
import { knowledgeApi } from "../api/client";
import type { DocumentItem, KnowledgeBaseItem } from "../api/types";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  processing: { label: "处理中", cls: "status-processing" },
  ready: { label: "已就绪", cls: "status-ready" },
  failed: { label: "失败", cls: "status-failed" },
};

export default function KnowledgePage() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [bases, setBases] = useState<KnowledgeBaseItem[]>([]);
  const [activeBase, setActiveBase] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [docList, baseList] = await Promise.all([knowledgeApi.list(), knowledgeApi.bases()]);
      setDocs(docList);
      setBases(baseList);
      if (baseList.length > 0 && activeBase === null) setActiveBase(baseList[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, [activeBase]);

  useEffect(() => {
    load();
  }, [load]);

  const createBase = async () => {
    const name = window.prompt("输入新知识库名称：");
    if (!name?.trim()) return;
    try {
      await knowledgeApi.createBase(name.trim());
      setActiveBase(null); // 触发重新加载
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    }
  };

  // 处理中的文档轮询刷新状态
  useEffect(() => {
    const timer = setInterval(() => {
      if (docs.some((d) => d.status === "processing")) load();
    }, 3000);
    return () => clearInterval(timer);
  }, [docs, load]);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await knowledgeApi.upload(file, activeBase ?? undefined);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const onDelete = async (id: number, name: string) => {
    if (!window.confirm(`确定删除文档「${name}」？对应的向量数据将同步清除。`)) return;
    try {
      await knowledgeApi.remove(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  return (
    <div className="kb-page">
      <div className="kb-header">
        <div>
          <h2>知识库</h2>
          <p className="sub">上传文档（.txt / .md / .pdf），系统自动解析并向量化，用于智能问答检索</p>
        </div>
        <div className="kb-actions">
          {bases.length > 0 && (
            <select
              className="input kb-select"
              value={activeBase ?? ""}
              onChange={(e) => setActiveBase(Number(e.target.value))}
            >
              {bases.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          )}
          <button className="btn" onClick={createBase}>
            ＋ 新知识库
          </button>
          <input ref={fileRef} type="file" accept=".txt,.md,.pdf" hidden onChange={onUpload} />
          <button className="btn primary" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? "上传中…" : "＋ 上传文档"}
          </button>
        </div>
      </div>

      {bases.length > 1 && (
        <div className="kb-note">💡 上传的文档将归入当前选择的知识库；提问时系统会自动路由到最相关的知识库（也可在对话中指定）。</div>
      )}

      {error && <div className="error-box">{error}</div>}

      <div className="doc-table">
        <div className="doc-row doc-head">
          <span>文档名称</span>
          <span>类型</span>
          <span>状态</span>
          <span>分块数</span>
          <span>上传时间</span>
          <span>操作</span>
        </div>
        {docs.map((d) => {
          const st = STATUS_META[d.status] ?? { label: d.status, cls: "" };
          return (
            <div className="doc-row" key={d.id}>
              <span className="doc-name">📄 {d.name}</span>
              <span className="doc-type">{d.doc_type.toUpperCase()}</span>
              <span>
                <span className={`status-badge ${st.cls}`}>{st.label}</span>
                {d.status === "failed" && <span className="fail-msg" title={d.error_msg}>⚠</span>}
              </span>
              <span>{d.chunk_count}</span>
              <span>{new Date(d.created_at).toLocaleString("zh-CN")}</span>
              <span>
                <button className="link-btn danger-text" onClick={() => onDelete(d.id, d.name)}>
                  删除
                </button>
              </span>
            </div>
          );
        })}
        {docs.length === 0 && <div className="empty-tip">知识库为空，点击右上角上传文档</div>}
      </div>

      <div className="kb-note">
        💡 预置示例文档（产品介绍 / 常见问题FAQ / 退换货政策）已自动向量化，可直接在「智能对话」中提问测试。
      </div>
    </div>
  );
}
