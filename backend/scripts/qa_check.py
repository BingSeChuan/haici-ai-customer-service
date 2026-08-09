"""端到端问答验证脚本（输出 UTF-8 到文件）。"""
import json
import re
import sys
import time
import urllib.request


def req(method, path, body=None, timeout=90):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    r = urllib.request.Request(
        "http://localhost:8000" + path, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.read().decode()


def ask(token, q):
    r = urllib.request.Request(
        "http://localhost:8000/api/chat/stream",
        data=json.dumps({"question": q}, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    t0 = time.time()
    resp = urllib.request.urlopen(r, timeout=120).read().decode()
    content = "".join(re.findall(r'event: delta\ndata: \{"content": "(.*?)"\}', resp))
    content = content.replace("\\n", " ").replace('\\"', '"').replace("\\u0026", "&")
    m = re.search(r"event: sources\ndata: (.*)", resp)
    src = m.group(1)[:180] if m else ""
    m = re.search(r"event: followups\ndata: (.*)", resp)
    fup = m.group(1) if m else ""
    print(f"[{q}] ({time.time() - t0:.0f}s)")
    print(f"  回答: {content[:300]}")
    print(f"  来源: {src}")
    print(f"  追问: {fup[:160]}")
    print()


def main():
    out = sys.stdout
    token = json.loads(req("POST", "/api/auth/login", {"account": "13800000000", "password": "admin123"}))[
        "access_token"
    ]
    ask(token, "云杉ERP标准版多少钱一年？")
    ask(token, "软件不想要了能退款吗？")
    ask(token, "专业版和标准版有什么区别？")
    ask(token, "忘记密码怎么办？")
    ask(token, "你们旗舰版支持私有化部署吗？")
    ask(token, "今天上海天气怎么样？")


if __name__ == "__main__":
    main()
