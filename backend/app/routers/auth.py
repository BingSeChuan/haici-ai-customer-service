"""认证路由：注册 / 登录。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas.common import LoginRequest, RegisterRequest, TokenResponse, UserOut
from ..services.auth import (
    create_access_token,
    find_user_by_account,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["认证"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if find_user_by_account(db, body.account):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="该手机号/邮箱已注册，请直接登录")
    user = User(
        phone=body.account if body.account.isdigit() or _looks_phone(body.account) else None,
        email=body.account if "@" in body.account else None,
        nickname=body.nickname or "用户",
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = find_user_by_account(db, body.account)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    return _token_response(user)


def _looks_phone(account: str) -> bool:
    return len(account) == 11 and account.isdigit()
