"""格式化工具模块。

提供各种格式化功能。
"""

from typing import Any
from datetime import datetime


class Formatters:
    """格式化工具类。"""

    @staticmethod
    def format_duration(seconds: float) -> str:
        """格式化时长。

        Args:
            seconds: 秒数

        Returns:
            格式化的时长字符串
        """
        if seconds < 60:
            return f"{seconds:.1f} 秒"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f} 分钟"
        else:
            hours = seconds / 3600
            return f"{hours:.1f} 小时"

    @staticmethod
    def format_date(date_str: str | None) -> str:
        """格式化日期。

        Args:
            date_str: 日期字符串

        Returns:
            格式化的日期
        """
        if not date_str:
            return "未知"

        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%Y年%m月%d日")
        except Exception:
            return date_str

    @staticmethod
    def format_discovery_count(count: int) -> str:
        """格式化发现数量。

        Args:
            count: 数量

        Returns:
            格式化的数量字符串
        """
        if count == 0:
            return "无"
        elif count < 10:
            return f"{count} 条"
        elif count < 50:
            return f"{count} 条"
        else:
            return f"{count} 条+"

    @staticmethod
    def format_agent_type(agent_type: str) -> tuple[str, str]:
        """格式化 Agent 类型为名称和图标。

        Args:
            agent_type: Agent 类型

        Returns:
            (图标, 名称) 元组
        """
        type_map = {
            "scout": ("🔍", "侦察"),
            "experience": ("🎨", "体验"),
            "technical": ("🔬", "技术"),
            "market": ("📊", "市场"),
            "red_team": ("⚔️", "红队"),
            "blue_team": ("🛡️", "蓝队"),
            "elite": ("👑", "综合"),
        }

        return type_map.get(agent_type, ("📋", agent_type))

    @staticmethod
    def format_source_type(source: str) -> str:
        """格式化发现来源类型。

        Args:
            source: 来源类型

        Returns:
            格式化的来源字符串
        """
        from src.environment import DiscoverySource

        source_map = {
            DiscoverySource.WEBSITE: "官网",
            DiscoverySource.DOCUMENTATION: "文档",
            DiscoverySource.NEWS: "新闻",
            DiscoverySource.ANALYSIS: "分析",
            DiscoverySource.INFERENCE: "推断",
            DiscoverySource.DEBATE: "辩论",
        }

        if isinstance(source, str):
            source = DiscoverySource(source)

        return source_map.get(source, source.value)

    @staticmethod
    def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
        """截断文本。

        Args:
            text: 原文本
            max_length: 最大长度
            suffix: 截断后缀

        Returns:
            截断后的文本
        """
        if len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix

    @staticmethod
    def pluralize(count: int, singular: str, plural: str | None = None) -> str:
        """返回单数或复数形式。

        Args:
            count: 数量
            singular: 单数形式
            plural: 复数形式（默认为 singular + "s"）

        Returns:
            正确的形式
        """
        if count == 1:
            return singular
        return plural or (singular + "s")
