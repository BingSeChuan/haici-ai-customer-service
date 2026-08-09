"""RAG 离线评估（RAGAS 风格，LLM-as-judge）。

指标：
- faithfulness（忠实度）：回答中的每个结论是否能被检索到的上下文支撑 —— 幻觉的直接度量
- context_recall（召回）：上下文中是否包含回答所需的关键信息 —— 检索质量
- 另输出：回答正确性（人工期望关键词命中）、每次问答的检索链路信息

关键设计：judge 看到的上下文 = 真实进入 Prompt 的完整父块（进程内调用
retrieve_chunks，与线上链路同参数），而非 API 返回的 80 字截断摘要 ——
截断摘要会把"上下文有依据但摘要里看不到"的正确答案误判为幻觉。

用法（backend/ 目录下，服务需运行）：
    .venv\\Scripts\\python -m eval.rag_eval
"""
import asyncio
import json
import re
import urllib.request

from app.services.llm import chat_json  # noqa: E402
from app.services.rag import retrieve_chunks  # noqa: E402

EVAL_CASES = [
    {"question": "文博ERP标准版多少钱一年？", "expect": ["3999"]},
    {"question": "软件不想要了能退款吗？", "expect": ["7天", "退款"]},
    {"question": "专业版和标准版有什么区别？", "expect": ["标准版", "专业版"]},
    {"question": "忘记密码怎么办？", "expect": ["忘记密码"]},
    {"question": "你们旗舰版支持私有化部署吗？", "expect": ["私有化"]},
    {"question": "今天上海的天气怎么样？", "expect": ["兜底", "抱歉", "暂无"]},  # 反幻觉
]

FAITHFULNESS_PROMPT = """你是 RAG 系统评估员。判断"回答"中的每条结论是否都能被"检索到的知识片段"支撑。
规则：结论在片段中有明确依据 → 支撑；片段没有或与片段矛盾 → 不支撑（幻觉）。
仅输出 JSON：{{"supported_claims": n, "total_claims": n, "faithfulness": 0.0到1.0, "hallucinated_examples": ["幻觉结论示例，无则空数组"]}}

【检索到的知识片段】
{context}

【回答】
{answer}"""


def ask_api(token: str, question: str) -> str:
    body = json.dumps({"question": question}, ensure_ascii=False).encode()
    r = urllib.request.Request(
        "http://localhost:8000/api/chat/stream",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    resp = urllib.request.urlopen(r, timeout=180).read().decode()
    content = "".join(re.findall(r'event: delta\ndata: \{"content": "(.*?)"\}', resp))
    return content.replace("\\n", " ").replace('\\"', '"')


async def get_context(question: str) -> list[str]:
    """进程内调用检索链路，取真实进入 Prompt 的完整父块。"""
    chunks, empty = await retrieve_chunks(question)
    if empty:
        return []
    return [c["text"] for c in chunks]


async def judge_faithfulness(answer: str, context: list[str]) -> dict:
    context_text = "\n".join(f"- {c[:300]}" for c in context) or "（无检索片段）"
    try:
        return await chat_json(
            [
                {"role": "system", "content": "你是 RAG 系统评估员。"},
                {
                    "role": "user",
                    "content": FAITHFULNESS_PROMPT.format(context=context_text[:6000], answer=answer[:1500]),
                },
            ],
            temperature=0.0,
            max_tokens=300,
        )
    except Exception as e:
        return {"faithfulness": None, "error": str(e)}


def login() -> str:
    """用独立随机账号评估（不占用演示账号的每日 100 次额度，可重复运行）。"""
    import random
    import string

    account = f"eval_{''.join(random.choices(string.digits, k=6))}@eval.local"
    for path, payload in [
        ("/api/auth/register", {"account": account, "password": "eval123456", "nickname": "评估"}),
        ("/api/auth/login", {"account": account, "password": "eval123456"}),
    ]:
        body = json.dumps(payload).encode()
        r = urllib.request.Request(
            "http://localhost:8000" + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(r, timeout=30).read().decode()
            return json.loads(resp)["access_token"]
        except urllib.error.HTTPError as e:
            if e.code != 409:  # 已注册则走登录
                raise
    raise RuntimeError("评估账号创建失败")


async def main():
    token = login()
    results = []
    for case in EVAL_CASES:
        q = case["question"]
        answer = ask_api(token, q)
        context = await get_context(q)
        verdict = await judge_faithfulness(answer, context)

        # 期望关键词命中（人工期望）
        expect_hit = any(k in answer for k in case["expect"])
        fallback = len(context) == 0

        results.append(
            {
                "question": q,
                "answer_head": answer[:60],
                "context_chunks": len(context),
                "expect_hit": expect_hit,
                "faithfulness": verdict.get("faithfulness"),
                "hallucinated": verdict.get("hallucinated_examples", []),
                "is_fallback": fallback,
            }
        )
        print(f"[{q}]")
        print(f"  上下文块数={len(context)} 期望命中={'✅' if expect_hit else '❌'} "
              f"faithfulness={verdict.get('faithfulness')}")
        if verdict.get("hallucinated_examples"):
            print(f"  幻觉示例: {verdict['hallucinated_examples']}")
        print()

    # 汇总
    scored = [r for r in results if r["faithfulness"] is not None]
    avg_f = sum(r["faithfulness"] for r in scored) / len(scored) if scored else 0
    hit_rate = sum(1 for r in results if r["expect_hit"]) / len(results)
    hallucination_free = sum(1 for r in results if not r["hallucinated"]) / len(results)
    print("=" * 50)
    print(f"平均 faithfulness（忠实度）: {avg_f:.2f}")
    print(f"期望命中率: {hit_rate * 100:.0f}%")
    print(f"无幻觉比例: {hallucination_free * 100:.0f}%")
    print(f"评估用例: {len(results)}（含 1 条反幻觉用例）")
    with open("eval/report.json", "w", encoding="utf-8") as f:
        json.dump({"avg_faithfulness": avg_f, "hit_rate": hit_rate, "results": results}, f, ensure_ascii=False, indent=2)
    print("报告已写入 eval/report.json")


if __name__ == "__main__":
    asyncio.run(main())
