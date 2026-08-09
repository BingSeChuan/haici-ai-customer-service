"""知识库路由：文档上传 / 列表 / 状态 / 删除，知识库管理（加分项）。"""
import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Document, KnowledgeBase, User
from ..schemas.common import (
    DocumentOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
)
from ..services.auth import get_current_user
from ..services.knowledge import ALLOWED_EXTENSIONS, process_document_async
from ..services.vector_store import delete_doc

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])


def _ensure_default_kb(db: Session, user_id: int) -> KnowledgeBase:
    """每个用户自动有一个默认知识库（id=1 为种子示例文档库，用户文档默认归属自己的库）。"""
    kb = db.scalar(
        select(KnowledgeBase).where(KnowledgeBase.user_id == user_id).order_by(KnowledgeBase.id)
    )
    if kb is None:
        kb = KnowledgeBase(user_id=user_id, name="我的知识库", description="默认知识库")
        db.add(kb)
        db.commit()
        db.refresh(kb)
    return kb


@router.post("/upload", response_model=DocumentOut)
def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    knowledge_base_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上传文档（.txt/.md/.pdf），后台异步解析 + 向量化。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="仅支持 .txt / .md / .pdf 格式")

    kb = _ensure_default_kb(db, user.id)
    if knowledge_base_id:
        target = db.get(KnowledgeBase, knowledge_base_id)
        if target is None or target.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="知识库不存在")
        kb = target

    os.makedirs(settings.upload_dir, exist_ok=True)
    file_path = os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}{ext}")
    with open(file_path, "wb") as f:
        f.write(file.file.read())

    doc = Document(
        user_id=user.id,
        knowledge_base_id=kb.id,
        name=file.filename or f"document{ext}",
        doc_type=ext.lstrip("."),
        status="processing",
        file_path=file_path,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background.add_task(process_document_async, doc.id)
    return DocumentOut.model_validate(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    docs = db.scalars(
        select(Document).where(Document.user_id == user.id).order_by(Document.id.desc())
    ).all()
    return [DocumentOut.model_validate(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return DocumentOut.model_validate(doc)


@router.delete("/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除文档：先清 Chroma 向量，再删元数据（级联一致）。"""
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="文档不存在")
    delete_doc(doc.id)  # 向量数据同步清除
    from ..services.rag import invalidate_bm25

    invalidate_bm25()  # 删除后刷新关键词索引
    try:
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except OSError:
        pass
    db.delete(doc)
    db.commit()
    return {"ok": True}


# ---------- 多知识库（加分项） ----------
@router.get("/bases", response_model=list[KnowledgeBaseOut])
def list_knowledge_bases(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    kbs = db.scalars(
        select(KnowledgeBase).where(KnowledgeBase.user_id == user.id).order_by(KnowledgeBase.id)
    ).all()
    return [KnowledgeBaseOut.model_validate(k) for k in kbs]


@router.post("/bases", response_model=KnowledgeBaseOut)
def create_knowledge_base(
    body: KnowledgeBaseCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    kb = KnowledgeBase(user_id=user.id, name=body.name, description=body.description)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return KnowledgeBaseOut.model_validate(kb)
