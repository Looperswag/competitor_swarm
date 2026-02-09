"""DuckDuckGo 搜索源实现。

使用 DuckDuckGo 进行免费搜索（无 API Key 限制）。
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


class DuckDuckGoSearchTool(SearchTool):
    """DuckDuckGo 搜索工具。

    使用 DuckDuckGo 进行免费搜索，无需 API Key。
    """

    def __init__(self) -> None:
        """初始化 DuckDuckGo 搜索工具。"""
        self._client: Any = None
        self._is_available = True
        self._init_client()

    def _init_client(self) -> None:
        """初始化 DuckDuckGo 客户端。"""
        try:
            # 使用新的 ddgs 包名（duckduckgo_search 已重命名）
            from ddgs import DDGS
            self._client = DDGS(timeout=30)
            logger.info("DuckDuckGo search initialized.")
        except ImportError:
            # 回退到旧包名
            try:
                from duckduckgo_search import DDGS
                self._client = DDGS(timeout=30)
                logger.info("DuckDuckGo search initialized (legacy package).")
            except ImportError:
                logger.warning(
                    "ddgs not installed. Install with: pip install ddgs"
                )
                self._is_available = False
        except Exception as e:
            logger.warning(f"Failed to initialize DuckDuckGo: {e}")
            self._is_available = False

    def search(
        self,
        query: str,
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """执行搜索。

        Args:
            query: 搜索查询
            time_range: 时间范围（DuckDuckGo 支持有限）
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        if not self._is_available or self._client is None:
            return []

        # DuckDuckGo 使用 time 参数过滤时间
        time_map = {
            SearchTimeRange.ONE_DAY: "d",
            SearchTimeRange.ONE_WEEK: "w",
            SearchTimeRange.ONE_MONTH: "m",
            SearchTimeRange.ONE_YEAR: "y",
            SearchTimeRange.NO_LIMIT: None,
        }

        time_param = time_map.get(time_range)

        # 重试逻辑（最多 3 次）- 使用 HTML 后端绕过 Bing 路由问题
        import time

        for attempt in range(3):
            try:
                if attempt > 0:
                    time.sleep(1)

                # 兼容新旧版本的 ddgs 包
                # 新版本使用 query 参数，旧版本使用 keywords 参数
                # 注意: ddgs >= 6.0.0 不再支持 "html" 后端，使用 "duckduckgo"
                kwargs = {
                    "max_results": max_results,
                    "backend": "duckduckgo",  # 新版本可用的后端
                }
                if time_param:
                    kwargs["timelimit"] = time_param

                # 尝试新版本 API (query 参数)
                try:
                    results = self._client.text(query, **kwargs)
                except TypeError:
                    # 回退到旧版本 API (keywords 参数)
                    results = self._client.text(keywords=query, **kwargs)

                if results is not None:
                    return self._parse_results(results)

            except Exception as e:
                if attempt == 2:
                    logger.warning(f"DuckDuckGo search failed after 3 attempts: {e}")
                    return []

        return []

    def _parse_results(self, data: list[dict[str, Any]]) -> list[SearchResult]:
        """解析搜索结果。

        Args:
            data: 搜索结果数据

        Returns:
            搜索结果列表
        """
        results = []

        for item in data:
            # 提取内容
            body = item.get("body", "")
            if not body:
                body = item.get("snippet", "")

            results.append(SearchResult(
                url=item.get("link", ""),
                title=item.get("title", ""),
                summary=body,
                site_name=self._extract_site_name(item.get("link", "")),
                published_date=None,  # DuckDuckGo 通常不提供发布日期
                icon_url=None,
                score=0.7,  # 默认评分
                provider=SearchProviderType.DUCKDUCKGO,
            ))

        return results

    @staticmethod
    def _extract_site_name(url: str) -> str | None:
        """从 URL 中提取站点名称。

        Args:
            url: URL 字符串

        Returns:
            站点名称
        """
        if not url:
            return None

        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc
        except Exception:
            return None

    @property
    def metadata(self) -> ProviderMetadata:
        """获取搜索源元数据。"""
        return ProviderMetadata(
            provider_type=SearchProviderType.DUCKDUCKGO,
            is_available=self._is_available,
            rate_limit=None,  # 无严格速率限制
            daily_quota=0,  # 无限制
            supports_time_range=True,
            priority=10,
            description="DuckDuckGo - 免费搜索引擎",
        )

    def check_health(self) -> bool:
        """检查搜索源是否可用。

        Returns:
            True 表示可用，False 表示不可用
        """
        if not self._is_available:
            return False

        try:
            # 简单测试搜索 - 使用 duckduckgo 后端
            # 兼容新旧版本
            try:
                results = self._client.text("test", max_results=1, backend="duckduckgo")
            except TypeError:
                results = self._client.text(keywords="test", max_results=1, backend="duckduckgo")
            return results is not None
        except Exception:
            return False
