"""API 集成测试（复用开发环境，随机账号隔离）。

覆盖：认证、业务规则（500 字/每日限额/兜底）、知识库（格式校验/状态机/级联删除）、
管理后台权限、流式问答事件序列。
"""
from datetime import date

from sqlalchemy import text

from app.config import settings
from app.database import engine

from .conftest import auth, register


def test_register_login_flow(api_client, random_account):
    token = register(api_client, random_account)
    assert token.startswith("eyJ")

    # 重复注册 409
    resp = api_client.post(
        "/api/auth/register", json={"account": random_account, "password": "test123456"}
    )
    assert resp.status_code == 409

    # 登录
    resp = api_client.post(
        "/api/auth/login", json={"account": random_account, "password": "test123456"}
    )
    assert resp.status_code == 200

    # 错误密码 401
    resp = api_client.post("/api/auth/login", json={"account": random_account, "password": "wrongpass"})
    assert resp.status_code == 401

    # 无 token 访问受保护接口 401
    resp = api_client.get("/api/sessions")
    assert resp.status_code == 401


def test_question_length_limit(api_client, random_account):
    token = register(api_client, random_account)
    long_q = "好" * (settings.max_question_length + 1)
    resp = api_client.post(
        "/api/chat/stream", json={"question": long_q}, headers=auth(token)
    )
    assert resp.status_code == 422


def test_daily_usage_limit_atomic(api_client, random_account):
    """每日限额：用量调到 limit-1 后下一次请求应触发 429（原子校验）。"""
    token = register(api_client, random_account)
    headers = auth(token)

    # 识别用户 id（从登录响应拿）
    resp = api_client.post(
        "/api/auth/login", json={"account": random_account, "password": "test123456"}
    )
    uid = resp.json()["user"]["id"]

    # 直接设置当日用量 = limit - 1
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO daily_usage (user_id, usage_date, question_count) "
                "VALUES (:uid, :d, :n) ON DUPLICATE KEY UPDATE question_count = :n"
            ),
            {"uid": uid, "d": date.today(), "n": settings.daily_question_limit - 1},
        )

    # 第 limit 次请求：正常开始（可能触发 LLM 流，仅断言非 429/422）
    resp = api_client.post(
        "/api/chat/stream", json={"question": "标准版多少钱？"}, headers=headers
    )
    assert resp.status_code not in (429, 422)

    # 第 limit+1 次请求：必须 429
    resp = api_client.post(
        "/api/chat/stream", json={"question": "标准版多少钱？"}, headers=headers
    )
    assert resp.status_code == 429, f"并发/限额防护失效: {resp.status_code}"


def test_upload_format_validation(api_client, random_account):
    token = register(api_client, random_account)
    resp = api_client.post(
        "/api/knowledge/upload",
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
        headers=auth(token),
    )
    assert resp.status_code == 400
    assert "仅支持" in resp.json()["detail"]


def test_knowledge_doc_lifecycle(api_client, random_account):
    """上传 → 就绪 → 删除（级联清向量）全生命周期。"""
    token = register(api_client, random_account)
    headers = auth(token)

    resp = api_client.post(
        "/api/knowledge/upload",
        files={"file": ("测试.txt", "云杉ERP标准版定价3999元每年。".encode(), "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]
    assert resp.json()["status"] == "processing"

    # 轮询至就绪
    status = None
    for _ in range(30):
        resp = api_client.get(f"/api/knowledge/{doc_id}", headers=headers)
        status = resp.json()["status"]
        if status != "processing":
            break
    assert status == "ready", f"文档处理失败: {resp.json()}"

    # 删除
    resp = api_client.delete(f"/api/knowledge/{doc_id}", headers=headers)
    assert resp.status_code == 200
    resp = api_client.get(f"/api/knowledge/{doc_id}", headers=headers)
    assert resp.status_code == 404


def test_admin_permission(api_client, random_account):
    """非管理员访问后台必须 403。"""
    token = register(api_client, random_account)
    resp = api_client.get("/api/admin/stats", headers=auth(token))
    assert resp.status_code == 403

    resp = api_client.get("/api/admin/sessions", headers=auth(token))
    assert resp.status_code == 403


def test_chat_stream_event_sequence(api_client, random_account):
    """SSE 流式问答事件序列完整性（命中知识库场景）。"""
    token = register(api_client, random_account)
    resp = api_client.post(
        "/api/chat/stream",
        json={"question": "云杉ERP标准版多少钱一年？"},
        headers=auth(token),
    )
    assert resp.status_code == 200
    body = resp.text
    for event in ["start", "delta", "sources", "done"]:
        assert f"event: {event}" in body, f"缺少 {event} 事件"
    assert "3999" in body or "来源" in body  # 知识库命中（或至少引用来源）


def test_empty_retrieval_fallback(api_client, random_account):
    """检索为空/无关：必须拒绝回答而非编造（兜底话术或 LLM 声明无关）。"""
    token = register(api_client, random_account)
    resp = api_client.post(
        "/api/chat/stream",
        json={"question": "今天上海的天气怎么样？"},
        headers=auth(token),
    )
    assert resp.status_code == 200
    # 不接受编造：回答必须含拒绝语气（兜底话术 或 LLM 声明"暂无/无法"）
    deny_markers = ["抱歉", "未找到", "暂无", "无法", "没有找到", "没有相关"]
    assert any(m in resp.text for m in deny_markers), f"疑似编造: {resp.text[:120]}"


def test_feedback_flow(api_client, random_account):
    """反馈提交 + 会话历史。"""
    token = register(api_client, random_account)
    headers = auth(token)

    resp = api_client.post(
        "/api/chat/stream", json={"question": "标准版多少钱？"}, headers=headers
    )
    body = resp.text
    assert "event: start" in body

    # 找到会话与助手消息
    resp = api_client.get("/api/sessions", headers=headers)
    sessions = resp.json()
    assert len(sessions) >= 1
    sid = sessions[0]["id"]

    resp = api_client.get(f"/api/sessions/{sid}/messages", headers=headers)
    messages = resp.json()
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert assistant, "缺少助手消息"

    resp = api_client.post(
        f"/api/sessions/messages/{assistant[-1]['id']}/feedback",
        json={"feedback_type": "like", "text": "测试反馈"},
        headers=headers,
    )
    assert resp.status_code == 200
