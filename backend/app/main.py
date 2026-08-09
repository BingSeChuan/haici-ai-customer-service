"""文博智能客服系统 — FastAPI 入口。

启动：uvicorn app.main:app --reload --port 8000（在 backend/ 目录下）
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import admin, auth, chat, knowledge, memory, sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时自动将 seed_docs 目录中的示例文档向量化（幂等：已处理过则跳过）。"""
    import os

    from sqlalchemy import select

    from .config import settings
    from .database import SessionLocal
    from .models import Document, KnowledgeBase, User
    from .services.knowledge import process_document_async

    db = SessionLocal()
    try:
        seed_dir = settings.seed_docs_dir
        if os.path.isdir(seed_dir):
            admin_user = db.scalar(select(User).where(User.is_admin.is_(True)))
            if admin_user is not None:
                kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == 1))
                if kb is None:
                    kb = KnowledgeBase(
                        id=1,
                        user_id=admin_user.id,
                        name="示例知识库",
                        description="预置示例文档（产品/FAQ/退换货政策）",
                    )
                    db.add(kb)
                    db.commit()

                for name in sorted(os.listdir(seed_dir)):
                    path = os.path.join(seed_dir, name)
                    if not os.path.isfile(path):
                        continue
                    ext = os.path.splitext(name)[1].lower().lstrip(".")
                    existing = db.scalar(select(Document).where(Document.file_path == path))
                    if existing and existing.status == "ready":
                        continue
                    if existing is None:
                        doc = Document(
                            user_id=admin_user.id,
                            knowledge_base_id=kb.id,
                            name=name,
                            doc_type=ext,
                            status="processing",
                            file_path=path,
                        )
                        db.add(doc)
                        db.commit()
                        db.refresh(doc)
                    else:
                        doc = existing
                    if doc.status == "processing":
                        process_document_async(doc.id)
    finally:
        db.close()
    yield


app = FastAPI(
    title="文博智能客服系统",
    description="企业级 LLM 智能客服（RAG + 流式输出）— AI 开发工程师笔试题",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(knowledge.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(admin.router)
app.include_router(memory.router)


@app.get("/")
def root():
    return {"app": "文博智能客服系统", "docs": "/docs", "status": "ok"}
