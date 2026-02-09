"""Tavily 搜索源实现。

使用 Tavily API 进行搜索。
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

from src.search.base import (
    ProviderMetadata,
    SearchProviderType,
    SearchResult,
    SearchTimeRange,
    SearchTool,
)


class TavilySearchTool(SearchTool):
    """Tavily 搜索工具。

    使用 Tavily API 进行高质量搜索。
    """

    # Tavily API 端点
    API_BASE_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None) -> None:
        """初始化 Tavily 搜索工具。

        Args:
            api_key: Tavily API 密钥，默认从环境变量 TAVILY_API_KEY 读取
        """
        self._api_key = api_key or os.getenv("TAVILY_API_KEY")
        self._is_available = bool(self._api_key)
        self._client = httpx.Client(timeout=30.0)

        if not self._is_available:
            logger.warning("TAVILY_API_KEY not configured. Tavily search will be disabled.")
        else:
            logger.info("Tavily search initialized.")

    def search(
        self,
        query: str,
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """执行搜索。

        Args:
            query: 搜索查询
            time_range: 时间范围
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        if not self._is_available:
            return []

        # Tavily 使用 days 参数
        days_map = {
            SearchTimeRange.ONE_DAY: 1,
            SearchTimeRange.ONE_WEEK: 7,
            SearchTimeRange.ONE_MONTH: 30,
            SearchTimeRange.ONE_YEAR: 365,
            SearchTimeRange.NO_LIMIT: None,
        }

        params: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }

        if days_map[time_range] is not None:
            params["days"] = days_map[time_range]

        try:
            response = self._client.post(self.API_BASE_URL, json=params)
            response.raise_for_status()

            data = response.json()
            return self._parse_results(data)

        except httpx.HTTPStatusError as e:
            logger.warning(f"Tavily API error ({e.response.status_code}). Search returned empty results.")
            return []
        except Exception as e:
            logger.warning(f"Tavily search failed: {e}. Returning empty results.")
            return []

    def _parse_results(self, data: dict[str, Any]) -> list[SearchResult]:
        """解析 API 响应。

        Args:
            data: API 响应数据

        Returns:
            搜索结果列表
        """
        results = []

        for item in data.get("results", []):
            # 提取内容
            content = item.get("content", "")
            if not content:
                # 如果没有 content 字段，尝试使用其他字段
                content_parts = []
                for key in ["title", "snippet", "description"]:
                    if key in item:
                        content_parts.append(str(item[key]))
                content = " - ".join(content_parts)

            results.append(SearchResult(
                url=item.get("url", ""),
                title=item.get("title", ""),
                summary=content,
                site_name=self._extract_site_name(item.get("url", "")),
                published_date=item.get("published_date"),
                icon_url=item.get("image_url"),
                score=item.get("score", 0.0),
                provider=SearchProviderType.TAVILY,
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
            provider_type=SearchProviderType.TAVILY,
            is_available=self._is_available,
            rate_limit=None,  # Tavily 没有严格的速率限制
            daily_quota=1000,  # 免费额度约 1000 次/月
            supports_time_range=True,
            priority=100,
            description="Tavily - 高质量 AI 搜索 API",
        )

    def check_health(self) -> bool:
        """检查搜索源是否可用。

        Returns:
            True 表示可用，False 表示不可用
        """
        return self._is_available

    def __del__(self) -> None:
        """清理资源。"""
        if hasattr(self, "_client") and self._client is not None:
            self._client.close()
