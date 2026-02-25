"""LLM 客户端测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.llm as llm_module
from src.llm import LLMClient, LLMResponse, Message


def _mock_config():
    return SimpleNamespace(
        model=SimpleNamespace(
            name="glm-4.7",
            temperature=0.0,
            max_tokens=512,
            thinking_mode=False,
            timeout=30.0,
        )
    )


@pytest.mark.asyncio
async def test_chat_async_uses_native_async_client(monkeypatch):
    """异步客户端可用时，chat_async 应调用原生 async SDK。"""
    async_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="async ok")],
        model="glm-4.7",
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )
    async_client = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(return_value=async_response))
    )

    monkeypatch.setattr("src.llm.get_config", _mock_config)
    monkeypatch.setattr("src.llm.get_env", lambda *_: "test-key")
    monkeypatch.setattr("src.llm.anthropic.Anthropic", lambda **_: MagicMock())
    monkeypatch.setattr("src.llm.anthropic.AsyncAnthropic", lambda **_: async_client)

    client = LLMClient()
    response = await client.chat_async(messages=[Message(role="user", content="hello")])

    assert response.content == "async ok"
    assert response.model == "glm-4.7"
    assert response.total_tokens == 18
    assert client.stats.total_requests == 1
    assert async_client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_chat_async_falls_back_to_sync_when_async_client_missing(monkeypatch):
    """异步客户端不可用时应回退到同步 chat。"""
    monkeypatch.setattr("src.llm.get_config", _mock_config)
    monkeypatch.setattr("src.llm.get_env", lambda *_: "test-key")
    monkeypatch.setattr("src.llm.anthropic.Anthropic", lambda **_: MagicMock())
    monkeypatch.setattr("src.llm.anthropic.AsyncAnthropic", lambda **_: MagicMock())

    client = LLMClient()
    client._async_client = None

    expected = LLMResponse(
        content="sync fallback",
        model="glm-4.7",
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
    )
    client.chat = MagicMock(return_value=expected)

    response = await client.chat_async(messages=[Message(role="user", content="hello")])

    assert response is expected
    client.chat.assert_called_once()


def test_retry_settings_default_values(monkeypatch):
    """默认配置应为应用层 1 次、SDK 层 0 次重试。"""
    monkeypatch.delenv("LLM_APP_MAX_RETRIES", raising=False)
    monkeypatch.delenv("LLM_SDK_MAX_RETRIES", raising=False)
    assert llm_module._load_retry_settings() == 1
    assert llm_module._load_sdk_retry_settings() == 0


def test_client_initializes_sdk_retries(monkeypatch):
    """LLMClient 应将 SDK 重试参数透传给 sync/async 客户端。"""
    captured: dict[str, dict] = {}

    def _fake_sync_client(**kwargs):
        captured["sync"] = kwargs
        return MagicMock()

    def _fake_async_client(**kwargs):
        captured["async"] = kwargs
        return MagicMock()

    monkeypatch.setenv("LLM_SDK_MAX_RETRIES", "0")
    monkeypatch.setenv("LLM_APP_MAX_RETRIES", "1")
    monkeypatch.setattr("src.llm.get_config", _mock_config)
    monkeypatch.setattr("src.llm.get_env", lambda *_: "test-key")
    monkeypatch.setattr("src.llm.anthropic.Anthropic", _fake_sync_client)
    monkeypatch.setattr("src.llm.anthropic.AsyncAnthropic", _fake_async_client)

    client = LLMClient()
    assert client._max_retries == 1
    assert captured["sync"]["max_retries"] == 0
    assert captured["async"]["max_retries"] == 0


@pytest.mark.asyncio
async def test_chat_async_logs_single_attempt_when_retry_is_one(monkeypatch):
    """应用层重试为 1 时，成功日志应记录 1/1 尝试。"""
    async_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        model="glm-4.7",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    async_create = AsyncMock(return_value=async_response)
    async_client = SimpleNamespace(messages=SimpleNamespace(create=async_create))

    info_calls: list[tuple] = []

    def _capture_info(*args, **kwargs):
        info_calls.append(args)

    monkeypatch.setenv("LLM_APP_MAX_RETRIES", "1")
    monkeypatch.setenv("LLM_SDK_MAX_RETRIES", "0")
    monkeypatch.setattr("src.llm.get_config", _mock_config)
    monkeypatch.setattr("src.llm.get_env", lambda *_: "test-key")
    monkeypatch.setattr("src.llm.anthropic.Anthropic", lambda **_: MagicMock())
    monkeypatch.setattr("src.llm.anthropic.AsyncAnthropic", lambda **_: async_client)
    monkeypatch.setattr(llm_module.logger, "info", _capture_info)

    client = LLMClient()
    response = await client.chat_async(messages=[Message(role="user", content="hello")])

    assert response.content == "ok"
    assert async_create.await_count == 1
    assert any(
        len(call) >= 4 and call[2] == 1 and call[3] == 1
        for call in info_calls
    )
