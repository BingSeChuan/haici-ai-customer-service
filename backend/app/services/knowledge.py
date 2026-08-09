"""知识库文档处理：解析 → 分块 → 分类标注 → 向量化 → 状态流转。

文档状态机：processing → ready / failed
删除文档时级联删除 Chroma 中对应向量（doc_id 关联）。
"""
import logging
import os
import re
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document
from .embedding import get_embedding_provider
from .vector_store import add_chunks

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}

# 片段类别关键词（用于"大规模上下文机制"：规则类片段优先，防注意力稀释）
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "rule": ["规则", "必须", "不得", "禁止", "规定", "应当", "一律", "政策", "退回", "退还", "售后", "赔偿", "责任", "要求"],
    "faq": ["常见问题", "FAQ", "问：", "Q：", "如何", "怎么办", "怎么办理"],
    "product": ["产品", "功能", "价格", "版本", "套餐", "特性", "支持", "适合", "服务"],
}
CATEGORY_PRIORITY = ["rule", "faq", "product", "other"]  # 优先级从高到低


def _detect_category(text: str) -> str:
    """基于关键词的规则/FAQ/产品片段分类（轻量启发式，配合 Prompt 中优先级策略）。"""
    best, score = "other", 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        s = sum(1 for kw in kws if kw in text)
        if s > score:
            best, score = cat, s
    return best


def parse_document(file_path: str, doc_type: str) -> str:
    """解析文档为纯文本。支持 .txt / .md / .pdf。"""
    if doc_type == "pdf":
        import fitz  # PyMuPDF

        text_parts = []
        with fitz.open(file_path) as pdf:
            for page in pdf:
                text_parts.append(page.get_text())
        return "\n".join(text_parts)
    # txt / md 均为 UTF-8 文本，兼容 GBK 兜底
    try:
        return open(file_path, encoding="utf-8").read()
    except UnicodeDecodeError:
        return open(file_path, encoding="gbk", errors="ignore").read()


# 章节单元模式：中文序号章节（一、二、…）、条款（第一条）、编号列表项（1. 2. 3.）、
# FAQ 条目（Q1：）、Markdown 标题。以这些开头的块独立成块（语义原子）。
_SECTION_RE = re.compile(
    r"^\s*(?:"
    r"(?:第[一二三四五六七八九十百]+[条章])"
    r"|(?:[一二三四五六七八九十]+[、.])"
    r"|(?:Q\d+[：:])"
    r"|(?:\d+[\.\、])"
    r"|(?:#{1,4}\s)"
    r"|(?:[-*]\s)"
    r")"
)


def _split_long_block(block: str, chunk_size: int, overlap: int) -> list[str]:
    """超长块：按句子就近切割，overlap 保留上一块尾部保证语义连续。"""
    sentences = re.split(r"(?<=[。！？；;.!?])\s*", block)
    out: list[str] = []
    cur = ""
    for sent in sentences:
        if len(cur) + len(sent) > chunk_size and cur:
            out.append(cur)
            cur = cur[-overlap:] if overlap else ""
        cur += sent
    if cur:
        out.append(cur)
    return [c for c in out if c.strip()]


def chunk_text(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    """按语义边界分块（章节单元独立成块）——生成"父块"。

    策略（关键设计决策，对应题目"注意力稀释"问题）：
    1. 先按空行拆段，再把段内以章节标记（一、/1./Q1：/第X条/##）开头的行
       单独切开 —— 保证每个版本/条款/FAQ 条目独立成块。若把多个知识点合并进
       一个大块，检索与 LLM 都会"稀释"：用户问"标准版多少钱"，命中块里却混着
       公司简介+专业版，模型容易漏读 —— 这是本项目实测定位到的核心质量问题；
    2. 章节单元独立成块（语义原子，不与其他段落合并）；
       普通段落按 chunk_size 预算合并相邻小块；
    3. 超长块内部按句子切割，overlap 保留上一块尾部；
    4. 短标题块（<20 字）并入下一块，避免纯关键词块虚高命中。

    返回的父块再经 split_children() 切分为子块（检索单元），
    构成 Parent-Child 两级结构（见 split_children 注释）。
    """
    chunk_size = chunk_size or settings.chunk_size
    overlap = overlap or settings.chunk_overlap

    # 1. 空行拆段 + 段内按章节标记行二次切分
    blocks: list[str] = []
    for para in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
        lines = para.splitlines()
        cur: list[str] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if _SECTION_RE.match(line) and cur:
                blocks.append("\n".join(cur))
                cur = []
            cur.append(line)
        if cur:
            blocks.append("\n".join(cur))

    # 2. 章节单元独立成块；普通段落合并到预算；超长块按句子切割
    chunks: list[str] = []
    buf = ""
    for block in blocks:
        if _SECTION_RE.match(block):
            if buf:
                chunks.append(buf)
                buf = ""
            if len(block) > chunk_size:
                chunks.extend(_split_long_block(block, chunk_size, overlap))
            else:
                chunks.append(block)
        elif len(block) > chunk_size:
            # 普通超长段落：先 flush 缓冲区，再按句子切割
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_split_long_block(block, chunk_size, overlap))
        elif len(buf) + len(block) <= chunk_size:
            buf = f"{buf}\n{block}" if buf else block
        else:
            chunks.append(buf)
            buf = block
    if buf:
        chunks.append(buf)

    # 3. 短标题块（<20 字，如"一、公司简介"）并入下一块：避免纯关键词块
    #    在向量检索中虚高命中、挤掉真正含答案的块（实测排名问题）
    merged: list[str] = []
    i = 0
    while i < len(chunks):
        cur = chunks[i]
        while i + 1 < len(chunks) and len(cur) < 20:
            i += 1
            cur = f"{cur}\n{chunks[i]}"
        merged.append(cur)
        i += 1
    return [c for c in merged if c.strip()]


def split_children(parents: list[str], child_size: int | None = None) -> list[tuple[str, str]]:
    """Parent-Child 分块：父块切分为重叠子块，返回 [(parent, child), ...]。

    企业级 RAG 的标准结构（解决检索精准度与上下文完整性的矛盾）：
    - child：180 字左右的检索单元，向量索引它 —— 命中更精准（小片段语义集中，
      不会被同块的其他知识点稀释相似度）；
    - parent：完整语义单元（条款/FAQ 条目/版本介绍），喂给 LLM —— 上下文完整，
      模型不会面对被切碎的片段；
    - 检索命中任意 child 后，取其 parent 进 Prompt（同一 parent 的多个 child 去重）。
    """
    child_size = child_size or settings.child_chunk_size
    overlap = max(20, child_size // 4)
    pairs: list[tuple[str, str]] = []
    for parent in parents:
        if len(parent) <= child_size:
            pairs.append((parent, parent))
            continue
        # 按句子边界切子块
        sentences = re.split(r"(?<=[。！？；;.!?])\s*", parent)
        cur = ""
        for sent in sentences:
            if len(cur) + len(sent) > child_size and cur:
                pairs.append((parent, cur))
                cur = cur[-overlap:]
            cur += sent
        if cur:
            pairs.append((parent, cur))
    return pairs


def process_document_async(doc_id: int):
    """后台任务：解析 → 分块 → 向量化 → 更新状态。

    使用独立 db 会话（BackgroundTasks 在线程池运行，不能复用请求会话）。
    """
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        if doc is None:
            return
        try:
            text = parse_document(doc.file_path, doc.doc_type)
            parents = chunk_text(text)
            if not parents:
                raise ValueError("文档内容为空，无法解析")

            # Parent-Child 分块：子块为检索单元（向量索引），父块为上下文单元（喂 LLM）
            pairs = split_children(parents)
            provider = get_embedding_provider()
            child_texts = [child for _, child in pairs]
            vectors = provider.embed(child_texts)
            # 同一父块的多个子块共用 parent_id（用父块文本的哈希区分）
            metadatas = [
                {
                    "doc_id": str(doc.id),
                    "doc_name": doc.name,
                    "knowledge_base_id": str(doc.knowledge_base_id),  # 多知识库路由依据
                    "category": _detect_category(child),
                    "parent_id": str(hash(parent) & 0x7FFFFFFF),
                    "parent_text": parent,  # 检索命中后直接取父块进 Prompt
                    "chunk_index": i,
                }
                for i, (parent, child) in enumerate(pairs)
            ]
            add_chunks(doc.id, child_texts, metadatas, vectors)

            doc.status = "ready"
            doc.chunk_count = len(pairs)
            doc.error_msg = ""
            from .rag import invalidate_bm25  # 局部导入避免循环依赖

            invalidate_bm25()  # 新文档入索引，保证增量更新对关键词检索可见
            logger.info("文档 %s 向量化完成: %d 个子块 / %d 个父块", doc.name, len(pairs), len(parents))
        except Exception as e:
            logger.exception("文档 %s 处理失败", doc.name)
            doc.status = "failed"
            doc.error_msg = str(e)[:500]
        db.commit()
    finally:
        db.close()


def build_snippet(text: str, limit: int = 80) -> str:
    """片段摘要：取开头并截断，用于来源引用展示。"""
    return text[:limit] + ("…" if len(text) > limit else "")
