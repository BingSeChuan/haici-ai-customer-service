"""业务规则：每日提问次数限额（可配置，默认 100 次/用户/日）。"""
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DailyUsage


def check_and_increment(db: Session, user_id: int) -> int:
    """检查限额并计数。返回今日已用次数；超限抛 429。"""
    today = date.today()
    usage = db.scalar(select(DailyUsage).where(DailyUsage.user_id == user_id, DailyUsage.usage_date == today))
    if usage is None:
        usage = DailyUsage(user_id=user_id, usage_date=today, question_count=0)
        db.add(usage)
        db.flush()

    if usage.question_count >= settings.daily_question_limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日提问次数已达上限（{settings.daily_question_limit} 次），请明天再来",
        )

    usage.question_count += 1
    db.add(usage)
    db.flush()
    return usage.question_count
