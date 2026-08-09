"""管理后台（加分项）：全量统计 + 全量会话记录查看。"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ChatSession, DailyUsage, Document, Feedback, Message, User
from ..schemas.common import AdminStats, DailyStat, MessageOut, SessionOut
from ..services.auth import get_current_user

router = APIRouter(prefix="/api/admin", tags=["管理后台"])


@router.get("/stats", response_model=AdminStats)
def admin_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_admin(user)

    total_users = db.scalar(select(func.count(User.id))) or 0
    total_sessions = db.scalar(select(func.count(ChatSession.id))) or 0
    total_messages = db.scalar(select(func.count(Message.id))) or 0
    total_documents = db.scalar(select(func.count(Document.id))) or 0

    like_count = db.scalar(
        select(func.count(Feedback.id)).where(Feedback.feedback_type == "like")
    ) or 0
    dislike_count = db.scalar(
        select(func.count(Feedback.id)).where(Feedback.feedback_type == "dislike")
    ) or 0

    # 近 7 日每日问答量（按天聚合，缺天补 0）
    today = date.today()
    rows = db.execute(
        select(DailyUsage.usage_date, func.sum(DailyUsage.question_count))
        .where(DailyUsage.usage_date >= today - timedelta(days=6))
        .group_by(DailyUsage.usage_date)
    ).all()
    count_by_date = {str(d): int(c) for d, c in rows}
    daily_stats = [
        DailyStat(date=str(today - timedelta(days=i)), question_count=count_by_date.get(str(today - timedelta(days=i)), 0))
        for i in range(6, -1, -1)
    ]

    return AdminStats(
        total_users=total_users,
        total_sessions=total_sessions,
        total_messages=total_messages,
        total_documents=total_documents,
        feedback_counts={"like": like_count, "dislike": dislike_count},
        daily_stats=daily_stats,
    )


def _require_admin(user: User):
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="无管理员权限")


@router.get("/sessions")
def admin_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """全量会话记录（加分项）：所有用户的会话列表，含用户信息与消息摘要。"""
    _require_admin(user)
    rows = db.execute(
        select(ChatSession, User)
        .join(User, ChatSession.user_id == User.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(500)
    ).all()
    sessions = []
    for s, u in rows:
        msg_count = db.scalar(
            select(func.count(Message.id)).where(Message.session_id == s.id)
        ) or 0
        last_msg = db.scalar(
            select(Message.content)
            .where(Message.session_id == s.id, Message.role == "user")
            .order_by(Message.id.desc())
        ) or ""
        sessions.append(
            {
                "id": s.id,
                "user": {"id": u.id, "nickname": u.nickname, "account": u.phone or u.email or ""},
                "title": s.title,
                "intent": s.intent,
                "message_count": msg_count,
                "last_question": last_msg[:80],
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
            }
        )
    return sessions


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def admin_session_messages(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """全量会话详情（管理员视角）：任意用户的完整对话记录。"""
    _require_admin(user)
    msgs = db.scalars(
        select(Message).where(Message.session_id == session_id).order_by(Message.id)
    ).all()
    return [MessageOut.model_validate(m) for m in msgs]
