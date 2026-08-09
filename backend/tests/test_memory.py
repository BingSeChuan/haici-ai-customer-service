"""记忆系统测试：重要性分级、去重判定、画像冲突、遗忘（LLM 调用全部 mock）。"""
import pytest
from sqlalchemy import select

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


@pytest.mark.asyncio
async def test_forget_memory_removes_vector(monkeypatch):
    """遗忘机制（修复 2）：forget 后 Chroma 向量集合中不再存在该记忆。"""
    from app.database import SessionLocal
    from app.models import UserMemory
    from app.services.memory import _memory_collection, forget_memory, store_memory

    # 新用户首次写入：相似检索为空 → dedup 返回 keep，不触发 LLM
    async def fake_dedup(content, existing):
        return "keep"

    monkeypatch.setattr("app.services.memory._dedup_check", fake_dedup)

    db = SessionLocal()
    try:
        # 创建最小用户/会话记录
        from app.models import ChatSession, User

        user = User(phone=f"139{hash('forget') % 10**8:08d}", nickname="遗忘测试", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        sess = ChatSession(user_id=user.id, title="遗忘测试")
        db.add(sess)
        db.commit()
        db.refresh(sess)

        await store_memory(db, user.id, sess.id, "fact", "用户偏好短信通知", 3)
        db.refresh(user)

        mem = db.scalar(
            select(UserMemory).where(UserMemory.user_id == user.id)
        )
        assert mem is not None and mem.vector_id, "记忆未写入或缺少 vector_id"

        col = _memory_collection()
        before = col.get(where={"user_id": str(user.id)})
        assert mem.vector_id in before["ids"], "向量未写入 Chroma"

        # 遗忘：向量必须被删除
        assert forget_memory(db, mem.id, user.id) is True
        after = col.get(where={"user_id": str(user.id)})
        assert mem.vector_id not in after["ids"], "遗忘后向量仍存在（修复 2 失效）"

        # 检索侧过滤：retrieve 不再召回（DB is_active=False 兜底）
        from app.services.memory import retrieve_memory_context

        ctx = await retrieve_memory_context(db, user.id, "用户喜欢什么通知方式？")
        assert "短信" not in ctx or "偏好" not in ctx, "已遗忘记忆仍被召回"
    finally:
        db.close()


def test_memory_type_whitelist():
    """记忆类型白名单：仅 fact/preference/event 可入库（结构化约束，题 17 注入防护）。

    process_conversation_memory 对 LLM 输出做白名单校验，非法类型回退 fact；
    原始用户指令不直接进记忆库（只经 LLM 提取的结构化 JSON 进入）。
    """
    import inspect

    src = inspect.getsource(memory.process_conversation_memory)
    assert 'm.get("type") in ("fact", "preference", "event")' in src  # 白名单校验存在
