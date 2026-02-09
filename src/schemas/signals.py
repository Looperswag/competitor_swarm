"""Signal 数据模式模块。

定义用于 Agent Swarm 框架的 Signal 数据结构和相关枚举。
Signal 是 Agent 之间通信的基本单元，替代原有的 Discovery 结构。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class SignalType(str, Enum):
    """信号类型枚举。

    定义不同类型的信号，用于分类和过滤。
    """

    INSIGHT = "insight"  # 洞察性发现
    THREAT = "threat"  # 威胁性发现
    OPPORTUNITY = "opportunity"  # 机会性发现
    RISK = "risk"  # 风险性发现
    NEED = "need"  # 需求性发现


class Dimension(str, Enum):
    """分析维度枚举。

    定义不同的分析维度，对应不同的 Agent 专长。
    """

    PRODUCT = "product"  # 产品维度
    TECHNICAL = "technical"  # 技术维度
    MARKET = "market"  # 市场维度
    UX = "ux"  # 用户体验维度
    BUSINESS = "business"  # 商业维度
    TEAM = "team"  # 团队维度


class Sentiment(str, Enum):
    """情感倾向枚举。

    定义信号的情感倾向。
    """

    POSITIVE = "positive"  # 正面
    NEUTRAL = "neutral"  # 中性
    NEGATIVE = "negative"  # 负面


class Actionability(str, Enum):
    """可行动性枚举。

    定义信号的可行动程度。
    """

    IMMEDIATE = "immediate"  # 立即行动
    SHORT_TERM = "short_term"  # 短期行动
    LONG_TERM = "long_term"  # 长期行动
    INFORMATIONAL = "informational"  # 信息性，无需行动


@dataclass(frozen=True)
class Signal:
    """信号数据类。

    表示 Agent 产生的一个结构化发现或信号。
    Signal 是 Stigmergy 通信机制中的基本单元。

    Attributes:
        id: 信号唯一标识符
        signal_type: 信号类型
        dimension: 分析维度
        evidence: 支持证据
        confidence: 置信度 (0.0-1.0)
        strength: 信号强度 (0.0-1.0)
        sentiment: 情感倾向
        tags: 分类标签
        source: 数据来源
        timestamp: ISO 8601 时间戳
        references: 相关信号 ID 列表
        author_agent: 创建信号的 Agent
        verified: 交叉验证状态
        debate_points: 辩论中提出的观点
        actionability: 可行动性
        metadata: 额外元数据
    """

    id: str
    signal_type: SignalType
    dimension: Dimension
    evidence: str
    confidence: float
    strength: float
    sentiment: Sentiment
    tags: list[str] = field(default_factory=list)
    source: str = ""
    timestamp: str = ""
    references: list[str] = field(default_factory=list)
    author_agent: str = ""
    verified: bool = False
    debate_points: list[str] = field(default_factory=list)
    actionability: Actionability = Actionability.INFORMATIONAL
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """初始化后验证。

        确保数据有效性。
        """
        # 验证置信度和强度范围
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be between 0.0 and 1.0, got {self.strength}")

        # 如果未提供时间戳，使用当前时间
        if not self.timestamp:
            object.__setattr__(self, "timestamp", datetime.now().isoformat())

        # 如果未提供 ID，生成 UUID
        if not self.id:
            object.__setattr__(self, "id", str(uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。

        Returns:
            字典表示（兼容 Reporter 期望的 content 字段）
        """
        return {
            "id": self.id,
            "signal_type": self.signal_type.value,
            "dimension": self.dimension.value,
            "evidence": self.evidence,
            "content": self.evidence,  # 添加 content 字段以兼容 Reporter
            "confidence": self.confidence,
            "strength": self.strength,
            "sentiment": self.sentiment.value,
            "tags": self.tags,
            "source": self.source,
            "timestamp": self.timestamp,
            "references": self.references,
            "author_agent": self.author_agent,
            "verified": self.verified,
            "debate_points": self.debate_points,
            "actionability": self.actionability.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Signal":
        """从字典创建 Signal。

        Args:
            data: 字典数据

        Returns:
            Signal 对象
        """
        return cls(
            id=data.get("id", ""),
            signal_type=SignalType(data.get("signal_type", SignalType.INSIGHT)),
            dimension=Dimension(data.get("dimension", Dimension.PRODUCT)),
            evidence=data.get("evidence", ""),
            confidence=data.get("confidence", 0.5),
            strength=data.get("strength", 0.5),
            sentiment=Sentiment(data.get("sentiment", Sentiment.NEUTRAL)),
            tags=data.get("tags", []),
            source=data.get("source", ""),
            timestamp=data.get("timestamp", ""),
            references=data.get("references", []),
            author_agent=data.get("author_agent", ""),
            verified=data.get("verified", False),
            debate_points=data.get("debate_points", []),
            actionability=Actionability(data.get("actionability", Actionability.INFORMATIONAL)),
            metadata=data.get("metadata", {}),
        )

    def is_fresh(self, max_age_hours: int = 24) -> bool:
        """检查信号是否新鲜。

        Args:
            max_age_hours: 最大允许年龄（小时）

        Returns:
            是否新鲜
        """
        try:
            signal_time = datetime.fromisoformat(self.timestamp)
            age_hours = (datetime.now() - signal_time).total_seconds() / 3600
            return age_hours <= max_age_hours
        except (ValueError, TypeError):
            return False

    def age_hours(self) -> float:
        """获取信号年龄（小时）。

        Returns:
            年龄（小时）
        """
        try:
            signal_time = datetime.fromisoformat(self.timestamp)
            return (datetime.now() - signal_time).total_seconds() / 3600
        except (ValueError, TypeError):
            return float("inf")

    def with_updated_strength(
        self,
        new_strength: float,
        verifier: str = "",
        debate_point: str = "",
    ) -> "Signal":
        """创建更新强度后的新 Signal。

        Args:
            new_strength: 新的强度值
            verifier: 验证者
            debate_point: 辩论观点

        Returns:
            新的 Signal 对象
        """
        debate_points = list(self.debate_points)
        if debate_point:
            debate_points.append(debate_point)

        # 创建新对象（因为 dataclass 是 frozen 的）
        return Signal(
            id=self.id,
            signal_type=self.signal_type,
            dimension=self.dimension,
            evidence=self.evidence,
            confidence=self.confidence,
            strength=max(0.0, min(1.0, new_strength)),
            sentiment=self.sentiment,
            tags=list(self.tags),
            source=self.source,
            timestamp=self.timestamp,
            references=list(self.references),
            author_agent=self.author_agent,
            verified=verifier != "" or self.verified,
            debate_points=debate_points,
            actionability=self.actionability,
            metadata={**self.metadata, "verified_by": verifier},
        )

    def __repr__(self) -> str:
        """字符串表示。

        Returns:
            字符串表示
        """
        return (
            f"Signal(id={self.id[:8]}..., "
            f"type={self.signal_type.value}, "
            f"dimension={self.dimension.value}, "
            f"confidence={self.confidence:.2f}, "
            f"strength={self.strength:.2f})"
        )


@dataclass
class SignalFilter:
    """信号过滤器。

    用于筛选和过滤信号。
    """

    signal_types: set[SignalType] | None = None
    dimensions: set[Dimension] | None = None
    sentiments: set[Sentiment] | None = None
    min_confidence: float = 0.0
    min_strength: float = 0.0
    verified_only: bool = False
    max_age_hours: int | None = None
    author_agents: set[str] | None = None
    tags: set[str] | None = None
    actionabilities: set[Actionability] | None = None

    def matches(self, signal: Signal) -> bool:
        """检查信号是否匹配过滤器。

        Args:
            signal: 信号对象

        Returns:
            是否匹配
        """
        # 检查信号类型
        if self.signal_types and signal.signal_type not in self.signal_types:
            return False

        # 检查维度
        if self.dimensions and signal.dimension not in self.dimensions:
            return False

        # 检查情感
        if self.sentiments and signal.sentiment not in self.sentiments:
            return False

        # 检查置信度
        if signal.confidence < self.min_confidence:
            return False

        # 检查强度
        if signal.strength < self.min_strength:
            return False

        # 检查验证状态
        if self.verified_only and not signal.verified:
            return False

        # 检查年龄
        if self.max_age_hours and not signal.is_fresh(self.max_age_hours):
            return False

        # 检查作者
        if self.author_agents and signal.author_agent not in self.author_agents:
            return False

        # 检查标签
        if self.tags:
            if not any(tag in signal.tags for tag in self.tags):
                return False

        # 检查可行动性
        if self.actionabilities and signal.actionability not in self.actionabilities:
            return False

        return True

    def __repr__(self) -> str:
        """字符串表示。

        Returns:
            字符串表示
        """
        parts = []
        if self.signal_types:
            parts.append(f"types={self.signal_types}")
        if self.dimensions:
            parts.append(f"dimensions={self.dimensions}")
        if self.min_confidence > 0:
            parts.append(f"min_conf={self.min_confidence}")
        if self.min_strength > 0:
            parts.append(f"min_str={self.min_strength}")
        if self.verified_only:
            parts.append("verified=True")
        if self.max_age_hours:
            parts.append(f"max_age={self.max_age_hours}h")

        return f"SignalFilter({', '.join(parts) if parts else 'all'})"
