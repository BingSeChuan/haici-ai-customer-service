"""长期记忆路由：记忆列表 / 画像 / 遗忘（题 12 遗忘机制的用户侧入口）。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services.auth import get_current_user
from ..services.memory import forget_memory, list_memories, list_profiles

router = APIRouter(prefix="/api/memory", tags=["长期记忆"])


@router.get("")
def get_memories(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """我的记忆：画像（L3）+ 情景记忆列表（L1/L2）。"""
    return {
        "profiles": list_profiles(db, user.id),
        "memories": list_memories(db, user.id),
    }


@router.delete("/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """遗忘机制（软删除 + 向量侧清除）。"""
    if not forget_memory(db, memory_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="记忆不存在")
    return {"ok": True}
