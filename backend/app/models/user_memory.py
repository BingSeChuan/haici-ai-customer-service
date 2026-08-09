from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class UserMemory(Base):
    """长期记忆（情景记忆，L1/L2 层）：LLM 从对话中提取的原子记忆。

    - 向量存在 Chroma（metadata.user_id 硬过滤防串扰），本表存结构化元数据
    - memory_type: fact（事实）/ preference（偏好）/ event（事件）
    - is_active: 遗忘机制（软删除：False 即遗忘，检索时过滤）
    - importance: 重要性分级（1-5），影响检索权重与遗忘优先级
    """

    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    memory_type: Mapped[str] = mapped_column(String(20), default="fact")  # fact/preference/event
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 过期遗忘
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserProfile(Base):
    """用户画像（语义记忆，L3 层）：结构化 KV，精确 Upsert + 冲突检测覆盖。

    例：{"city": "上海", "company_size": "10人以下", "plan": "标准版"}
    每次写入前 LLM 做冲突检测：与旧值矛盾 → 覆盖并记录更新。
    """

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(String(200))
    source_session_id: Mapped[int] = mapped_column(Integer, default=0)  # 信息来源会话
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
