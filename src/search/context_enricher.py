"""上下文增强器模块。

为 Elite Agent 收集外部专家观点和分析。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

from src.search.base import SearchTool, SearchTimeRange, SearchResult


@dataclass
class ExternalInsight:
    """外部洞察数据类。

    表示从外部来源收集的专家观点或分析。
    """

    url: str
    title: str
    summary: str
    source_type: str  # expert_blog, tech_paper, news, review, analysis
    site_name: str | None = None
    published_date: str | None = None
    relevance_score: float = 0.0
    quoted_content: list[str] | None = None

    def to_dict(self) -> dict:
        """转换为字典。"""
        return {
            "url": self.url,
            "title": self.title,
            "summary": self.summary,
            "source_type": self.source_type,
            "site_name": self.site_name,
            "published_date": self.published_date,
            "relevance_score": self.relevance_score,
            "quoted_content": self.quoted_content or [],
        }


class ContextEnricher:
    """上下文增强器。

    为 Elite Agent 收集外部专家观点和分析。
    """

    def __init__(self, search_tool: SearchTool) -> None:
        """初始化上下文增强器。

        Args:
            search_tool: 搜索工具实例
        """
        self._search = search_tool

    def enrich_for_elite(
        self,
        target: str,
        category: str | None = None,
        max_results_per_query: int = 5,
    ) -> list[ExternalInsight]:
        """为 Elite Agent 收集外部上下文。

        Args:
            target: 目标产品/公司名称
            category: 产品类别（用于搜索行业趋势）
            max_results_per_query: 每个查询的最大结果数

        Returns:
            外部洞察列表
        """
        # 构建搜索查询
        queries = self._build_search_queries(target, category)

        insights = []

        for query_type, query in queries.items():
            try:
                results = self._search.search(
                    query=query,
                    time_range=SearchTimeRange.ONE_YEAR,
                    max_results=max_results_per_query,
                )

                for result in results:
                    insights.append(ExternalInsight(
                        url=result.url,
                        title=result.title,
                        summary=result.summary,
                        source_type=self._classify_source(result, query_type),
                        site_name=result.site_name,
                        published_date=result.published_date,
                        relevance_score=result.score,
                    ))

            except Exception as e:
                # 单个搜索失败不应影响整体
                logger.warning(f"Search failed for '{query}': {e}")
                continue

        # 去重并排序
        unique_insights = self._deduplicate(insights)
        sorted_insights = sorted(
            unique_insights,
            key=lambda x: x.relevance_score,
            reverse=True,
        )

        return sorted_insights[:30]  # 最多返回 30 条

    def _build_search_queries(self, target: str, category: str | None) -> dict[str, str]:
        """构建搜索查询。

        Args:
            target: 目标产品/公司名称
            category: 产品类别

        Returns:
            查询类型到查询字符串的映射
        """
        queries = {
            # 专家观点
            "expert": f'"{target}" 专家分析 深度评测',
            "industry": f'"{target}" 行业报告 市场分析',

            # 技术视角
            "technical": f'"{target}" 技术架构 开发者',

            # 商业视角
            "business": f'"{target}" 商业模式 盈利',

            # 用户反馈
            "review": f'"{target}" 用户评价 体验分析',
        }

        if category:
            queries["trend"] = f"{category} 发展趋势 行业分析"

        return queries

    def _classify_source(self, result: SearchResult, query_type: str) -> str:
        """分类来源类型。

        Args:
            result: 搜索结果
            query_type: 查询类型

        Returns:
            来源类型
        """
        url = result.url.lower()

        # 根据域名判断来源类型
        if any(domain in url for domain in ["medium.com", "blog", "substack"]):
            return "expert_blog"
        elif any(domain in url for domain in ["arxiv.org", "acm.org", "ieee.org"]):
            return "tech_paper"
        elif any(domain in url for domain in ["news", "techcrunch", "36kr", "ifanr"]):
            return "news"
        elif any(domain in url for domain in ["youtube.com", "bilibili"]):
            return "video"
        else:
            # 根据查询类型推断
            type_map = {
                "expert": "analysis",
                "industry": "analysis",
                "technical": "analysis",
                "business": "analysis",
                "review": "review",
                "trend": "analysis",
            }
            return type_map.get(query_type, "article")

    def _deduplicate(self, insights: list[ExternalInsight]) -> list[ExternalInsight]:
        """去重。

        Args:
            insights: 外部洞察列表

        Returns:
            去重后的列表
        """
        seen_urls = set()
        unique = []

        for insight in insights:
            if insight.url not in seen_urls:
                seen_urls.add(insight.url)
                unique.append(insight)

        return unique
