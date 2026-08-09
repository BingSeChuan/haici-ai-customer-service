"""会话路由：历史会话列表 / 会话详情（含完整对话记录）/ 消息反馈。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ChatSession, Feedback, Message, User
from ..schemas.common import FeedbackRequest, MessageOut, SessionOut
from ..services.auth import get_current_user

router = APIRouter(prefix="/api/sessions", tags=["会话"])


@router.get("", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sessions = db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
    ).all()
    return [SessionOut.model_validate(s) for s in sessions]


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def session_messages(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="会话不存在")
    msgs = db.scalars(
        select(Message).where(Message.session_id == session_id).order_by(Message.id)
    ).all()
    return [MessageOut.model_validate(m) for m in msgs]


@router.post("/messages/{message_id}/feedback")
def submit_feedback(
    message_id: int,
    body: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对 AI 回答点赞 / 踩（可选文字）。同一消息重复提交则覆盖。

    修复 10：归属校验改用 EXISTS 子查询（原实现全量加载用户会话再判断）。
    """
    from sqlalchemy import exists

    owned = exists(
        select(ChatSession.id).where(
            ChatSession.id == Message.session_id,
            ChatSession.user_id == user.id,
        )
    )
    msg = db.scalar(select(Message).where(Message.id == message_id, owned))
    if msg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="消息不存在")

    existing = db.scalar(
        select(Feedback).where(Feedback.message_id == message_id, Feedback.user_id == user.id)
    )
    if existing:
        existing.feedback_type = body.feedback_type
        existing.text = body.text
    else:
        db.add(Feedback(message_id=message_id, user_id=user.id, feedback_type=body.feedback_type, text=body.text))
    db.commit()
    return {"ok": True, "feedback_type": body.feedback_type}
