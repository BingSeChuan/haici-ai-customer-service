"""Agent 记忆系统（L0-L3 分层）。

分层架构：
- L0 原始对话：MySQL messages（全量保存，确保不丢）—— 已有
- L1 原子记忆：LLM 从对话提取 {fact, preference, event} 类记忆 —— 本模块 extract
- L2 场景分块：记忆按 session 关联，带上下文检索
- L3 用户画像：结构化 KV（UserProfile 表），Upsert + 冲突检测覆盖 —— 本模块

核心设计：
1. 防串扰：情景记忆检索强制 metadata where={"user_id": ...} 硬过滤
2. 写入去重：新记忆写入前检索 Top-3 相似，LLM 判定合并/跳过
3. 遗忘机制：is_active 软删除 + expires_at 过期 + 低重要性优先遗忘
4. 画像冲突检测：新旧值矛盾时 LLM 裁决覆盖，杜绝自相矛盾
5. 防提示词注入：记忆只接受 LLM 提取的结构化 JSON，原始用户指令不直接入库
"""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import UserMemory, UserProfile
from .embedding import get_embedding_provider
from .llm import chat_json

logger = logging.getLogger(__name__)

MEMORY_COLLECTION = "haici_user_memory"

# L1 原子记忆提取：只接受结构化输出（注入防护：原始指令不进记忆库）
EXTRACT_PROMPT = """你是记忆提取器。从以下客服对话中提取值得长期记住的用户信息，输出 JSON：
{{
  "memories": [
    {{"type": "fact|preference|event", "content": "一句话描述，含关键实体", "importance": 1-5}}
  ],
  "profile_updates": [
    {{"key": "短键名（如 city/company_size/plan/industry）", "value": "值"}}
  ]
}}
规则：
- 只提取事实/偏好/事件，不提取寒暄；
- 与产品相关的用户信息（公司规模、行业、版本、城市）进 profile_updates；
- 用户明确表达的偏好（如"我不喜欢XX"）必须提取；
- 没有值得记忆的内容就输出空数组。
对话内容：
{conversation}"""

# 写入去重：检索到相似记忆时由 LLM 裁决
DEDUP_PROMPT = """新记忆与已有记忆是否表达同一个事实/偏好？（语义重复 → true）
新记忆：{new}
已有记忆：
{existing}
仅输出 JSON：{{"duplicate": true/false, "decision": "merge|skip|keep", "reason": "一句话"}}"""

# 画像冲突检测：与旧值矛盾时覆盖
PROFILE_CONFLICT_PROMPT = """用户画像更新冲突检测。
字段：{key}
旧值：{old_value}
新值：{new_value}
仅输出 JSON：{{"conflict": true/false, "decision": "overwrite|keep|merge", "reason": "一句话"}}"""

# 记忆注入 Prompt（注意力聚焦）：只注入当前用户相关记忆
MEMORY_CONTEXT_PROMPT = """你是记忆检索器。根据用户当前问题，从【用户记忆库】中挑出最相关的记忆条目（最多 3 条）：
- 相关：能帮助个性化回答（用户背景、历史偏好、之前问过的事）；
- 不相关的一律不选。
仅输出 JSON：{{"selected": [记忆编号]}}，不要输出其他内容。

用户问题：{question}

用户记忆库：
{memories}"""

# 短期记忆重要性分级：用户指令与关键结论永不丢，工具输出可截断
IMPORTANT_HINT_WORDS = ["必须", "不要", "记住", "我喜欢", "我不喜欢", "我的", "请帮我", "订单", "价格", "退款", "投诉"]


def is_important_msg(content: str) -> bool:
    """短期记忆重要性分级：含关键指令/实体词的消息标记为重要。"""
    return any(w in content for w in IMPORTANT_HINT_WORDS)


_memory_col = None


def _memory_collection():
    """修复 6：模块级缓存客户端与集合（与 vector_store.py 全局缓存风格一致）。"""
    global _memory_col
    if _memory_col is None:
        import chromadb

        from ..config import settings

        client = chromadb.PersistentClient(path=settings.chroma_dir)
        _memory_col = client.get_or_create_collection(
            MEMORY_COLLECTION, metadata={"hnsw:space": "cosine"}
        )
    return _memory_col


async def extract_memory(conversation: str) -> dict:
    """L1：LLM 从对话提取原子记忆 + 画像更新。失败返回空（不影响主链路）。"""
    try:
        return await chat_json(
            [
                {"role": "system", "content": "你是记忆提取器，只输出结构化 JSON。"},
                {"role": "user", "content": EXTRACT_PROMPT.format(conversation=conversation[:3000])},
            ],
            temperature=0.1,
            max_tokens=600,
        )
    except Exception as e:
        logger.warning("记忆提取失败: %s", e)
        return {}


async def _dedup_check(content: str, existing: list[str]) -> str:
    """写入去重：与已有记忆语义重复时合并/跳过。"""
    if not existing:
        return "keep"
    try:
        result = await chat_json(
            [
                {"role": "system", "content": "你是记忆去重器。"},
                {
                    "role": "user",
                    "content": DEDUP_PROMPT.format(
                        new=content, existing="\n".join(f"- {e}" for e in existing[:3])
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=150,
        )
        return result.get("decision", "keep")
    except Exception as e:
        logger.warning("记忆去重判定失败，直接写入: %s", e)
        return "keep"


async def store_memory(db: Session, user_id: int, session_id: int, memory_type: str, content: str, importance: int):
    """写入记忆：向量化入 Chroma + 元数据入 MySQL，带去重。

    修复 2：vector_id（Chroma ID）落库到 UserMemory.vector_id，
    遗忘时按 vector_id 精确删除向量（此前用 MySQL int id 永远删不掉）。
    """
    # 写入前检索相似记忆（去重）
    provider = get_embedding_provider()
    vector = await asyncio.to_thread(provider.embed, [content])
    vector = vector[0]
    col = _memory_collection()
    hits = await asyncio.to_thread(
        col.query,
        query_embeddings=[vector],
        n_results=3,
        where={"user_id": str(user_id)},
        include=["documents", "distances"],
    )
    similar = [d for d in (hits.get("documents") or [[]])[0] if d]
    decision = await _dedup_check(content, similar)
    if decision in ("merge", "skip"):
        logger.info("记忆去重: %s（%s）", decision, content[:40])
        return

    memory_id = f"mem_{uuid.uuid4().hex}"
    await asyncio.to_thread(
        col.upsert,
        ids=[memory_id],
        documents=[content],
        embeddings=[vector],
        metadatas=[
            {
                "user_id": str(user_id),
                "session_id": str(session_id),
                "memory_id": memory_id,
                "is_active": "true",
            }
        ],
    )
    db.add(
        UserMemory(
            user_id=user_id,
            session_id=session_id,
            vector_id=memory_id,
            memory_type=memory_type,
            content=content,
            importance=importance,
        )
    )
    db.commit()


async def upsert_profile(db: Session, user_id: int, session_id: int, key: str, value: str):
    """L3 画像 Upsert + 冲突检测覆盖。"""
    existing = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id, UserProfile.key == key))
    if existing and existing.value != value:
        try:
            result = await chat_json(
                [
                    {"role": "system", "content": "你是用户画像冲突裁决器。"},
                    {
                        "role": "user",
                        "content": PROFILE_CONFLICT_PROMPT.format(
                            key=key, old_value=existing.value, new_value=value
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=100,
            )
            if result.get("decision") == "keep":
                logger.info("画像冲突保留旧值: %s=%s", key, existing.value)
                return
        except Exception as e:
            logger.warning("画像冲突检测失败，覆盖写入: %s", e)
        logger.info("画像冲突覆盖: %s %s → %s", key, existing.value, value)
    if existing:
        existing.value = value
        existing.source_session_id = session_id
    else:
        db.add(UserProfile(user_id=user_id, key=key, value=value, source_session_id=session_id))
    db.commit()


async def process_conversation_memory(db: Session, user_id: int, session_id: int, user_q: str, answer: str):
    """对话落库后的记忆流水线：提取 → 去重入库 → 画像更新（异步卸载思路）。"""
    try:
        result = await extract_memory(f"用户：{user_q}\n客服：{answer}")
        for m in result.get("memories", [])[:5]:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            await store_memory(
                db, user_id, session_id,
                m.get("type", "fact") if m.get("type") in ("fact", "preference", "event") else "fact",
                content,
                int(m.get("importance", 3)),
            )
        for p in result.get("profile_updates", [])[:8]:
            key, value = (p.get("key") or "").strip(), (p.get("value") or "").strip()
            if key and value and len(key) <= 50 and len(value) <= 200:
                await upsert_profile(db, user_id, session_id, key, value)
    except Exception as e:
        logger.warning("记忆流水线异常（不影响对话）: %s", e)


async def retrieve_memory_context(db: Session, user_id: int, question: str, top_k: int = 5) -> str:
    """读取链路：问答前按 user_id 硬过滤检索记忆，组装为注入文本。

    返回空字符串表示无相关记忆（不注入，保持 Prompt 干净）。
    """
    # 画像（语义记忆）直接注入（最新画像永远进 Prompt 头部）
    profiles = db.scalars(
        select(UserProfile).where(UserProfile.user_id == user_id).order_by(UserProfile.updated_at.desc())
    ).all()
    profile_lines = [f"- {p.key}: {p.value}" for p in profiles]

    # 情景记忆：向量检索 + user_id 硬过滤（防串扰），再经 LLM 挑选
    try:
        # 修复 2b：已遗忘（is_active=False）记忆的 vector_id 集合，检索后过滤兜底
        # （主机制是 forget 时删除向量；此过滤保证向量删除失败时也不泄露）
        active_vector_ids = set(
            db.scalars(
                select(UserMemory.vector_id).where(
                    UserMemory.user_id == user_id,
                    UserMemory.is_active.is_(True),
                    UserMemory.vector_id.is_not(None),
                )
            ).all()
        )
        provider = get_embedding_provider()
        vector = await asyncio.to_thread(provider.embed, [question])
        vector = vector[0]
        col = _memory_collection()
        hits = await asyncio.to_thread(
            col.query,
            query_embeddings=[vector],
            n_results=top_k,
            where={"user_id": str(user_id)},  # 硬过滤：杜绝越权召回他人记忆
            include=["documents", "metadatas", "distances"],
        )
        memory_docs = (hits.get("documents") or [[]])[0]
        memory_ids = (hits.get("ids") or [[]])[0]
        if memory_docs:
            candidates = [
                {"id": i, "text": d}
                for i, d in enumerate(memory_docs)
                if memory_ids[i] in active_vector_ids  # 已遗忘记忆不召回（修复 2b）
                and 1 - (hits["distances"][0][i]) >= 0.35  # 阈值拦截
            ]
            if candidates:
                # LLM 挑选最相关的 ≤3 条（注意力聚焦）
                result = await chat_json(
                    [
                        {"role": "system", "content": "你是记忆检索器。"},
                        {
                            "role": "user",
                            "content": MEMORY_CONTEXT_PROMPT.format(
                                question=question,
                                memories="\n".join(f"[{c['id']}] {c['text'][:100]}" for c in candidates),
                            ),
                        },
                    ],
                    temperature=0.0,
                    max_tokens=120,
                )
                selected_ids = {int(x) for x in result.get("selected", []) if str(x).isdigit()}
                memory_lines = [
                    f"- {c['text']}"
                    for c in candidates
                    if c["id"] in selected_ids or not selected_ids
                ][:3]
            else:
                memory_lines = []
        else:
            memory_lines = []
    except Exception as e:
        logger.warning("情景记忆检索失败（忽略）: %s", e)
        memory_lines = []

    if not profile_lines and not memory_lines:
        return ""
    parts = []
    if profile_lines:
        parts.append("【用户画像】\n" + "\n".join(profile_lines[:5]))
    if memory_lines:
        parts.append("【用户历史记忆】\n" + "\n".join(memory_lines))
    return "\n\n".join(parts)


def forget_memory(db: Session, memory_id: int, user_id: int) -> bool:
    """遗忘机制：软删除 is_active=False + 按 vector_id 删除向量。

    向量删除失败只记日志不阻断软删除（DB 侧 is_active 仍保证检索过滤）。
    """
    mem = db.get(UserMemory, memory_id)
    if mem is None or mem.user_id != user_id:
        return False
    mem.is_active = False
    db.commit()
    if mem.vector_id:
        try:
            col = _memory_collection()
            col.delete(ids=[mem.vector_id])  # 按 Chroma 真实 ID 删除（修复 2a）
        except Exception as e:
            logger.warning("向量记忆删除失败（软删除仍生效）: %s", e)
    return True


def list_memories(db: Session, user_id: int) -> list[dict]:
    """记忆列表（前端"我的记忆"页）。"""
    rows = db.scalars(
        select(UserMemory)
        .where(UserMemory.user_id == user_id, UserMemory.is_active.is_(True))
        .order_by(UserMemory.importance.desc(), UserMemory.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": m.id,
            "memory_type": m.memory_type,
            "content": m.content,
            "importance": m.importance,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


def list_profiles(db: Session, user_id: int) -> list[dict]:
    return [
        {"key": p.key, "value": p.value, "updated_at": p.updated_at.isoformat()}
        for p in db.scalars(
            select(UserProfile).where(UserProfile.user_id == user_id).order_by(UserProfile.updated_at.desc())
        ).all()
    ]
