"""搜索工具基础模块。

定义搜索工具的抽象接口和数据结构。
"""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, Callable


class SearchProviderType(str, Enum):
    """搜索源类型枚举。

    定义所有支持的搜索源类型。
    """

    TAVILY = "tavily"
    DUCKDUCKGO = "duckduckgo"
    WIKIPEDIA = "wikipedia"
    SKILL_FALLBACK = "skill_fallback"
    MULTI = "multi"


class SearchTimeRange(str, Enum):
    """搜索时间范围。

    用于限制搜索结果的时间范围。
    """

    ONE_DAY = "oneDay"
    ONE_WEEK = "oneWeek"
    ONE_MONTH = "oneMonth"
    ONE_YEAR = "oneYear"
    NO_LIMIT = "noLimit"


@dataclass(frozen=True)
class SearchResult:
    """搜索结果数据类。

    表示单个搜索结果。
    """

    url: str
    title: str
    summary: str
    site_name: str | None = None
    published_date: str | None = None
    icon_url: str | None = None
    score: float = 0.0  # 相关性评分
    provider: SearchProviderType | None = None  # 结果来源

    def to_dict(self) -> dict:
        """转换为字典。"""
        return {
            "url": self.url,
            "title": self.title,
            "summary": self.summary,
            "site_name": self.site_name,
            "published_date": self.published_date,
            "icon_url": self.icon_url,
            "score": self.score,
            "provider": self.provider.value if self.provider else None,
        }


@dataclass(frozen=True)
class ProviderMetadata:
    """搜索源元数据。

    描述搜索源的能力和状态。
    """

    provider_type: SearchProviderType
    is_available: bool
    rate_limit: int | None  # 每分钟请求限制，None 表示无限制
    daily_quota: int | None  # 每日配额，None 表示无限制
    supports_time_range: bool
    priority: int = 0  # 优先级，数字越大优先级越高
    description: str = ""


@dataclass(frozen=True)
class SearchQuery:
    """搜索查询数据类。

    封装搜索请求的所有参数。
    """

    query: str
    time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR
    max_results: int = 10
    provider_types: list[SearchProviderType] | None = None  # 指定使用的搜索源


class SearchTool(Protocol):
    """搜索工具接口。

    所有搜索工具实现都需要遵循此接口。
    """

    @abstractmethod
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
        ...

    @property
    @abstractmethod
    def metadata(self) -> ProviderMetadata:
        """获取搜索源元数据。"""
        ...

    @abstractmethod
    def check_health(self) -> bool:
        """检查搜索源是否可用。

        Returns:
            True 表示可用，False 表示不可用
        """
        ...
