"""LLM 客户端封装（DeepSeek / 任意 OpenAI 兼容端点）。

职责：
- 流式对话（SSE 由上层转发）
- 超时 / 重试 / 显式错误信息（AI 模块异常处理要求）
- 意图识别、追问生成等一次性小调用
"""
import json
import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from ..config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.llm_api_key:
            raise RuntimeError(
                "未配置 LLM_API_KEY。请在 backend/.env 中填入你的 DeepSeek API Key（参考 .env.example）"
            )
        _client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
            max_retries=1,  # 网络抖动自动重试 1 次
        )
    return _client


async def chat_stream(
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 2000,
) -> AsyncIterator[str]:
    """流式对话：逐块产出文本增量。"""
    client = get_client()
    try:
        stream = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        logger.error("LLM 流式调用失败: %s", e)
        raise RuntimeError(f"LLM 调用失败: {type(e).__name__}: {e}")


async def chat_once(messages: list[dict], temperature: float = 0.3, max_tokens: int = 2000) -> str:
    """一次性对话（意图识别 / 追问生成用），返回完整文本。"""
    client = get_client()
    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        logger.error("LLM 一次性调用失败: %s", e)
        raise RuntimeError(f"LLM 调用失败: {type(e).__name__}: {e}")


async def chat_json(messages: list[dict], temperature: float = 0.1, max_tokens: int = 500) -> dict:
    """要求 LLM 输出 JSON 的调用，带容错解析。"""
    raw = await chat_once(messages, temperature=temperature, max_tokens=max_tokens)
    raw = raw.strip()
    # 去掉 ```json ... ``` 围栏
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 容错：截取第一个 { 到最后一个 } 之间的内容
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        logger.warning("LLM 未返回合法 JSON: %s", raw[:200])
        return {}
