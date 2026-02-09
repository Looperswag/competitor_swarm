"""LLM 客户端模块。

封装 GLM API（通过 Anthropic SDK 兼容接口）。
"""

import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any

import anthropic

from src.utils.config import get_env, get_config


class _GlobalRateLimiter:
    """全局 LLM 节流器：限制并发 + 请求间隔，避免短时间爆量。"""

    def __init__(self, max_concurrent: int, min_interval_seconds: float) -> None:
        self._semaphore = threading.Semaphore(max_concurrent)
        self._min_interval = max(0.0, min_interval_seconds)
        self._lock = threading.Lock()
        self._last_start = 0.0
        self._cooldown_until = 0.0

    def acquire(self) -> None:
        self._semaphore.acquire()
        self._wait_for_slot()

    def release(self) -> None:
        self._semaphore.release()

    def _wait_for_slot(self) -> None:
        if self._min_interval <= 0:
            self._wait_for_cooldown()
            return
        with self._lock:
            now = time.monotonic()
            wait = max(
                self._cooldown_until - now,
                self._min_interval - (now - self._last_start),
            )
            if wait > 0:
                time.sleep(wait)
            self._last_start = time.monotonic()

    def _wait_for_cooldown(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._cooldown_until - now
            if wait > 0:
                time.sleep(wait)

    def cool_down(self, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    def __enter__(self) -> "_GlobalRateLimiter":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _build_global_rate_limiter() -> _GlobalRateLimiter:
    """从环境变量构建全局节流器。"""
    max_concurrent = int(os.getenv("LLM_MAX_CONCURRENT", "1"))
    min_interval_ms = int(os.getenv("LLM_MIN_INTERVAL_MS", "300"))

    if max_concurrent <= 0:
        max_concurrent = 1
    if min_interval_ms < 0:
        min_interval_ms = 0

    return _GlobalRateLimiter(
        max_concurrent=max_concurrent,
        min_interval_seconds=min_interval_ms / 1000.0,
    )


_GLOBAL_RATE_LIMITER = _build_global_rate_limiter()


@dataclass(frozen=True)
class Message:
    """消息类。"""

    role: str
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """LLM 响应类。"""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    thinking_content: str | None = None


@dataclass
class LLMUsageStats:
    """使用统计。"""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    total_cost_estimate: float = 0.0  # 人民币


class LLMClient:
    """GLM API 客户端。

    使用 Anthropic SDK 连接智谱 GLM API。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        """初始化客户端。

        Args:
            api_key: API 密钥，默认从环境变量 ZHIPUAI_API_KEY 读取
            base_url: API 基础 URL，默认使用智谱兼容接口
            model: 模型名称，默认从配置读取
        """
        self._api_key = api_key or get_env("ZHIPUAI_API_KEY")
        self._base_url = base_url or "https://open.bigmodel.cn/api/anthropic"

        config = get_config()
        self._model = model or config.model.name
        self._temperature = config.model.temperature
        self._max_tokens = config.model.max_tokens
        self._thinking_mode = config.model.thinking_mode
        self._timeout = config.model.timeout  # 超时配置

        self._client = anthropic.Anthropic(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,  # 设置超时
        )

        self._stats = LLMUsageStats()

    @property
    def stats(self) -> LLMUsageStats:
        """获取使用统计。"""
        return self._stats

    def chat(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking_mode: bool | None = None,
    ) -> LLMResponse:
        """发送聊天请求。

        Args:
            messages: 消息列表
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            thinking_mode: 是否启用思考模式

        Returns:
            LLM 响应对象
        """
        # 转换消息格式
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        # 构建请求参数
        params: dict[str, Any] = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": max_tokens or self._max_tokens,
        }

        if system_prompt:
            params["system"] = system_prompt

        if temperature is not None:
            params["temperature"] = temperature
        elif self._temperature > 0:
            params["temperature"] = self._temperature

        # 思考模式
        if thinking_mode or self._thinking_mode:
            params["thinking"] = {"type": "enabled", "budget_tokens": 10000}

        # 重试逻辑
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                with _GLOBAL_RATE_LIMITER:
                    response = self._client.messages.create(**params)

                # 解析响应 - 兼容 ThinkingBlock 和 TextBlock
                content = ""
                thinking = None

                for block in response.content:
                    block_type = getattr(block, "type", "")
                    if block_type == "text":
                        content = getattr(block, "text", "")
                    elif block_type == "thinking":
                        thinking = getattr(block, "thinking", None)

                # 如果没有找到 text 内容，尝试其他方式获取
                if not content and len(response.content) > 0:
                    for block in response.content:
                        if hasattr(block, "text"):
                            content = block.text
                            break

                # 确保 content 不为空（使用 thinking 作为后备）
                if not content and thinking:
                    content = thinking

                # 计算 token 使用
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens

                # 更新统计
                self._stats.total_input_tokens += input_tokens
                self._stats.total_output_tokens += output_tokens
                self._stats.total_requests += 1

                return LLMResponse(
                    content=content,
                    model=response.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    thinking_content=thinking,
                )

            except anthropic.RateLimitError as e:
                last_error = e
                _GLOBAL_RATE_LIMITER.cool_down(min(5 * (attempt + 1), 30))
                if attempt < max_retries - 1:
                    wait_time = min(2 ** attempt, 10)  # 限制最大等待时间为 10 秒
                    time.sleep(wait_time)
                    continue
                raise

            except anthropic.APITimeoutError as e:
                # 专门处理超时错误
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise

            except anthropic.APIError as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise

        raise RuntimeError(f"Failed after {max_retries} retries: {last_error}")

    def reset_stats(self) -> None:
        """重置使用统计。"""
        self._stats = LLMUsageStats()

    def get_cost_estimate(self) -> float:
        """估算成本（人民币）。

        GLM-4.7 定价（仅供参考）：
        - 输入: ¥0.5 / 1M tokens
        - 输出: ¥2.0 / 1M tokens

        Returns:
            估算成本（人民币）
        """
        input_cost = self._stats.total_input_tokens * 0.5 / 1_000_000
        output_cost = self._stats.total_output_tokens * 2.0 / 1_000_000
        return input_cost + output_cost


# 全局客户端实例（延迟加载）
_client: LLMClient | None = None


def get_client() -> LLMClient:
    """获取全局 LLM 客户端实例。

    Returns:
        LLM 客户端
    """
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_client() -> None:
    """重置全局 LLM 客户端。"""
    global _client
    _client = None
