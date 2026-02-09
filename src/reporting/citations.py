"""引用管理模块。

跟踪和管理报告中引用的所有外部来源。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Citation:
    """引用数据类。

    表示报告中的一个外部来源引用。
    """

    id: int
    title: str
    url: str
    source_type: str  # official, news, blog, paper, review, analysis
    site_name: str
    accessed_at: str
    relevance: str  # 用于哪个分析维度
    quoted_content: list[str] = field(default_factory=list)
    author: str | None = None
    published_date: str | None = None

    def to_markdown(self) -> str:
        """转换为 Markdown 格式。

        Returns:
            Markdown 格式的引用字符串
        """
        lines = [
            f"[{self.id}] {self.title}",
            f"   - 来源: {self.site_name}",
            f"   - 类型: {self._format_source_type()}",
            f"   - 链接: {self.url}",
        ]
        if self.author:
            lines.append(f"   - 作者: {self.author}")
        if self.published_date:
            lines.append(f"   - 发布日期: {self.published_date}")
        return "\n".join(lines)

    def _format_source_type(self) -> str:
        """格式化来源类型为中文。"""
        type_map = {
            "official": "官方来源",
            "news": "新闻报道",
            "blog": "博客文章",
            "paper": "技术论文",
            "review": "用户评测",
            "analysis": "行业分析",
            "video": "视频内容",
            "article": "文章",
        }
        return type_map.get(self.source_type, self.source_type)


class CitationManager:
    """引用管理器。

    跟踪和管理报告中的所有外部来源引用。
    """

    def __init__(self) -> None:
        """初始化引用管理器。"""
        self._citations: list[Citation] = []
        self._next_id = 1
        self._citations_by_relevance: dict[str, list[int]] = {}

    def add_citation(
        self,
        title: str,
        url: str,
        source_type: str,
        site_name: str,
        relevance: str,
        quoted_content: list[str] | None = None,
        author: str | None = None,
        published_date: str | None = None,
    ) -> int:
        """添加引用，返回引用编号。

        Args:
            title: 标题
            url: 链接
            source_type: 来源类型
            site_name: 站点名称
            relevance: 相关分析维度
            quoted_content: 被引用的内容片段
            author: 作者
            published_date: 发布日期

        Returns:
            引用编号
        """
        citation = Citation(
            id=self._next_id,
            title=title,
            url=url,
            source_type=source_type,
            site_name=site_name,
            accessed_at=datetime.now().strftime("%Y-%m-%d"),
            relevance=relevance,
            quoted_content=quoted_content or [],
            author=author,
            published_date=published_date,
        )

        self._citations.append(citation)

        # 按相关性索引
        if relevance not in self._citations_by_relevance:
            self._citations_by_relevance[relevance] = []
        self._citations_by_relevance[relevance].append(citation.id)

        self._next_id += 1
        return citation.id

    def get_citations_by_relevance(self, relevance: str) -> list[Citation]:
        """获取特定维度的引用。

        Args:
            relevance: 分析维度

        Returns:
            引用列表
        """
        ids = self._citations_by_relevance.get(relevance, [])
        return [c for c in self._citations if c.id in ids]

    def format_appendix(self) -> str:
        """格式化附录内容。

        Returns:
            Markdown 格式的附录
        """
        lines = [
            "## 附录：来源索引",
            "",
            "| 编号 | 类型 | 标题 | 来源 | 链接 | 访问日期 |",
            "|------|------|------|------|------|----------|",
        ]

        for c in self._citations:
            # 截断过长的标题
            title_short = c.title[:40] + "..." if len(c.title) > 40 else c.title
            lines.append(
                f"| [{c.id}] | {c._format_source_type()} | {title_short} | "
                f"{c.site_name[:20]} | [链接]({c.url}) | {c.accessed_at} |"
            )

        return "\n".join(lines)

    def count(self) -> int:
        """获取引用总数。

        Returns:
            引用数量
        """
        return len(self._citations)

    def clear(self) -> None:
        """清空所有引用。"""
        self._citations.clear()
        self._next_id = 1
        self._citations_by_relevance.clear()
