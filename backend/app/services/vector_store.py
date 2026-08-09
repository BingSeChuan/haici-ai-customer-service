"""Chroma 向量库封装（本地持久化模式，无需独立服务）。

- 每个文档的向量通过 metadata.doc_id 关联，删除文档时级联清理
- 检索按相似度阈值过滤（RAG_SIMILARITY_THRESHOLD），低于阈值视为"检索为空"→ 兜底
"""
import logging
import uuid
from typing import Sequence

from ..config import settings

logger = logging.getLogger(__name__)

_client = None
_collection = None


def get_collection():
    """懒加载 Chroma 客户端与集合（首次调用时初始化）。"""
    global _client, _collection
    if _collection is None:
        import chromadb

        _client = chromadb.PersistentClient(path=settings.chroma_dir)
        # cosine 距离与"相似度"换算：similarity = 1 - distance
        _collection = _client.get_or_create_collection(
            name="haici_knowledge",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Chroma 集合就绪: %s", settings.chroma_dir)
    return _collection


def _sim(distance: float) -> float:
    """Chroma cosine 距离 → 相似度分数。"""
    return 1.0 - distance


def add_chunks(doc_id: int, texts: Sequence[str], metadatas: Sequence[dict], vectors: Sequence[list[float]]):
    """写入一批分块。ids 使用 uuid 保证幂等追加。"""
    col = get_collection()
    ids = [str(uuid.uuid4()) for _ in texts]
    col.add(ids=ids, documents=list(texts), metadatas=list(metadatas), embeddings=list(vectors))
    return ids


def delete_doc(doc_id: int):
    """删除某文档的全部向量（按 metadata.doc_id 过滤）。"""
    col = get_collection()
    result = col.get(where={"doc_id": str(doc_id)})
    if result["ids"]:
        col.delete(ids=result["ids"])


def search(query_vector: list[float], top_k: int, knowledge_base_id: int | None = None) -> list[dict]:
    """向量检索，返回 [{id, text, metadata, similarity}]，未做阈值过滤（阈值在调用方）。

    knowledge_base_id 非空时按 metadata 过滤，实现"指定知识库提问"。
    """
    col = get_collection()
    where = {"knowledge_base_id": str(knowledge_base_id)} if knowledge_base_id else None
    result = col.query(
        query_embeddings=[query_vector],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    items = []
    if not result["ids"] or not result["ids"][0]:
        return items
    for i, _id in enumerate(result["ids"][0]):
        items.append(
            {
                "id": _id,
                "text": result["documents"][0][i],
                "metadata": result["metadatas"][0][i] or {},
                "similarity": _sim(result["distances"][0][i]),
            }
        )
    return items
