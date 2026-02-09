"""Skill 降级搜索源实现。

当 Tavily API 不可用时，使用 Claude Code 的 search skill 进行在线搜索。
"""

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

from src.search.base import (
    ProviderMetadata,
    SearchProviderType,
    SearchResult,
    SearchTimeRange,
    SearchTool,
)


class SkillFallbackSearchTool(SearchTool):
    """Skill 降级搜索工具。

    当主搜索工具（如 Tavily）失败时，使用 Claude Code 的 search skill 作为备选方案。
    """

    def __init__(self, enable_fallback: bool = True) -> None:
        """初始化 Skill 降级搜索工具。

        Args:
            enable_fallback: 是否启用降级机制
        """
        self._enable_fallback = enable_fallback
        self._skill_available = False
        self._check_skill_availability()

    def _check_skill_availability(self) -> None:
        """检查 search skill 是否可用。"""
        try:
            # 测试 search skill 是否可用
            result = subprocess.run(
                ["claude", "skill", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self._skill_available = "search" in result.stdout
        except Exception:
            self._skill_available = False

        if not self._skill_available:
            logger.warning("Claude Code 'search' skill not available. Fallback search disabled.")

    def search(
        self,
        query: str,
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """使用 search skill 执行搜索。

        Args:
            query: 搜索查询
            time_range: 时间范围（注意：search skill 可能不支持此参数）
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        if not self._enable_fallback or not self._skill_available:
            return []

        try:
            # 调用 Claude Code 的 search skill
            result = subprocess.run(
                ["claude", "skill", "search", "--query", query, "--max-results", str(max_results)],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                logger.warning(f"Search skill failed: {result.stderr}")
                return []

            return self._parse_skill_output(result.stdout)

        except subprocess.TimeoutExpired:
            logger.warning("Search skill timed out.")
            return []
        except Exception as e:
            logger.warning(f"Search skill error: {e}")
            return []

    def _parse_skill_output(self, output: str) -> list[SearchResult]:
        """解析 search skill 的输出。

        Args:
            output: skill 输出文本

        Returns:
            搜索结果列表
        """
        results = []

        # search skill 的输出格式通常是 JSON 或结构化文本
        # 尝试解析 JSON
        try:
            import json

            data = json.loads(output)
            if isinstance(data, dict) and "results" in data:
                for item in data["results"]:
                    results.append(SearchResult(
                        url=item.get("url", ""),
                        title=item.get("title", ""),
                        summary=item.get("summary", item.get("content", "")),
                        site_name=self._extract_site_name(item.get("url", "")),
                        published_date=None,
                        score=item.get("score", 0.5),
                        provider=SearchProviderType.SKILL_FALLBACK,
                    ))
                return results
        except Exception:
            pass

        # 如果不是 JSON，尝试解析结构化文本
        lines = output.split("\n")
        current_result: dict[str, Any] = {}

        for line in lines:
            line = line.strip()
            if not line:
                if current_result:
                    self._add_result_from_dict(current_result, results)
                    current_result = {}
                continue

            # 解析常见格式
            if line.startswith("Title:"):
                current_result["title"] = line[6:].strip()
            elif line.startswith("URL:"):
                current_result["url"] = line[4:].strip()
            elif line.startswith("Summary:"):
                current_result["summary"] = line[8:].strip()
            elif line.startswith("- "):
                # 可能是结果项
                if current_result:
                    self._add_result_from_dict(current_result, results)
                    current_result = {}
                # 尝试从列表项提取信息
                current_result["title"] = line[2:].strip()

        # 添加最后一个结果
        if current_result:
            self._add_result_from_dict(current_result, results)

        return results

    def _add_result_from_dict(self, data: dict[str, Any], results: list[SearchResult]) -> None:
        """从字典添加结果到列表。

        Args:
            data: 结果数据字典
            results: 结果列表
        """
        if "title" in data or "url" in data:
            results.append(SearchResult(
                url=data.get("url", ""),
                title=data.get("title", data.get("url", "")),
                summary=data.get("summary", ""),
                site_name=self._extract_site_name(data.get("url", "")),
                published_date=None,
                score=0.5,
                provider=SearchProviderType.SKILL_FALLBACK,
            ))

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
            provider_type=SearchProviderType.SKILL_FALLBACK,
            is_available=self._skill_available and self._enable_fallback,
            rate_limit=None,
            daily_quota=0,  # 无限制
            supports_time_range=False,
            priority=1,  # 最低优先级
            description="Claude Code Search Skill - 降级搜索",
        )

    def check_health(self) -> bool:
        """检查搜索源是否可用。

        Returns:
            True 表示可用，False 表示不可用
        """
        return self._skill_available and self._enable_fallback
