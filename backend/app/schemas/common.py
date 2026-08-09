"""Pydantic 请求 / 响应模型。"""
from datetime import datetime

from pydantic import BaseModel, Field


# ---------- 认证 ----------
class RegisterRequest(BaseModel):
    account: str = Field(..., description="手机号或邮箱")
    password: str = Field(..., min_length=6, max_length=64, description="密码 6-64 位")
    nickname: str = Field("", max_length=50)


class LoginRequest(BaseModel):
    account: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    nickname: str
    is_admin: bool

    model_config = {"from_attributes": True}


# ---------- 会话 / 消息 ----------
class ChatRequest(BaseModel):
    session_id: int | None = Field(None, description="为空则创建新会话")
    question: str = Field(..., min_length=1, description="问题内容（≤500 字，路由层校验）")
    knowledge_base_id: int | None = Field(None, description="指定知识库（加分项路由）")


class SessionOut(BaseModel):
    id: int
    title: str
    intent: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceItem(BaseModel):
    doc_name: str
    excerpt: str
    similarity: float | None = None


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    intent: str
    sources: list[SourceItem] = []
    followups: list[str] = []
    is_fallback: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackRequest(BaseModel):
    feedback_type: str = Field(..., pattern="^(like|dislike)$")
    text: str = Field("", max_length=500)


# ---------- 知识库 ----------
class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""


class KnowledgeBaseOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: int
    knowledge_base_id: int
    name: str
    doc_type: str
    status: str
    chunk_count: int
    error_msg: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- 管理后台 ----------
class DailyStat(BaseModel):
    date: str
    question_count: int


class AdminStats(BaseModel):
    total_users: int
    total_sessions: int
    total_messages: int
    total_documents: int
    feedback_counts: dict  # {like: n, dislike: n}
    daily_stats: list[DailyStat]  # 近 7 日问答量


TokenResponse.model_rebuild()
