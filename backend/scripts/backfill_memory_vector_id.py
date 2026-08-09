"""存量记忆 vector_id 回填脚本（迁移工具）。

背景：遗忘机制修复（vector_id 列）之前写入的 UserMemory 行 vector_id 为 NULL，
检索侧的"活跃 vector_id 集合"过滤会把这些存量记忆全部排除（静默失效）。
本脚本用 Chroma haici_user_memory 集合中已有的 metadata（memory_id/user_id/session_id）
按 (user_id, session_id, content) 精确匹配回填 MySQL 行的 vector_id。

用法（backend/ 目录下）：
    .venv\\Scripts\\python scripts/backfill_memory_vector_id.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import UserMemory  # noqa: E402
from app.services.memory import _memory_collection  # noqa: E402


def main():
    db = SessionLocal()
    try:
        col = _memory_collection()
        data = col.get(include=["documents", "metadatas"])
        ids, docs, metas = data["ids"], data["documents"], data["metadatas"]
        print(f"Chroma 记忆向量总数: {len(ids)}")

        backfilled = skipped = 0
        for cid, doc, meta in zip(ids, docs, metas):
            if not meta or not meta.get("memory_id"):
                continue
            user_id = meta.get("user_id")
            session_id = meta.get("session_id")
            if user_id is None:
                continue

            # 已回填的跳过（幂等）
            done = db.scalar(
                select(UserMemory.id).where(
                    UserMemory.vector_id == meta["memory_id"],
                    UserMemory.user_id == int(user_id),
                )
            )
            if done:
                skipped += 1
                continue

            # 按 (user_id, session_id, content) 匹配未回填的行
            row = db.scalar(
                select(UserMemory.id)
                .where(
                    UserMemory.user_id == int(user_id),
                    UserMemory.vector_id.is_(None),
                    UserMemory.content == doc,
                )
                .order_by(UserMemory.id)
                .limit(1)
            )
            if row is None:
                print(f"  未匹配到 MySQL 行，跳过: {meta['memory_id']} ({doc[:30]}…)")
                continue
            db.execute(
                update(UserMemory)
                .where(UserMemory.id == row)
                .values(vector_id=meta["memory_id"])
            )
            backfilled += 1

        db.commit()
        print(f"回填完成: {backfilled} 条（已跳过 {skipped} 条重复/已回填）")
        print("提示：若存在未匹配行（向量无对应 MySQL 记录），建议人工核对后再物理清理。")
    finally:
        db.close()


if __name__ == "__main__":
    main()
