"""数据库初始化：建表 + 种子数据（管理员账号）。

用法（backend/ 目录下）：
    1. 设置管理员密码环境变量（生产环境必须显式注入，不落库、不打日志）：
       Windows PowerShell:  $env:ADMIN_PASSWORD = "你的强密码"
       Linux/macOS:         export ADMIN_PASSWORD="你的强密码"
    2. 运行：
       .venv\\Scripts\\python scripts/init_db.py

修复 3：管理员密码不再硬编码，未设置 ADMIN_PASSWORD 时提示并退出；
打印信息不包含密码明文。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import KnowledgeBase, User  # noqa: E402
from app.services.auth import hash_password  # noqa: E402


def main():
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        print(
            "错误：未设置 ADMIN_PASSWORD 环境变量。\n"
            "请先设置管理员密码再运行（参考 .env.example 与运行指南.md），"
            "不设置则拒绝创建带默认密码的管理员账号。"
        )
        sys.exit(1)

    print("创建数据表 ...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin = User(
                phone="13800000000",
                nickname="管理员",
                password_hash=hash_password(admin_password),
                is_admin=True,
            )
            db.add(admin)
            print("已创建管理员账号: 13800000000（密码来自 ADMIN_PASSWORD 环境变量，is_admin=True）")
        else:
            print("用户表已有数据，跳过管理员创建")

        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == 1).first()
        if kb is None:
            admin = db.query(User).filter(User.is_admin.is_(True)).first()
            if admin:
                db.add(
                    KnowledgeBase(
                        id=1,
                        user_id=admin.id,
                        name="示例知识库",
                        description="预置示例文档（产品/FAQ/退换货政策）",
                    )
                )
                print("已创建示例知识库（id=1）")
        db.commit()
        print("初始化完成")
    finally:
        db.close()


if __name__ == "__main__":
    main()
