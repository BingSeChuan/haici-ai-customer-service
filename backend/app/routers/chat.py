"""对话路由：SSE 流式问答（POST /api/chat/stream）。

SSE 事件协议（前端按此解析）：
  event: start     data: {"session_id":1,"message_id":2,"intent":"产品咨询"}
  event: delta     data: {"content":"逐字增量文本"}
  event: sources   data: {"sources":[{"doc_name":"...","excerpt":"...","similarity":0.82}]}
  event: followups data: {"suggestions":["...","..."]}
  event: done      data: {"message_id":2}
  event: error     data: {"detail":"..."}
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..models import ChatSession, KnowledgeBase, Message, User
from ..schemas.common import ChatRequest
from ..services.auth import get_current_user
from ..services.knowledge import build_snippet
from ..services.rag import (
    build_rag_messages,
    detect_intent,
    generate_followups,
    get_history,
    retrieve_chunks,
)
from ..services.usage import check_and_increment

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["对话"])

# 修复 7：后台任务集合（持有引用防 GC 丢弃；done 时自动移除）
_memory_tasks: set[asyncio.Task] = set()


async def _memory_pipeline(user_id: int, session_id: int, question: str, answer: str):
    """L1 记忆提取后台任务：独立 DB 会话，失败静默（不影响主链路）。"""
    from ..database import SessionLocal
    from ..services.memory import process_conversation_memory

    mdb = SessionLocal()
    try:
        await process_conversation_memory(mdb, user_id, session_id, question, answer)
    except Exception:
        logger.exception("记忆提取后台任务异常")
    finally:
        mdb.close()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # ---- 业务规则校验（在流开始前完成，直接返回错误码而非 SSE error） ----
    if len(body.question) > settings.max_question_length:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"提问长度不能超过 {settings.max_question_length} 字（当前 {len(body.question)} 字）",
        )
    check_and_increment(db, user.id)  # 每日限额，超限抛 429

    question = body.question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="问题不能为空")

    # ---- 会话与用户消息落库 ----
    if body.session_id:
        session = db.get(ChatSession, body.session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="会话不存在")
    else:
        session = ChatSession(user_id=user.id, title=question[:20])
        db.add(session)
        db.commit()
        db.refresh(session)

    user_msg = Message(session_id=session.id, role="user", content=question)
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # ---- 意图识别：失败不影响主链路 ----
    intent = await detect_intent(question)
    session.intent = intent
    user_msg.intent = intent
    db.add_all([session, user_msg])
    db.commit()

    # ---- 越权防护：指定知识库必须属于当前用户（与 knowledge.py 上传校验同风格） ----
    if body.knowledge_base_id is not None:
        target_kb = db.get(KnowledgeBase, body.knowledge_base_id)
        if target_kb is None or target_kb.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="知识库不存在")

    # ---- 向量检索（阈值过滤后可能为空 → 兜底） ----
    # 多知识库路由：指定库则只检索该库；未指定则全量检索自动路由
    chunks, is_empty = await retrieve_chunks(question, knowledge_base_id=body.knowledge_base_id)
    routed_kb_name = None
    if not is_empty and body.knowledge_base_id is None:
        # 自动路由：命中片段按知识库聚合，得分最高的库为路由目标
        kb_scores: dict[str, float] = {}
        for c in chunks:
            kb = c["metadata"].get("knowledge_base_id", "")
            kb_scores[kb] = kb_scores.get(kb, 0.0) + c["similarity"]
        top_kb = max(kb_scores, key=kb_scores.get) if kb_scores else None
        if top_kb:
            kb_obj = db.get(KnowledgeBase, int(top_kb))
            if kb_obj:
                routed_kb_name = kb_obj.name
    history = await get_history(db, session.id)

    # ---- 长期记忆读取：问答前注入用户画像与历史偏好 ----
    from ..services.memory import process_conversation_memory, retrieve_memory_context

    memory_context = await retrieve_memory_context(db, user.id, question)
    if memory_context:
        logger.info("注入用户记忆上下文（%d 字）", len(memory_context))

    async def event_stream():
        # 生成器内使用独立会话（请求会话在响应结束后才关闭，但长流中自建更稳妥）
        gen_db = SessionLocal()
        assistant_id: int | None = None
        answer_parts: list[str] = []
        try:
            if await request.is_disconnected():
                return

            start_data: dict = {"session_id": session.id, "message_id": user_msg.id, "intent": intent}
            if routed_kb_name:
                start_data["knowledge_base"] = routed_kb_name  # 多知识库路由结果展示
            yield _sse("start", start_data)

            if is_empty:
                # 检索为空：标准兜底话术，不调用 LLM、不编造
                fallback = settings.fallback_reply
                answer_parts.append(fallback)
                yield _sse("delta", {"content": fallback})
            else:
                # ---- 拼接 Prompt（含用户记忆）并流式调用 LLM ----
                rag_messages = build_rag_messages(question, chunks, history, memory_context)
                async for delta in _chat_with_retry(rag_messages):
                    answer_parts.append(delta)
                    yield _sse("delta", {"content": delta})

            answer = "".join(answer_parts)

            # ---- 落库助手消息（含引用来源） ----
            sources = [
                {
                    "doc_name": c["metadata"].get("doc_name", "未知"),
                    "excerpt": build_snippet(c["text"]),
                    "similarity": round(c["similarity"], 4),
                }
                for c in chunks
            ]
            assistant_msg = Message(
                session_id=session.id,
                role="assistant",
                content=answer,
                sources=sources,
                is_fallback=is_empty,
                intent=intent,
            )
            gen_db.add(assistant_msg)
            gen_db.commit()
            gen_db.refresh(assistant_msg)
            assistant_id = assistant_msg.id

            yield _sse("sources", {"sources": sources})

            # ---- 追问建议：单独小调用，失败返回空 ----
            suggestions = await generate_followups(question, answer) if not is_empty else []
            if suggestions:
                assistant_msg.followups = suggestions
                gen_db.add(assistant_msg)
                gen_db.commit()
            yield _sse("followups", {"suggestions": suggestions})

            yield _sse("done", {"message_id": assistant_id})

            # ---- L1 记忆提取（异步，不阻塞流） ----
            # 修复 7：任务集合持有引用防止被 GC 丢弃；完成后自动移除
            task = asyncio.create_task(
                _memory_pipeline(user_id=user.id, session_id=session.id, question=question, answer=answer)
            )
            _memory_tasks.add(task)
            task.add_done_callback(_memory_tasks.discard)
        except Exception:
            # 修复 4：完整异常只记日志，客户端只收通用文案（不泄露内部实现）
            logger.exception("SSE 流异常")
            # 已累积的内容也落库，避免用户白问
            if answer_parts and assistant_id is None:
                try:
                    gen_db.add(
                        Message(
                            session_id=session.id,
                            role="assistant",
                            content="".join(answer_parts),
                            sources=[
                                {
                                    "doc_name": c["metadata"].get("doc_name", "未知"),
                                    "excerpt": build_snippet(c["text"]),
                                }
                                for c in chunks
                            ],
                            is_fallback=is_empty,
                            intent=intent,
                        )
                    )
                    gen_db.commit()
                except Exception:
                    gen_db.rollback()
            yield _sse("error", {"detail": "服务暂时不可用，请稍后重试"})
        finally:
            gen_db.close()

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _chat_with_retry(rag_messages: list[dict]):
    """LLM 流式调用（llm.py 内已配置重试 1 次），此处不再额外处理。"""
    from ..services.llm import chat_stream

    async for delta in chat_stream(rag_messages):
        yield delta
