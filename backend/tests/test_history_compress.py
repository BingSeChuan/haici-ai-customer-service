"""多轮历史分层压缩测试（mock LLM，不发起真实调用）。"""
import pytest

from app.services import rag


def _history(rounds: int, content: str) -> list[dict]:
    h = []
    for i in range(rounds):
        h.append({"role": "user", "content": f"问题{i}: {content}"})
        h.append({"role": "assistant", "content": f"回答{i}: {content}"})
    return h


@pytest.mark.asyncio
async def test_short_history_not_compressed(monkeypatch):
    """短历史（≤2000 字）不触发压缩，零额外 LLM 开销。"""
    called = False

    async def fake_chat_once(messages, **kwargs):
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr(rag, "chat_once", fake_chat_once)
    history = _history(2, "你好")  # 短
    result = await rag.compress_history(history)
    assert result == history
    assert not called


@pytest.mark.asyncio
async def test_long_history_compressed_keeps_recent(monkeypatch):
    """超长历史：最近 3 轮保留原文，更早轮次压缩为摘要。"""
    long_text = "这是第X轮对话的详细内容，包含价格3999元与退款政策等信息。" * 5  # ~45字/轮

    async def fake_chat_once(messages, **kwargs):
        # 断言摘要请求包含"压缩"指令
        assert messages[1]["content"].startswith("请把以下客服对话压缩")
        return "【摘要】用户咨询过价格与退款政策。"

    monkeypatch.setattr(rag, "chat_once", fake_chat_once)

    history = _history(10, long_text)  # 10 轮 × 90 字 ≈ 900 字——需超过 2000
    assert sum(len(m["content"]) for m in history) > 2000
    result = await rag.compress_history(history)

    # 最近 3 轮（6 条）原文保留
    recent_texts = [m["content"] for m in history[-6:]]
    assert all(any(m["content"] == t for m in result) for t in recent_texts)
    # 摘要存在
    assert any("【更早对话摘要】" in m["content"] for m in result)
    # 总量显著下降
    assert sum(len(m["content"]) for m in result) < sum(len(m["content"]) for m in history)


@pytest.mark.asyncio
async def test_compress_failure_falls_back_to_truncation(monkeypatch):
    """压缩失败（LLM 异常）回退为字符截断，不影响主链路。"""
    async def failing_chat_once(messages, **kwargs):
        raise RuntimeError("LLM 超时")

    monkeypatch.setattr(rag, "chat_once", failing_chat_once)
    history = _history(10, "内容" * 30)
    result = await rag.compress_history(history)
    # 回退结果非空且不抛异常
    assert result
    assert sum(len(m["content"]) for m in result) <= sum(len(m["content"]) for m in history)
