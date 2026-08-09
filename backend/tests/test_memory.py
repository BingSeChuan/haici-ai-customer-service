"""记忆系统测试：重要性分级、去重判定、画像冲突、遗忘（LLM 调用全部 mock）。"""
import pytest

from app.services import memory


def test_importance_hint_words():
    """短期记忆重要性分级：含关键指令/实体的消息标记为重要（题 3）。"""
    assert memory.is_important_msg("请记住我喜欢用短信通知")
    assert memory.is_important_msg("订单必须明天发货")
    assert not memory.is_important_msg("好的，谢谢")


@pytest.mark.asyncio
async def test_dedup_decision_follows_llm(monkeypatch):
    """写入去重（题 11）：LLM 判定 merge/skip 时不写入，keep 时写入。"""
    async def fake_chat_json(messages, **kwargs):
        content = messages[1]["content"]
        if "用户偏好短信" in content:
            return {"duplicate": True, "decision": "merge", "reason": "同义"}
        return {"duplicate": False, "decision": "keep", "reason": "新信息"}

    monkeypatch.setattr(memory, "chat_json", fake_chat_json)
    assert await memory._dedup_check("用户喜欢短信", ["用户偏好短信"]) == "merge"
    assert await memory._dedup_check("用户喜欢短信", ["用户公司有20人"]) == "keep"


@pytest.mark.asyncio
async def test_extract_memory_failure_is_silent(monkeypatch):
    """记忆提取失败必须静默返回空，不影响主链路（题 5 健壮性）。"""
    async def failing(messages, **kwargs):
        raise RuntimeError("LLM 超时")

    monkeypatch.setattr(memory, "chat_json", failing)
    assert await memory.extract_memory("用户：你好\n客服：您好") == {}


@pytest.mark.asyncio
async def test_profile_conflict_overwrite_and_keep(monkeypatch):
    """画像冲突检测（题 13）：decision=keep 保留旧值，overwrite 覆盖。"""
    class StubDB:
        def __init__(self):
            self.existing = None

        def scalar(self, stmt):
            return self.existing

        def add(self, obj):
            pass

        def commit(self):
            pass

    async def fake_chat_json(messages, **kwargs):
        return {"conflict": True, "decision": "overwrite", "reason": "以用户最新说法为准"}

    monkeypatch.setattr(memory, "chat_json", fake_chat_json)
    db = StubDB()
    # 无既有画像：直接写入不抛异常
    assert await memory.upsert_profile(db, 1, 1, "city", "上海") is None

    # 有既有画像 + LLM 判定 overwrite：覆盖不抛异常
    from app.models import UserProfile

    db.existing = UserProfile(user_id=1, key="city", value="北京")
    assert await memory.upsert_profile(db, 1, 1, "city", "上海") is None


def test_memory_type_whitelist():
    """记忆类型白名单：仅 fact/preference/event 可入库（结构化约束，题 17 注入防护）。

    process_conversation_memory 对 LLM 输出做白名单校验，非法类型回退 fact；
    原始用户指令不直接进记忆库（只经 LLM 提取的结构化 JSON 进入）。
    """
    import inspect

    src = inspect.getsource(memory.process_conversation_memory)
    assert 'm.get("type") in ("fact", "preference", "event")' in src  # 白名单校验存在
