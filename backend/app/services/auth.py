"""JWT 认证：注册 / 登录 / 令牌解析。"""
import re
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)

PHONE_RE = re.compile(r"^1\d{10}$")
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI 依赖：从 Authorization: Bearer <token> 解析当前用户。"""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="未登录，请先登录")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="登录凭证无效或已过期")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def normalize_account(account: str) -> tuple[str, str]:
    """返回 (账户字段, 账户值)。支持手机号或邮箱。"""
    if PHONE_RE.match(account):
        return "phone", account
    if EMAIL_RE.match(account):
        return "email", account
    raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="请输入正确的手机号或邮箱格式")


def find_user_by_account(db: Session, account: str) -> User | None:
    field, value = normalize_account(account)
    return db.scalar(select(User).where(getattr(User, field) == value))
