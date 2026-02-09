"""多源结果聚合器。

合并和去重多个搜索源的结果。
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from src.search.base import SearchProviderType, SearchResult


@dataclass(frozen=True)
class AggregatedResult:
    """聚合结果数据类。"""

    results: list[SearchResult]
    total_count: int
    provider_counts: dict[SearchProviderType, int] = field(default_factory=dict)
    deduped_count: int = 0


class SortStrategy:
    """排序策略枚举。"""

    SCORE = "score"  # 按相关性评分
    LATEST = "latest"  # 按发布日期
    DIVERSE = "diverse"  # 多样性排序（混合来源）


class ResultAggregator:
    """结果聚合器。

    合并和去重多个搜索源的结果，支持多种排序策略。
    """

    def __init__(
        self,
        deduplication_enabled: bool = True,
        sort_strategy: str = SortStrategy.SCORE,
    ) -> None:
        """初始化聚合器。

        Args:
            deduplication_enabled: 是否启用去重
            sort_strategy: 排序策略
        """
        self._deduplication_enabled = deduplication_enabled
        self._sort_strategy = sort_strategy
        self._url_normalizer: Callable[[str], str] = self._normalize_url

    def aggregate(
        self,
        provider_results: dict[SearchProviderType, list[SearchResult]],
        max_results: int = 10,
    ) -> AggregatedResult:
        """聚合多个搜索源的结果。

        Args:
            provider_results: 各搜索源的结果映射
            max_results: 最大返回结果数

        Returns:
            聚合后的结果
        """
        # 收集所有结果
        all_results: list[SearchResult] = []
        provider_counts: dict[SearchProviderType, int] = defaultdict(int)

        for provider_type, results in provider_results.items():
            # 为每个结果添加来源标记
            tagged_results = [
                SearchResult(
                    url=r.url,
                    title=r.title,
                    summary=r.summary,
                    site_name=r.site_name,
                    published_date=r.published_date,
                    icon_url=r.icon_url,
                    score=r.score,
                    provider=provider_type,
                )
                for r in results
            ]
            all_results.extend(tagged_results)
            provider_counts[provider_type] = len(results)

        total_count = len(all_results)

        # 去重
        if self._deduplication_enabled:
            all_results = self._deduplicate(all_results)

        deduped_count = len(all_results)

        # 排序
        all_results = self._sort_results(all_results)

        # 限制结果数量
        all_results = all_results[:max_results]

        return AggregatedResult(
            results=all_results,
            total_count=total_count,
            provider_counts=dict(provider_counts),
            deduped_count=deduped_count,
        )

    def _deduplicate(self, results: list[SearchResult]) -> list[SearchResult]:
        """去重搜索结果。

        基于 URL 去重，保留评分最高的结果。

        Args:
            results: 搜索结果列表

        Returns:
            去重后的结果列表
        """
        seen_urls: dict[str, SearchResult] = {}

        for result in results:
            normalized_url = self._url_normalizer(result.url)
            if normalized_url not in seen_urls:
                seen_urls[normalized_url] = result
            else:
                # 保留评分更高的结果
                if result.score > seen_urls[normalized_url].score:
                    seen_urls[normalized_url] = result

        return list(seen_urls.values())

    def _sort_results(self, results: list[SearchResult]) -> list[SearchResult]:
        """排序搜索结果。

        Args:
            results: 搜索结果列表

        Returns:
            排序后的结果列表
        """
        if self._sort_strategy == SortStrategy.SCORE:
            return self._sort_by_score(results)
        elif self._sort_strategy == SortStrategy.LATEST:
            return self._sort_by_date(results)
        elif self._sort_strategy == SortStrategy.DIVERSE:
            return self._sort_by_diversity(results)
        else:
            return self._sort_by_score(results)

    def _sort_by_score(self, results: list[SearchResult]) -> list[SearchResult]:
        """按相关性评分排序。"""
        return sorted(results, key=lambda r: r.score, reverse=True)

    def _sort_by_date(self, results: list[SearchResult]) -> list[SearchResult]:
        """按发布日期排序。"""
        def sort_key(r: SearchResult) -> tuple:
            # 有日期的优先，然后按日期降序
            if r.published_date:
                return (1, r.published_date)
            return (0, "")

        return sorted(results, key=sort_key, reverse=True)

    def _sort_by_diversity(self, results: list[SearchResult]) -> list[SearchResult]:
        """按多样性排序（混合不同来源的结果）。

        从各搜索源交替选取结果，确保多样性。
        """
        # 按来源分组
        grouped: dict[SearchProviderType, list[SearchResult]] = defaultdict(list)
        for result in results:
            provider = result.provider or SearchProviderType.SKILL_FALLBACK
            grouped[provider].append(result)

        # 每组内按评分排序
        for provider in grouped:
            grouped[provider] = self._sort_by_score(grouped[provider])

        # 交替选取
        diversified: list[SearchResult] = []
        providers = list(grouped.keys())
        max_len = max((len(v) for v in grouped.values()), default=0)

        for i in range(max_len):
            for provider in providers:
                if i < len(grouped[provider]):
                    diversified.append(grouped[provider][i])

        return diversified

    @staticmethod
    def _normalize_url(url: str) -> str:
        """标准化 URL 用于去重比较。

        Args:
            url: 原始 URL

        Returns:
            标准化后的 URL
        """
        try:
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(url.lower())

            # 移除常见的跟踪参数
            query_params = []
            for param in parsed.query.split("&"):
                if param and not any(
                    tracking_prefix in param
                    for tracking_prefix in ["utm_", "fbclid=", "gclid="]
                ):
                    query_params.append(param)

            normalized = parsed._replace(
                scheme="https",  # 统一使用 https
                query="&".join(query_params),
                fragment="",  # 移除片段
            )

            return urlunparse(normalized)
        except Exception:
            return url.lower()
