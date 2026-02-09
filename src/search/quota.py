"""搜索配额和速率限制管理。

跟踪每日配额使用，实现速率限制检查。
"""

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from src.search.base import SearchProviderType


@dataclass(frozen=True)
class QuotaStatus:
    """配额状态数据类。"""

    provider_type: SearchProviderType
    daily_limit: int | None
    daily_used: int
    daily_remaining: int | None
    rate_limit: int | None  # 每分钟请求限制
    rate_window_used: int  # 当前时间窗口内使用的请求数
    reset_time: str | None  # 配额重置时间


@dataclass
class RateLimitWindow:
    """速率限制时间窗口。"""

    count: int = 0
    window_start: float = field(default_factory=time.time)


class QuotaManager:
    """配额管理器。

    跟踪每日配额使用，实现速率限制检查。
    """

    # 默认速率限制窗口：60秒
    WINDOW_SIZE = 60

    def __init__(
        self,
        quota_file: str | Path = "data/cache/quota.json",
    ) -> None:
        """初始化配额管理器。

        Args:
            quota_file: 配额数据存储文件
        """
        self._quota_file = Path(quota_file)
        self._lock = threading.RLock()

        # 每日配额使用记录
        self._daily_usage: dict[SearchProviderType, int] = defaultdict(int)

        # 每日配额限制
        self._daily_limits: dict[SearchProviderType, int | None] = {}

        # 速率限制
        self._rate_limits: dict[SearchProviderType, int | None] = {}

        # 速率限制时间窗口
        self._rate_windows: dict[SearchProviderType, RateLimitWindow] = defaultdict(
            lambda: RateLimitWindow()
        )

        # 最后重置日期
        self._last_reset_date: str | None = None

        # 创建缓存目录
        self._quota_file.parent.mkdir(parents=True, exist_ok=True)

        # 加载保存的配额数据
        self._load()

    def configure_provider(
        self,
        provider_type: SearchProviderType,
        daily_limit: int | None = None,
        rate_limit: int | None = None,
    ) -> None:
        """配置搜索源的配额限制。

        Args:
            provider_type: 搜索源类型
            daily_limit: 每日配额限制，None 表示无限制
            rate_limit: 每分钟速率限制，None 表示无限制
        """
        with self._lock:
            self._daily_limits[provider_type] = daily_limit
            self._rate_limits[provider_type] = rate_limit

    def check_and_consume(
        self,
        provider_type: SearchProviderType,
        cost: int = 1,
    ) -> bool:
        """检查并消耗配额。

        Args:
            provider_type: 搜索源类型
            cost: 本次请求消耗的配额

        Returns:
            True 表示配额充足，False 表示已达限制
        """
        with self._lock:
            # 检查是否需要重置每日配额
            self._check_daily_reset()

            # 检查每日配额
            daily_limit = self._daily_limits.get(provider_type)
            if daily_limit is not None:
                if self._daily_usage[provider_type] + cost > daily_limit:
                    print(
                        f"Warning: Daily quota exceeded for {provider_type.value} "
                        f"({self._daily_usage[provider_type]}/{daily_limit})"
                    )
                    return False

            # 检查速率限制
            rate_limit = self._rate_limits.get(provider_type)
            if rate_limit is not None:
                window = self._rate_windows[provider_type]
                current_time = time.time()

                # 检查是否需要重置时间窗口
                if current_time - window.window_start > self.WINDOW_SIZE:
                    window.count = 0
                    window.window_start = current_time

                if window.count + cost > rate_limit:
                    print(
                        f"Warning: Rate limit exceeded for {provider_type.value} "
                        f"({window.count}/{rate_limit} per {self.WINDOW_SIZE}s)"
                    )
                    return False

            # 消耗配额
            self._daily_usage[provider_type] += cost
            self._rate_windows[provider_type].count += cost

            # 保存状态
            self._save()

            return True

    def get_status(self, provider_type: SearchProviderType) -> QuotaStatus:
        """获取搜索源的配额状态。

        Args:
            provider_type: 搜索源类型

        Returns:
            配额状态
        """
        with self._lock:
            self._check_daily_reset()

            daily_limit = self._daily_limits.get(provider_type)
            daily_used = self._daily_usage.get(provider_type, 0)

            # 计算剩余配额
            if daily_limit is None:
                daily_remaining = None
            else:
                daily_remaining = max(0, daily_limit - daily_used)

            # 计算重置时间
            reset_time = None
            if self._last_reset_date:
                try:
                    reset_date = datetime.strptime(
                        self._last_reset_date, "%Y-%m-%d"
                    ) + timedelta(days=1)
                    reset_time = reset_date.isoformat()
                except Exception:
                    pass

            # 获取当前窗口使用量
            rate_limit = self._rate_limits.get(provider_type)
            window = self._rate_windows.get(provider_type)
            rate_window_used = window.count if window else 0

            return QuotaStatus(
                provider_type=provider_type,
                daily_limit=daily_limit,
                daily_used=daily_used,
                daily_remaining=daily_remaining,
                rate_limit=rate_limit,
                rate_window_used=rate_window_used,
                reset_time=reset_time,
            )

    def reset_daily(self, provider_type: SearchProviderType | None = None) -> None:
        """重置每日配额。

        Args:
            provider_type: 搜索源类型，None 表示重置所有
        """
        with self._lock:
            if provider_type is None:
                self._daily_usage.clear()
            else:
                self._daily_usage[provider_type] = 0

            self._save()

    def reset_rate_window(self, provider_type: SearchProviderType | None = None) -> None:
        """重置速率限制窗口。

        Args:
            provider_type: 搜索源类型，None 表示重置所有
        """
        with self._lock:
            if provider_type is None:
                self._rate_windows.clear()
            else:
                self._rate_windows[provider_type] = RateLimitWindow()

            self._save()

    def _check_daily_reset(self) -> None:
        """检查是否需要重置每日配额。"""
        current_date = datetime.now().strftime("%Y-%m-%d")

        if self._last_reset_date != current_date:
            # 新的一天，重置每日配额
            self._daily_usage.clear()
            self._last_reset_date = current_date

            # 重置速率窗口
            for window in self._rate_windows.values():
                window.count = 0
                window.window_start = time.time()

            self._save()

    def _save(self) -> None:
        """保存配额数据到文件。"""
        try:
            data = {
                "last_reset_date": self._last_reset_date,
                "daily_usage": {
                    k.value: v for k, v in self._daily_usage.items()
                },
                "daily_limits": {
                    k.value: v for k, v in self._daily_limits.items()
                    if v is not None
                },
                "rate_limits": {
                    k.value: v for k, v in self._rate_limits.items()
                    if v is not None
                },
            }

            with open(self._quota_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save quota data: {e}")

    def _load(self) -> None:
        """从文件加载配额数据。"""
        if not self._quota_file.exists():
            return

        try:
            with open(self._quota_file, "r") as f:
                data = json.load(f)

            self._last_reset_date = data.get("last_reset_date")

            # 加载每日使用量
            for provider_str, usage in data.get("daily_usage", {}).items():
                try:
                    provider = SearchProviderType(provider_str)
                    self._daily_usage[provider] = usage
                except ValueError:
                    pass

            # 加载每日限制
            for provider_str, limit in data.get("daily_limits", {}).items():
                try:
                    provider = SearchProviderType(provider_str)
                    self._daily_limits[provider] = limit
                except ValueError:
                    pass

            # 加载速率限制
            for provider_str, limit in data.get("rate_limits", {}).items():
                try:
                    provider = SearchProviderType(provider_str)
                    self._rate_limits[provider] = limit
                except ValueError:
                    pass

        except Exception as e:
            logger.warning(f"Failed to load quota data: {e}")

    def get_all_status(self) -> dict[SearchProviderType, QuotaStatus]:
        """获取所有搜索源的配额状态。

        Returns:
            搜索源到配额状态的映射
        """
        with self._lock:
            self._check_daily_reset()

            result = {}
            # 包含所有配置过的搜索源
            for provider in set(
                list(self._daily_limits.keys())
                + list(self._rate_limits.keys())
                + list(self._daily_usage.keys())
            ):
                result[provider] = self.get_status(provider)

            return result
