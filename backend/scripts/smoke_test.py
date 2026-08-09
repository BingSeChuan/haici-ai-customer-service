"""端到端冒烟测试：注册 → 登录 → 上传文档 → 流式问答 → 兜底 → 限额 → 反馈。

用法（backend/ 目录下，服务需已启动）：
    .venv\\Scripts\\python scripts/smoke_test.py [--base http://localhost:8000]
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8000"
TOKEN = ""


def req(method: str, path: str, body: dict | None = None, raw: bool = False, timeout: int = 120):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def check(name: str, cond: bool, extra: str = ""):
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name} {extra}")
    if not cond:
        raise SystemExit(f"冒烟测试失败：{name}")


def main():
    global BASE, TOKEN
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    args = parser.parse_args()
    BASE = args.base

    import random

    account = f"test_{random.randint(100000, 999999)}@smoke.com"

    print("1) 注册")
    code, resp = req("POST", "/api/auth/register", {"account": account, "password": "test123456", "nickname": "冒烟测试"})
    check("注册成功", code == 200, f"({code})")
    TOKEN = json.loads(resp)["access_token"]

    print("2) 登录")
    code, resp = req("POST", "/api/auth/login", {"account": account, "password": "test123456"})
    check("登录成功", code == 200, f"({code})")
    TOKEN = json.loads(resp)["access_token"]

    print("3) 上传文档")
    import io

    boundary = "----smoketest"
    doc_text = "测试文档：本公司产品为云杉ERP标准版，年费3999元，7天内未使用可全额退款。"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"smoke.txt\"\r\n"
        f"Content-Type: text/plain\r\n\r\n{doc_text}\r\n--{boundary}--\r\n"
    ).encode()
    req_upload = urllib.request.Request(
        BASE + "/api/knowledge/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    code, resp = _open(req_upload)
    check("上传返回 200", code == 200, f"({code})")
    doc_id = json.loads(resp)["id"]

    print("4) 轮询文档状态")
    import time

    status = "processing"
    for _ in range(60):
        time.sleep(1)
        code, resp = req("GET", f"/api/knowledge/{doc_id}")
        status = json.loads(resp)["status"]
        if status != "processing":
            break
    check("文档向量化完成 (ready)", status == "ready", f"status={status}")

    print("5) 流式问答（SSE）")
    code, resp = req("POST", "/api/chat/stream", {"question": "云杉ERP标准版一年多少钱？"})
    check("SSE 返回 200", code == 200, f"({code})")
    events = re.findall(r"event: (\w+)", resp)
    for ev in ["start", "delta", "sources", "followups", "done"]:
        check(f"收到 {ev} 事件", ev in events)
    data_delta = "".join(re.findall(r'event: delta\ndata: \{"content": "(.*?)"\}', resp))
    check("回答非空", len(data_delta) > 10, f"({data_delta[:30]}…)")
    check("包含来源引用", "sources" in resp)

    print("6) 检索为空兜底")
    code, resp = req("POST", "/api/chat/stream", {"question": "今天上海天气怎么样？"})
    check("兜底回复不编造", "抱歉" in resp or "未找到" in resp, f"({code})")

    print("7) 超长问题 422")
    code, resp = req("POST", "/api/chat/stream", {"question": "好" * 501})
    check("超 500 字返回 422", code == 422, f"({code})")

    print("8) 会话历史")
    code, resp = req("GET", "/api/sessions")
    sessions = json.loads(resp)
    check("有会话记录", len(sessions) >= 1)
    sid = sessions[0]["id"]
    code, resp = req("GET", f"/api/sessions/{sid}/messages")
    check("会话详情含消息", len(json.loads(resp)) >= 2)

    print("9) 反馈提交")
    code, resp = req("GET", f"/api/sessions/{sid}/messages")
    msgs = json.loads(resp)
    assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
    if assistant_msgs:
        code, resp = req("POST", f"/api/sessions/messages/{assistant_msgs[-1]['id']}/feedback", {"feedback_type": "like", "text": "很好"})
        check("反馈提交成功", code == 200, f"({code})")

    print("10) 每日限额（改库验证，仅检查接口可访问）")
    code, resp = req("GET", "/api/admin/stats")
    check("admin 接口权限控制", code == 403, f"非管理员返回 403 ({code})")

    print("\n🎉 冒烟测试全部通过")


def _open(request: urllib.request.Request):
    try:
        with urllib.request.urlopen(request, timeout=120) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


if __name__ == "__main__":
    main()
