"""业务规则：每日提问次数限额（可配置，默认 100 次/用户/日）。

并发安全设计：使用单条原子 UPDATE（`question_count < limit` 条件内置），
避免"先查后增"竞态 —— 并发请求同时通过检查会突破上限（check-then-act 反模式）。
"""
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DailyUsage


def check_and_increment(db: Session, user_id: int) -> int:
    """原子检查并计数。返回今日已用次数；超限抛 429。

    实现：先尝试 UPDATE（自带上限条件），受影响行数为 0 时再确认
    是否因"当日无记录"（需 INSERT）还是"已达上限"（需 429）。
    """
    from sqlalchemy import text

    today = date.today()
    # 1. 当日记录不存在则创建（INSERT ... 幂等）
    db.execute(
        text(
            "INSERT IGNORE INTO daily_usage (user_id, usage_date, question_count) "
            "VALUES (:uid, :d, 0)"
        ),
        {"uid": user_id, "d": today},
    )
    # 2. 原子自增：仅当未达上限时生效，返回受影响行数
    result = db.execute(
        text(
            "UPDATE daily_usage SET question_count = question_count + 1 "
            "WHERE user_id = :uid AND usage_date = :d AND question_count < :limit"
        ),
        {"uid": user_id, "d": today, "limit": settings.daily_question_limit},
    )
    if result.rowcount == 1:
        count = db.scalar(
            select(DailyUsage.question_count).where(
                DailyUsage.user_id == user_id, DailyUsage.usage_date == today
            )
        )
        return int(count)

    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"今日提问次数已达上限（{settings.daily_question_limit} 次），请明天再来",
    )
