"""多源搜索工具。

支持多个搜索源的聚合、降级和负载均衡。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

from src.search.aggregator import (
    AggregatedResult,
    ResultAggregator,
    SortStrategy,
)
from src.search.base import (
    ProviderMetadata,
    SearchProviderType,
    SearchResult,
    SearchTimeRange,
    SearchTool,
)
from src.search.cache import SearchCache
from src.search.quota import QuotaManager
from src.search.registry import registry


class MultiSourceSearchTool(SearchTool):
    """多源搜索工具。

    支持多个搜索源的聚合、降级和负载均衡。
    """

    def __init__(
        self,
        preferred_providers: list[SearchProviderType] | None = None,
        agent_type: str | None = None,
        cache_enabled: bool = True,
        cache_ttl: int = 3600,
        quota_enabled: bool = True,
        aggregation_mode: str = "priority",
        max_parallel_providers: int = 2,
    ) -> None:
        """初始化多源搜索工具。

        Args:
            preferred_providers: 首选搜索源列表
            agent_type: Agent 类型，用于选择默认搜索源
            cache_enabled: 是否启用缓存
            cache_ttl: 缓存过期时间（秒）
            quota_enabled: 是否启用配额管理
            aggregation_mode: 聚合模式
                - "priority": 优先使用第一个可用搜索源
                - "parallel": 并行使用多个搜索源
                - "all": 使用所有可用搜索源
            max_parallel_providers: 最大并行搜索源数量
        """
        self._agent_type = agent_type
        self._aggregation_mode = aggregation_mode
        self._max_parallel_providers = max_parallel_providers

        # 根据配置选择搜索源
        self._preferred_providers = (
            preferred_providers
            or self._get_default_providers_for_agent(agent_type)
        )

        # 初始化缓存
        self._cache = SearchCache(
            cache_dir="data/cache/search",
            default_ttl=cache_ttl,
            enabled=cache_enabled,
        )

        # 初始化配额管理
        self._quota_manager = QuotaManager() if quota_enabled else None

        # 初始化聚合器
        self._aggregator = ResultAggregator(
            deduplication_enabled=True,
            sort_strategy=SortStrategy.SCORE,
        )

        # 注册默认搜索源（如果尚未注册）
        self._register_default_providers()

        logger.info(f"MultiSourceSearchTool initialized with providers: {[p.value for p in self._preferred_providers]}")

    def _register_default_providers(self) -> None:
        """注册默认搜索源。"""
        from src.search.providers.tavily import TavilySearchTool
        from src.search.providers.duckduckgo import DuckDuckGoSearchTool
        from src.search.providers.wikipedia import WikipediaSearchTool
        from src.search.providers.skill_fallback import SkillFallbackSearchTool

        # 只在尚未注册时注册
        if SearchProviderType.TAVILY not in registry.list_available():
            registry.register(SearchProviderType.TAVILY, TavilySearchTool)
        if SearchProviderType.DUCKDUCKGO not in registry.list_available():
            registry.register(SearchProviderType.DUCKDUCKGO, DuckDuckGoSearchTool)
        if SearchProviderType.WIKIPEDIA not in registry.list_available():
            registry.register(SearchProviderType.WIKIPEDIA, WikipediaSearchTool)
        if SearchProviderType.SKILL_FALLBACK not in registry.list_available():
            registry.register(SearchProviderType.SKILL_FALLBACK, SkillFallbackSearchTool)

    @staticmethod
    def _get_default_providers_for_agent(agent_type: str | None) -> list[SearchProviderType]:
        """根据 Agent 类型获取默认搜索源。

        Args:
            agent_type: Agent 类型

        Returns:
            搜索源类型列表
        """
        # Agent 到搜索源的映射
        agent_providers = {
            "scout": [
                SearchProviderType.TAVILY,
                SearchProviderType.DUCKDUCKGO,
                SearchProviderType.WIKIPEDIA,
            ],
            "experience": [
                SearchProviderType.TAVILY,
                SearchProviderType.DUCKDUCKGO,
            ],
            "technical": [
                SearchProviderType.TAVILY,
                SearchProviderType.DUCKDUCKGO,
            ],
            "market": [
                SearchProviderType.TAVILY,
                SearchProviderType.DUCKDUCKGO,
            ],
            "red_team": [
                SearchProviderType.TAVILY,
                SearchProviderType.DUCKDUCKGO,
            ],
            "blue_team": [
                SearchProviderType.TAVILY,
                SearchProviderType.WIKIPEDIA,
            ],
            "elite": [
                SearchProviderType.TAVILY,
                SearchProviderType.DUCKDUCKGO,
                SearchProviderType.WIKIPEDIA,
            ],
        }

        return agent_providers.get(agent_type, [
            SearchProviderType.TAVILY,
            SearchProviderType.DUCKDUCKGO,
        ])

    def search(
        self,
        query: str,
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """执行多源搜索。

        Args:
            query: 搜索查询
            time_range: 时间范围
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        # 检查缓存
        cached = self._cache.get(query, time_range, max_results)
        if cached is not None:
            logger.info(f"Using cached results for query: {query[:50]}...")
            return cached

        # 选择搜索源
        selected_providers = self._select_providers()

        if not selected_providers:
            logger.warning("No search providers available.")
            return []

        # 执行搜索
        provider_results = self._search_with_fallback(
            query, time_range, max_results, selected_providers
        )

        # 聚合结果
        aggregated = self._aggregator.aggregate(provider_results, max_results)

        # 缓存结果
        self._cache.set(query, aggregated.results, time_range, max_results)

        return aggregated.results

    def _select_providers(self) -> dict[SearchProviderType, SearchTool]:
        """选择可用搜索源。

        Returns:
            搜索源类型到搜索工具的映射
        """
        selected = {}

        for provider_type in self._preferred_providers:
            provider = registry.get_provider(provider_type)
            if provider and provider.check_health():
                selected[provider_type] = provider

        return selected

    def _search_with_fallback(
        self,
        query: str,
        time_range: SearchTimeRange,
        max_results: int,
        providers: dict[SearchProviderType, SearchTool],
    ) -> dict[SearchProviderType, list[SearchResult]]:
        """使用降级策略执行搜索。

        Args:
            query: 搜索查询
            time_range: 时间范围
            max_results: 最大结果数
            providers: 可用搜索源

        Returns:
            各搜索源的结果
        """
        results = {}

        if self._aggregation_mode == "priority":
            # 优先模式：使用第一个可用的搜索源
            for provider_type, provider in providers.items():
                # 检查配额
                if self._quota_manager:
                    if not self._quota_manager.check_and_consume(provider_type):
                        logger.warning(f"Quota exceeded for {provider_type.value}, skipping.")
                        continue

                try:
                    provider_results = provider.search(query, time_range, max_results)
                    if provider_results:
                        results[provider_type] = provider_results
                        logger.info(f"Got {len(provider_results)} results from {provider_type.value}")
                        break  # 使用第一个成功的搜索源
                except Exception as e:
                    logger.warning(f"Search with {provider_type.value} failed: {e}")

        elif self._aggregation_mode == "parallel":
            # 并行模式：使用多个搜索源
            count = 0
            for provider_type, provider in providers.items():
                if count >= self._max_parallel_providers:
                    break

                # 检查配额
                if self._quota_manager:
                    if not self._quota_manager.check_and_consume(provider_type):
                        continue

                try:
                    provider_results = provider.search(query, time_range, max_results)
                    if provider_results:
                        results[provider_type] = provider_results
                        logger.info(f"Got {len(provider_results)} results from {provider_type.value}")
                        count += 1
                except Exception as e:
                    logger.warning(f"Search with {provider_type.value} failed: {e}")

        else:  # "all" 或其他
            # 使用所有搜索源
            for provider_type, provider in providers.items():
                # 检查配额
                if self._quota_manager:
                    if not self._quota_manager.check_and_consume(provider_type):
                        continue

                try:
                    provider_results = provider.search(query, time_range, max_results)
                    if provider_results:
                        results[provider_type] = provider_results
                        logger.info(f"Got {len(provider_results)} results from {provider_type.value}")
                except Exception as e:
                    logger.warning(f"Search with {provider_type.value} failed: {e}")

        return results

    @property
    def metadata(self) -> ProviderMetadata:
        """获取搜索源元数据。"""
        return ProviderMetadata(
            provider_type=SearchProviderType.MULTI,
            is_available=len(self._preferred_providers) > 0,
            rate_limit=None,
            daily_quota=None,
            supports_time_range=True,  # 取决于使用的搜索源
            priority=0,
            description="多源聚合搜索",
        )

    def check_health(self) -> bool:
        """检查搜索源是否可用。

        Returns:
            True 表示至少有一个搜索源可用
        """
        selected = self._select_providers()
        return len(selected) > 0

    def get_cache_stats(self) -> dict[str, Any]:
        """获取缓存统计信息。"""
        return self._cache.get_stats()

    def get_quota_status(self) -> dict[str, Any]:
        """获取配额状态。"""
        if self._quota_manager is None:
            return {"enabled": False}

        return {
            "enabled": True,
            "providers": {
                k.value: v.__dict__
                for k, v in self._quota_manager.get_all_status().items()
            },
        }

    def clear_cache(self) -> None:
        """清空缓存。"""
        self._cache.clear()
