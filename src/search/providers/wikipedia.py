"""Wikipedia 搜索源实现。

使用 Wikipedia API 获取百科信息。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

from src.search.base import (
    ProviderMetadata,
    SearchProviderType,
    SearchResult,
    SearchTimeRange,
    SearchTool,
)


class WikipediaSearchTool(SearchTool):
    """Wikipedia 搜索工具。

    使用 Wikipedia-API 获取百科信息，适合产品背景和概念解释。
    比原生的 wikipedia 库更稳定可靠。
    """

    def __init__(self, lang: str = "zh") -> None:
        """初始化 Wikipedia 搜索工具。

        Args:
            lang: Wikipedia 语言版本（默认中文）
        """
        self._lang = lang
        self._client: Any = None
        self._is_available = True
        self._init_client()

    def _init_client(self) -> None:
        """初始化 Wikipedia 客户端。"""
        try:
            import wikipediaapi

            self._client = wikipediaapi.Wikipedia(
                language=self._lang,
                extract_format=wikipediaapi.ExtractFormat.WIKI,
                user_agent="CompetitorSwarm/1.0 (https://github.com/competitor-swarm)"
            )
            logger.info(f"Wikipedia search initialized (lang={self._lang}).")
        except ImportError:
            logger.warning(
                "wikipedia-api not installed. Install with: pip install wikipedia-api"
            )
            self._is_available = False
        except Exception as e:
            logger.warning(f"Failed to initialize Wikipedia: {e}")
            self._is_available = False

    def search(
        self,
        query: str,
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """执行搜索。

        注意：Wikipedia 不支持时间范围过滤。

        Args:
            query: 搜索查询
            time_range: 时间范围（忽略）
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        if not self._is_available or self._client is None:
            return []

        try:
            # 使用 wikipedia-api 的搜索功能
            # wikipedia-api 本身不直接提供搜索，需要使用其 page 方法
            # 这里我们使用 pywiki 或直接尝试获取页面
            # 为了保持简单，我们使用一个简单的搜索策略

            # 尝试直接获取匹配的页面
            results = []

            # 首先尝试精确匹配
            page = self._client.page(query)
            if page.exists():
                results.append(self._create_result_from_page(page))

            # 如果需要更多结果，尝试一些变体
            if len(results) < max_results:
                # 尝试一些常见的搜索变体
                # 注意：wikipedia-api 不提供搜索 API，所以这里使用简单策略
                # 实际使用中可以考虑添加 wikipedia 库作为搜索依赖
                pass

            return results[:max_results]

        except Exception as e:
            logger.warning(f"Wikipedia search failed: {e}. Returning empty results.")
            return []

    def _create_result_from_page(self, page: Any) -> SearchResult:
        """从 Wikipedia 页面对象创建搜索结果。

        Args:
            page: Wikipedia 页面对象

        Returns:
            搜索结果
        """
        # 获取摘要（前 500 个字符）
        summary = page.summary[:500] if page.summary else ""

        # 清理摘要中的维基链接标记
        summary = self._clean_summary(summary)

        return SearchResult(
            url=page.fullurl,
            title=page.title,
            summary=summary,
            site_name="wikipedia.org",
            published_date=None,
            icon_url=None,
            score=0.8,
            provider=SearchProviderType.WIKIPEDIA,
        )

    @staticmethod
    def _clean_summary(summary: str) -> str:
        """清理摘要文本。

        移除维基链接标记和其他格式。

        Args:
            summary: 原始摘要

        Returns:
            清理后的摘要
        """
        # 移除维基链接 [[...]] 格式
        import re

        # 移除 [[link]] 格式，保留链接文本
        summary = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", summary)

        # 移除多余的空格
        summary = re.sub(r"\s+", " ", summary).strip()

        return summary

    @property
    def metadata(self) -> ProviderMetadata:
        """获取搜索源元数据。"""
        return ProviderMetadata(
            provider_type=SearchProviderType.WIKIPEDIA,
            is_available=self._is_available,
            rate_limit=None,
            daily_quota=0,  # 无限制
            supports_time_range=False,
            priority=20,
            description="Wikipedia - 免费百科全书",
        )

    def check_health(self) -> bool:
        """检查搜索源是否可用。

        Returns:
            True 表示可用，False 表示不可用
        """
        if not self._is_available:
            return False

        try:
            # 简单测试搜索 - 尝试获取一个已知存在的页面
            page = self._client.page("Python")
            return page.exists()
        except Exception:
            return False
