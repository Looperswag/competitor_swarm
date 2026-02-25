"""LLM 客户端模块。

封装 GLM API（通过 Anthropic SDK 兼容接口）。
"""

import os
import asyncio
import time
import threading
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from src.utils.config import get_env, get_config

logger = logging.getLogger(__name__)


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


class _AsyncGlobalRateLimiter:
    """异步全局 LLM 节流器（事件循环安全）。

    asyncio.Semaphore / asyncio.Lock 会隐式绑定到创建时的事件循环。
    当模块级实例在导入阶段创建后，若后续在不同事件循环中使用（如
    asyncio.run() 创建的临时循环），会触发 "bound to a different event
    loop" 错误。因此这里采用懒加载：首次 acquire 时才创建原语，并在
    事件循环切换时自动重建。
    """

    def __init__(self, max_concurrent: int, min_interval_seconds: float) -> None:
        self._max_concurrent = max_concurrent
        self._min_interval = max(0.0, min_interval_seconds)
        self._last_start = 0.0
        self._cooldown_until = 0.0
        # 懒加载：不在 __init__ 中创建 asyncio 原语
        self._semaphore: asyncio.Semaphore | None = None
        self._lock: asyncio.Lock | None = None
        self._bound_loop: asyncio.AbstractEventLoop | None = None

    def _ensure_primitives(self) -> None:
        """确保 asyncio 原语绑定到当前运行的事件循环。"""
        loop = asyncio.get_running_loop()
        if self._bound_loop is not loop:
            self._semaphore = asyncio.Semaphore(self._max_concurrent)
            self._lock = asyncio.Lock()
            self._bound_loop = loop

    async def acquire(self) -> None:
        self._ensure_primitives()
        await self._semaphore.acquire()
        await self._wait_for_slot()

    def release(self) -> None:
        if self._semaphore is not None:
            self._semaphore.release()

    async def _wait_for_slot(self) -> None:
        if self._min_interval <= 0:
            await self._wait_for_cooldown()
            return
        async with self._lock:
            now = time.monotonic()
            wait = max(
                self._cooldown_until - now,
                self._min_interval - (now - self._last_start),
            )
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_start = time.monotonic()

    async def _wait_for_cooldown(self) -> None:
        async with self._lock:
            wait = self._cooldown_until - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)

    async def cool_down(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._ensure_primitives()
        async with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    async def __aenter__(self) -> "_AsyncGlobalRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()


def _load_rate_limit_settings() -> tuple[int, float]:
    """从环境变量加载并校验限流设置。"""
    max_concurrent = int(os.getenv("LLM_MAX_CONCURRENT", "2"))
    min_interval_ms = int(os.getenv("LLM_MIN_INTERVAL_MS", "300"))

    if max_concurrent <= 0:
        max_concurrent = 1
    if min_interval_ms < 0:
        min_interval_ms = 0

    return max_concurrent, min_interval_ms / 1000.0


def _load_retry_settings() -> int:
    """加载应用层重试次数（不含 SDK 内部重试）。"""
    try:
        max_retries = int(os.getenv("LLM_APP_MAX_RETRIES", "1"))
    except ValueError:
        max_retries = 1
    if max_retries <= 0:
        return 1
    return max_retries


def _load_sdk_retry_settings() -> int:
    """加载 SDK 层重试次数。"""
    try:
        max_retries = int(os.getenv("LLM_SDK_MAX_RETRIES", "0"))
    except ValueError:
        max_retries = 0
    return max(0, max_retries)


def _build_global_rate_limiter() -> _GlobalRateLimiter:
    max_concurrent, min_interval_seconds = _load_rate_limit_settings()
    return _GlobalRateLimiter(
        max_concurrent=max_concurrent,
        min_interval_seconds=min_interval_seconds,
    )


def _build_async_global_rate_limiter() -> _AsyncGlobalRateLimiter:
    max_concurrent, min_interval_seconds = _load_rate_limit_settings()
    return _AsyncGlobalRateLimiter(
        max_concurrent=max_concurrent,
        min_interval_seconds=min_interval_seconds,
    )


_GLOBAL_RATE_LIMITER = _build_global_rate_limiter()
_ASYNC_GLOBAL_RATE_LIMITER = _build_async_global_rate_limiter()


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
        self._max_retries = _load_retry_settings()
        self._sdk_max_retries = _load_sdk_retry_settings()

        self._client = anthropic.Anthropic(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,  # 设置超时
            max_retries=self._sdk_max_retries,
        )
        async_client_cls = getattr(anthropic, "AsyncAnthropic", None)
        self._async_client = (
            async_client_cls(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout,
                max_retries=self._sdk_max_retries,
            )
            if async_client_cls is not None
            else None
        )

        self._stats = LLMUsageStats()
        self._stats_lock = threading.Lock()

    @property
    def stats(self) -> LLMUsageStats:
        """获取使用统计。"""
        return self._stats

    def _build_params(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking_mode: bool | None = None,
    ) -> dict[str, Any]:
        """构建统一的 SDK 请求参数。"""
        params: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens or self._max_tokens,
        }

        if system_prompt:
            params["system"] = system_prompt

        if temperature is not None:
            params["temperature"] = temperature
        elif self._temperature > 0:
            params["temperature"] = self._temperature

        if thinking_mode or self._thinking_mode:
            params["thinking"] = {"type": "enabled", "budget_tokens": 10000}

        return params

    @staticmethod
    def _parse_response_content(response: Any) -> tuple[str, str | None]:
        """解析文本内容和思考内容。"""
        text_parts: list[str] = []
        thinking_parts: list[str] = []

        for block in getattr(response, "content", []):
            block_type = getattr(block, "type", "")
            if block_type == "text":
                text = getattr(block, "text", "")
                if text:
                    text_parts.append(text)
            elif block_type == "thinking":
                thinking = getattr(block, "thinking", None)
                if thinking:
                    thinking_parts.append(thinking)
            elif hasattr(block, "text"):
                fallback_text = getattr(block, "text", "")
                if fallback_text:
                    text_parts.append(fallback_text)

        content = "\n".join(text_parts).strip()
        thinking_content = "\n".join(thinking_parts).strip() or None
        if not content and thinking_content:
            content = thinking_content
        return content, thinking_content

    def _build_llm_response(self, response: Any) -> LLMResponse:
        """将 SDK 响应转换为统一结构，并记录统计。"""
        content, thinking_content = self._parse_response_content(response)
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

        with self._stats_lock:
            self._stats.total_input_tokens += input_tokens
            self._stats.total_output_tokens += output_tokens
            self._stats.total_requests += 1

        return LLMResponse(
            content=content,
            model=getattr(response, "model", self._model),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            thinking_content=thinking_content,
        )

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
        params = self._build_params(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_mode=thinking_mode,
        )

        # 重试逻辑
        max_retries = self._max_retries
        last_error = None

        for attempt in range(max_retries):
            attempt_index = attempt + 1
            attempt_start = time.monotonic()
            try:
                with _GLOBAL_RATE_LIMITER:
                    response = self._client.messages.create(**params)
                elapsed = time.monotonic() - attempt_start
                logger.info(
                    "llm.chat success model=%s attempt=%s/%s elapsed=%.2fs",
                    self._model,
                    attempt_index,
                    max_retries,
                    elapsed,
                )
                return self._build_llm_response(response)

            except anthropic.RateLimitError as e:
                last_error = e
                elapsed = time.monotonic() - attempt_start
                logger.warning(
                    "llm.chat rate_limited model=%s attempt=%s/%s elapsed=%.2fs error=%s",
                    self._model,
                    attempt_index,
                    max_retries,
                    elapsed,
                    e,
                )
                _GLOBAL_RATE_LIMITER.cool_down(min(5 * (attempt + 1), 30))
                if attempt < max_retries - 1:
                    wait_time = min(2 ** attempt, 10)  # 限制最大等待时间为 10 秒
                    time.sleep(wait_time)
                    continue
                raise

            except anthropic.APITimeoutError as e:
                # 专门处理超时错误
                last_error = e
                elapsed = time.monotonic() - attempt_start
                logger.warning(
                    "llm.chat timeout model=%s attempt=%s/%s elapsed=%.2fs error=%s",
                    self._model,
                    attempt_index,
                    max_retries,
                    elapsed,
                    e,
                )
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise

            except anthropic.APIError as e:
                last_error = e
                elapsed = time.monotonic() - attempt_start
                logger.warning(
                    "llm.chat api_error model=%s attempt=%s/%s elapsed=%.2fs error=%s",
                    self._model,
                    attempt_index,
                    max_retries,
                    elapsed,
                    e,
                )
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise

        raise RuntimeError(f"Failed after {max_retries} retries: {last_error}")

    async def chat_async(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        thinking_mode: bool | None = None,
    ) -> LLMResponse:
        """异步聊天请求。

        优先使用原生 AsyncAnthropic；不可用时降级到线程包装同步实现。
        """
        if self._async_client is None:
            return await asyncio.to_thread(
                self.chat,
                messages,
                system_prompt,
                temperature,
                max_tokens,
                thinking_mode,
            )

        params = self._build_params(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_mode=thinking_mode,
        )

        max_retries = self._max_retries
        last_error: Exception | None = None

        for attempt in range(max_retries):
            attempt_index = attempt + 1
            attempt_start = time.monotonic()
            try:
                async with _ASYNC_GLOBAL_RATE_LIMITER:
                    response = await self._async_client.messages.create(**params)
                elapsed = time.monotonic() - attempt_start
                logger.info(
                    "llm.chat_async success model=%s attempt=%s/%s elapsed=%.2fs",
                    self._model,
                    attempt_index,
                    max_retries,
                    elapsed,
                )
                return self._build_llm_response(response)

            except anthropic.RateLimitError as e:
                last_error = e
                elapsed = time.monotonic() - attempt_start
                logger.warning(
                    "llm.chat_async rate_limited model=%s attempt=%s/%s elapsed=%.2fs error=%s",
                    self._model,
                    attempt_index,
                    max_retries,
                    elapsed,
                    e,
                )
                await _ASYNC_GLOBAL_RATE_LIMITER.cool_down(min(5 * (attempt + 1), 30))
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(2 ** attempt, 10))
                    continue
                raise

            except anthropic.APITimeoutError as e:
                last_error = e
                elapsed = time.monotonic() - attempt_start
                logger.warning(
                    "llm.chat_async timeout model=%s attempt=%s/%s elapsed=%.2fs error=%s",
                    self._model,
                    attempt_index,
                    max_retries,
                    elapsed,
                    e,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                raise

            except anthropic.APIError as e:
                last_error = e
                elapsed = time.monotonic() - attempt_start
                logger.warning(
                    "llm.chat_async api_error model=%s attempt=%s/%s elapsed=%.2fs error=%s",
                    self._model,
                    attempt_index,
                    max_retries,
                    elapsed,
                    e,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                raise

        raise RuntimeError(f"Failed after {max_retries} retries: {last_error}")

    def reset_stats(self) -> None:
        """重置使用统计。"""
        with self._stats_lock:
            self._stats = LLMUsageStats()

    def get_cost_estimate(self) -> float:
        """估算成本（人民币）。

        当前实现使用固定单价进行估算（仅供参考，请以当前模型官方最新定价为准）：
        - 输入: ¥0.5 / 1M tokens（参考）
        - 输出: ¥2.0 / 1M tokens（参考）

        Returns:
            估算成本（人民币）
        """
        with self._stats_lock:
            input_tokens = self._stats.total_input_tokens
            output_tokens = self._stats.total_output_tokens
        input_cost = input_tokens * 0.5 / 1_000_000
        output_cost = output_tokens * 2.0 / 1_000_000
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
