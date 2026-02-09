"""搜索源注册表。

管理所有可用的搜索源实现。
"""

import logging
import threading
from typing import Callable, Type

logger = logging.getLogger(__name__)

from src.search.base import SearchProviderType, SearchTool


class SearchProviderRegistry:
    """搜索源注册表。

    单例模式，管理所有搜索源的注册和获取。
    """

    _instance: "SearchProviderRegistry | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "SearchProviderRegistry":
        """获取单例实例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._providers: dict[SearchProviderType, Callable[[], SearchTool]] = {}
                    cls._instance._singletons: dict[SearchProviderType, SearchTool] = {}
        return cls._instance

    def register(
        self,
        provider_type: SearchProviderType,
        factory: Callable[[], SearchTool] | Type[SearchTool],
    ) -> None:
        """注册搜索源工厂函数。

        Args:
            provider_type: 搜索源类型
            factory: 工厂函数或类，用于创建搜索源实例
        """
        self._providers[provider_type] = factory

    def unregister(self, provider_type: SearchProviderType) -> None:
        """注销搜索源。

        Args:
            provider_type: 搜索源类型
        """
        self._providers.pop(provider_type, None)
        self._singletons.pop(provider_type, None)

    def get_provider(
        self,
        provider_type: SearchProviderType,
        force_new: bool = False,
    ) -> SearchTool | None:
        """获取搜索源实例。

        Args:
            provider_type: 搜索源类型
            force_new: 是否强制创建新实例

        Returns:
            搜索源实例，不存在时返回 None
        """
        factory = self._providers.get(provider_type)
        if factory is None:
            return None

        # 返回单例或创建新实例
        if not force_new and provider_type in self._singletons:
            return self._singletons[provider_type]

        try:
            instance = factory() if callable(factory) else factory
            if not force_new:
                self._singletons[provider_type] = instance
            return instance
        except Exception as e:
            logger.warning(f"Failed to create provider {provider_type}: {e}")
            return None

    def list_available(self) -> list[SearchProviderType]:
        """列出所有已注册的搜索源类型。

        Returns:
            搜索源类型列表
        """
        return list(self._providers.keys())

    def list_available_with_health(self) -> dict[SearchProviderType, bool]:
        """列出所有已注册的搜索源及其健康状态。

        Returns:
            搜索源类型到健康状态的映射
        """
        result = {}
        for provider_type in self._providers:
            provider = self.get_provider(provider_type)
            if provider:
                result[provider_type] = provider.check_health()
            else:
                result[provider_type] = False
        return result

    def clear(self) -> None:
        """清空所有注册的搜索源。"""
        self._providers.clear()
        self._singletons.clear()


# 全局注册表实例
registry = SearchProviderRegistry()
