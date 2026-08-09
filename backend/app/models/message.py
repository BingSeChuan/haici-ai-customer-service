from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Message(Base):
    """会话消息。sources 为 JSON：引用的知识来源（文档名 + 片段摘要）。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(20), default="")     # 意图分类标注
    sources: Mapped[list] = mapped_column(JSON, default=list)       # [{doc_name, excerpt}]
    followups: Mapped[list] = mapped_column(JSON, default=list)     # 追问建议
    is_fallback: Mapped[bool] = mapped_column(default=False)        # 兜底回复标记
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
