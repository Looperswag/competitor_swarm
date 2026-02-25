"""GitHub 仓库搜索源实现。

使用 GitHub API 搜索仓库，获取 stars、forks、issues 等数据。
"""

import logging
import os
from typing import Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from src.search.base import (
    ProviderMetadata,
    SearchProviderType,
    SearchResult,
    SearchTimeRange,
    SearchTool,
)


class GitHubSearchTool(SearchTool):
    """GitHub 仓库搜索工具。

    使用 GitHub API 搜索仓库，获取项目统计信息。
    需要 GITHUB_TOKEN 环境变量（可选，有 token 可提高速率限制）。
    """

    def __init__(self, api_token: str | None = None) -> None:
        """初始化 GitHub 搜索工具。

        Args:
            api_token: GitHub API Token，未提供时从环境变量读取
        """
        self._api_token = api_token or os.getenv("GITHUB_TOKEN")
        self._base_url = "https://api.github.com"
        self._is_available = True
        self._check_availability()

    def _check_availability(self) -> None:
        """检查 GitHub API 是否可用。"""
        import urllib.request
        import urllib.error

        try:
            headers = self._build_headers()
            req = urllib.request.Request(f"{self._base_url}/rate_limit", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    logger.info("GitHub API is available.")
                else:
                    self._is_available = False
        except urllib.error.HTTPError as e:
            if e.code == 401:
                logger.warning("GitHub API token is invalid.")
                # 没有 token 也可以使用，只是速率限制更低
                self._is_available = True
            else:
                logger.warning(f"GitHub API check failed: {e}")
                self._is_available = True  # 仍然尝试使用
        except Exception as e:
            logger.warning(f"GitHub API check failed: {e}")
            self._is_available = True  # 仍然尝试使用

    def _build_headers(self) -> dict[str, str]:
        """构建请求头。"""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "CompetitorSwarm/1.0",
        }
        if self._api_token:
            headers["Authorization"] = f"token {self._api_token}"
        return headers

    def search(
        self,
        query: str,
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """搜索 GitHub 仓库。

        Args:
            query: 搜索查询
            time_range: 时间范围
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        if not self._is_available:
            return []

        import urllib.request
        import urllib.parse
        import urllib.error
        import json

        # 构建搜索查询
        search_query = query

        # 添加时间范围过滤
        if time_range != SearchTimeRange.NO_LIMIT:
            created_after = self._get_date_filter(time_range)
            if created_after:
                search_query = f"{query} created:>{created_after}"

        # URL 编码
        encoded_query = urllib.parse.quote(search_query)
        url = f"{self._base_url}/search/repositories?q={encoded_query}&per_page={min(max_results, 100)}&sort=stars&order=desc"

        try:
            headers = self._build_headers()
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
                return self._parse_results(data.get("items", []))

        except urllib.error.HTTPError as e:
            if e.code == 403:
                logger.warning("GitHub API rate limit exceeded.")
            else:
                logger.warning(f"GitHub search failed: HTTP {e.code}")
            return []
        except Exception as e:
            logger.warning(f"GitHub search failed: {e}")
            return []

    def _get_date_filter(self, time_range: SearchTimeRange) -> str | None:
        """获取时间过滤日期。

        Args:
            time_range: 时间范围

        Returns:
            ISO 格式日期字符串
        """
        now = datetime.now()
        delta_map = {
            SearchTimeRange.ONE_DAY: timedelta(days=1),
            SearchTimeRange.ONE_WEEK: timedelta(weeks=1),
            SearchTimeRange.ONE_MONTH: timedelta(days=30),
            SearchTimeRange.ONE_YEAR: timedelta(days=365),
        }

        delta = delta_map.get(time_range)
        if delta:
            date = now - delta
            return date.strftime("%Y-%m-%d")
        return None

    def _parse_results(self, items: list[dict[str, Any]]) -> list[SearchResult]:
        """解析 GitHub 搜索结果。

        Args:
            items: GitHub API 返回的仓库列表

        Returns:
            搜索结果列表
        """
        results = []

        for item in items:
            # 构建摘要信息
            summary = self._build_summary(item)

            results.append(SearchResult(
                url=item.get("html_url", ""),
                title=item.get("full_name", item.get("name", "")),
                summary=summary,
                site_name="github.com",
                published_date=item.get("created_at"),
                icon_url=item.get("owner", {}).get("avatar_url"),
                score=self._calculate_score(item),
                provider=SearchProviderType.GITHUB,
            ))

        return results

    def _build_summary(self, item: dict[str, Any]) -> str:
        """构建仓库摘要。

        Args:
            item: 仓库信息

        Returns:
            摘要文本
        """
        parts = []

        # 描述
        description = item.get("description", "")
        if description:
            parts.append(description[:200])

        # 统计信息
        stats = []
        stars = item.get("stargazers_count", 0)
        if stars:
            stats.append(f"⭐ {self._format_number(stars)}")

        forks = item.get("forks_count", 0)
        if forks:
            stats.append(f"🍴 {self._format_number(forks)}")

        issues = item.get("open_issues_count", 0)
        if issues:
            stats.append(f"❗ {self._format_number(issues)}")

        language = item.get("language")
        if language:
            stats.append(f"🔤 {language}")

        if stats:
            parts.append(" | ".join(stats))

        return "\n".join(parts)

    @staticmethod
    def _format_number(num: int) -> str:
        """格式化数字。

        Args:
            num: 数字

        Returns:
            格式化后的字符串
        """
        if num >= 1_000_000:
            return f"{num / 1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num / 1_000:.1f}K"
        return str(num)

    @staticmethod
    def _calculate_score(item: dict[str, Any]) -> float:
        """计算相关性评分。

        基于 stars、forks、最近更新等因素。

        Args:
            item: 仓库信息

        Returns:
            评分 (0.0-1.0)
        """
        stars = item.get("stargazers_count", 0)
        forks = item.get("forks_count", 0)

        # 对数缩放 stars
        import math
        star_score = min(1.0, math.log10(max(1, stars)) / 5)  # 100k stars = 1.0

        # Fork 权重
        fork_score = min(1.0, math.log10(max(1, forks)) / 4)  # 10k forks = 1.0

        # 综合评分
        score = 0.6 * star_score + 0.4 * fork_score

        return round(score, 2)

    def get_repo_stats(self, owner: str, repo: str) -> dict[str, Any] | None:
        """获取仓库详细统计信息。

        Args:
            owner: 仓库所有者
            repo: 仓库名称

        Returns:
            仓库统计信息
        """
        import urllib.request
        import urllib.error
        import json

        url = f"{self._base_url}/repos/{owner}/{repo}"

        try:
            headers = self._build_headers()
            req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
                return {
                    "stars": data.get("stargazers_count", 0),
                    "forks": data.get("forks_count", 0),
                    "open_issues": data.get("open_issues_count", 0),
                    "watchers": data.get("watchers_count", 0),
                    "language": data.get("language"),
                    "license": data.get("license", {}).get("spdx_id") if data.get("license") else None,
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "pushed_at": data.get("pushed_at"),
                    "size": data.get("size", 0),  # KB
                    "topics": data.get("topics", []),
                    "homepage": data.get("homepage"),
                    "description": data.get("description"),
                }

        except urllib.error.HTTPError as e:
            logger.warning(f"Failed to get repo stats: HTTP {e.code}")
            return None
        except Exception as e:
            logger.warning(f"Failed to get repo stats: {e}")
            return None

    @property
    def metadata(self) -> ProviderMetadata:
        """获取搜索源元数据。"""
        # GitHub API 速率限制：认证 5000/小时，未认证 60/小时
        rate_limit = 5000 if self._api_token else 60

        return ProviderMetadata(
            provider_type=SearchProviderType.GITHUB,
            is_available=self._is_available,
            rate_limit=rate_limit,  # 每小时
            daily_quota=None,
            supports_time_range=True,
            priority=50,
            description="GitHub - 代码仓库搜索",
        )

    def check_health(self) -> bool:
        """检查搜索源是否可用。

        Returns:
            True 表示可用，False 表示不可用
        """
        if not self._is_available:
            return False

        import urllib.request
        import urllib.error

        try:
            headers = self._build_headers()
            req = urllib.request.Request(
                f"{self._base_url}/search/repositories?q=test&per_page=1",
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception:
            return False
