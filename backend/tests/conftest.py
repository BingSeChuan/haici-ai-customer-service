"""pytest 公共设施。

说明：测试复用开发环境（MySQL/Chroma/embedding 缓存），
通过随机账号隔离数据，不污染演示数据。
运行：backend 目录下 `.venv/Scripts/python -m pytest tests/ -v`
"""
import random
import string

import pytest


@pytest.fixture()
def random_account():
    """生成随机测试账号（避免与已有数据冲突）。"""
    suffix = "".join(random.choices(string.digits, k=6))
    return f"test_{suffix}@pytest.com"


@pytest.fixture()
def api_client():
    """FastAPI TestClient（复用 app 启动逻辑，含种子文档向量化）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client


def register(client, account: str, password: str = "test123456") -> str:
    """注册并返回 token。"""
    resp = client.post("/api/auth/register", json={"account": account, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
