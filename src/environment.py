"""共享环境模块。

实现 Stigmergy 通信机制，允许 Agent 之间通过共享环境间接通信。

支持两种数据结构：
- Discovery: 旧版本发现格式（向后兼容）
- Signal: 新版本信号格式（推荐使用）
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.config import get_config

# 导入新的 Signal 结构
try:
    from src.schemas.signals import Signal, SignalFilter, Dimension, SignalType
    SIGNALS_AVAILABLE = True
except ImportError:
    SIGNALS_AVAILABLE = False


class DiscoverySource(str, Enum):
    """发现来源类型。"""

    WEBSITE = "website"
    DOCUMENTATION = "documentation"
    NEWS = "news"
    ANALYSIS = "analysis"
    INFERENCE = "inference"
    DEBATE = "debate"


@dataclass(frozen=True)
class Discovery:
    """发现数据类。

    表示一个 Agent 发现的信息（旧版本，向后兼容）。
    新代码应使用 Signal 代替。
    """

    id: str
    agent_type: str
    content: str
    source: DiscoverySource
    quality_score: float  # 0.0 - 1.0
    timestamp: str
    references: list[str] = field(default_factory=list)  # 引用的其他发现 ID
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "id": self.id,
            "agent_type": self.agent_type,
            "content": self.content,
            "source": self.source.value,
            "quality_score": self.quality_score,
            "timestamp": self.timestamp,
            "references": self.references,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Discovery":
        """从字典创建。"""
        return cls(
            id=data["id"],
            agent_type=data["agent_type"],
            content=data["content"],
            source=DiscoverySource(data["source"]),
            quality_score=data["quality_score"],
            timestamp=data["timestamp"],
            references=data.get("references", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class VirtualPheromone:
    """虚拟信息素。

    追踪发现/信号的"吸引力"，即被其他 Agent 引用的程度。
    """

    item_id: str
    reference_count: int = 0
    last_accessed: str = ""

    def update_access(self) -> None:
        """更新访问时间。"""
        self.last_accessed = datetime.now().isoformat()


class StigmergyEnvironment:
    """Stigmergy 共享环境。

    实现 Agent 之间的间接通信：
    - Agent 可以添加发现/信号到环境
    - Agent 可以检索相关发现/信号
    - 高质量发现/信号会被更多引用（虚拟信息素）

    支持两种数据结构：
    - Discovery: 旧版本格式（向后兼容）
    - Signal: 新版本格式（推荐使用）
    """

    def __init__(self, cache_path: str | None = None) -> None:
        """初始化环境。

        Args:
            cache_path: 缓存目录路径
        """
        config = get_config()
        self._cache_path = Path(cache_path or config.cache.path)
        self._cache_path.mkdir(parents=True, exist_ok=True)

        # 旧版本 Discovery 存储
        self._discoveries: dict[str, Discovery] = {}
        self._pheromones: dict[str, VirtualPheromone] = {}

        # 新版本 Signal 存储
        self._signals: dict[str, Any] = {} if not SIGNALS_AVAILABLE else {}
        self._signal_pheromones: dict[str, VirtualPheromone] = {}

    # ========== Discovery 方法（向后兼容） ==========

    def add_discovery(
        self,
        agent_type: str,
        content: str,
        source: DiscoverySource,
        quality_score: float = 0.5,
        references: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Discovery:
        """添加发现到环境（旧版本，向后兼容）。

        Args:
            agent_type: Agent 类型
            content: 发现内容
            source: 发现来源
            quality_score: 质量评分 (0.0 - 1.0)
            references: 引用的其他发现 ID
            metadata: 额外元数据

        Returns:
            创建的发现对象
        """
        discovery_id = str(uuid.uuid4())

        discovery = Discovery(
            id=discovery_id,
            agent_type=agent_type,
            content=content,
            source=source,
            quality_score=max(0.0, min(1.0, quality_score)),
            timestamp=datetime.now().isoformat(),
            references=references or [],
            metadata=metadata or {},
        )

        self._discoveries[discovery_id] = discovery
        self._pheromones[discovery_id] = VirtualPheromone(discovery_id)

        # 更新被引用发现的计数
        for ref_id in discovery.references:
            if ref_id in self._pheromones:
                self._pheromones[ref_id].reference_count += 1

        return discovery

    def get_discovery(self, discovery_id: str) -> Discovery | None:
        """获取特定发现（旧版本）。

        Args:
            discovery_id: 发现 ID

        Returns:
            发现对象，如果不存在返回 None
        """
        discovery = self._discoveries.get(discovery_id)
        if discovery and discovery_id in self._pheromones:
            self._pheromones[discovery_id].update_access()
        return discovery

    def get_discoveries_by_agent(self, agent_type: str) -> list[Discovery]:
        """获取特定 Agent 类型的所有发现（旧版本）。

        Args:
            agent_type: Agent 类型

        Returns:
            发现列表
        """
        return [
            d for d in self._discoveries.values()
            if d.agent_type == agent_type
        ]

    def get_relevant_discoveries(
        self,
        agent_type: str | None = None,
        limit: int = 10,
        min_quality: float = 0.0,
    ) -> list[Discovery]:
        """获取相关发现（旧版本）。

        按虚拟信息素强度排序（引用计数 × 质量评分）。

        Args:
            agent_type: 筛选特定 Agent 类型，None 表示全部
            limit: 最大返回数量
            min_quality: 最低质量评分

        Returns:
            相关发现列表
        """
        discoveries = list(self._discoveries.values())

        # 筛选
        if agent_type:
            discoveries = [d for d in discoveries if d.agent_type == agent_type]
        discoveries = [d for d in discoveries if d.quality_score >= min_quality]

        # 按虚拟信息素排序
        def score(d: Discovery) -> float:
            pheromone = self._pheromones.get(d.id)
            ref_count = pheromone.reference_count if pheromone else 0
            return ref_count * d.quality_score

        discoveries.sort(key=score, reverse=True)

        return discoveries[:limit]

    def get_hot_discoveries(self, limit: int = 5) -> list[Discovery]:
        """获取热门发现（高引用计数）（旧版本）。

        Args:
            limit: 最大返回数量

        Returns:
            热门发现列表
        """
        scored = [
            (d, self._pheromones[d.id].reference_count)
            for d in self._discoveries.values()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [d for d, _ in scored[:limit]]

    # ========== Signal 方法（新版本） ==========

    def add_signal(
        self,
        signal: Any,
    ) -> Any:
        """添加信号到环境（新版本）。

        Args:
            signal: Signal 对象

        Returns:
            添加的信号对象
        """
        if not SIGNALS_AVAILABLE:
            raise ImportError("Signal schema not available. Check src.schemas.signals import.")

        self._signals[signal.id] = signal
        self._signal_pheromones[signal.id] = VirtualPheromone(signal.id)

        # 更新被引用信号的计数
        for ref_id in signal.references:
            if ref_id in self._signal_pheromones:
                self._signal_pheromones[ref_id].reference_count += 1

        return signal

    def get_signal(self, signal_id: str) -> Any | None:
        """获取特定信号（新版本）。

        Args:
            signal_id: 信号 ID

        Returns:
            信号对象，如果不存在返回 None
        """
        signal = self._signals.get(signal_id)
        if signal and signal_id in self._signal_pheromones:
            self._signal_pheromones[signal_id].update_access()
        return signal

    def get_signals_by_filter(
        self,
        filter_obj: Any | None = None,
        limit: int = 50,
    ) -> list[Any]:
        """根据过滤器获取信号（新版本）。

        Args:
            filter_obj: SignalFilter 对象
            limit: 最大返回数量

        Returns:
            信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        signals = list(self._signals.values())

        # 应用过滤器
        if filter_obj:
            signals = [s for s in signals if filter_obj.matches(s)]

        # 按强度和引用次数排序
        def score(signal: Any) -> float:
            pheromone = self._signal_pheromones.get(signal.id)
            ref_count = pheromone.reference_count if pheromone else 0
            return ref_count * signal.strength

        signals.sort(key=score, reverse=True)

        return signals[:limit]

    def get_signals_by_dimension(
        self,
        dimension: Any,
        min_confidence: float = 0.0,
        min_strength: float = 0.0,
        verified_only: bool = False,
        limit: int = 50,
    ) -> list[Any]:
        """根据维度获取信号（新版本）。

        Args:
            dimension: Dimension 枚举值
            min_confidence: 最低置信度
            min_strength: 最低强度
            verified_only: 是否仅返回已验证的信号
            limit: 最大返回数量

        Returns:
            信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        signals = [
            s for s in self._signals.values()
            if s.dimension == dimension
            and s.confidence >= min_confidence
            and s.strength >= min_strength
        ]

        if verified_only:
            signals = [s for s in signals if s.verified]

        # 按强度排序
        signals.sort(key=lambda s: s.strength, reverse=True)

        return signals[:limit]

    def get_signals_by_type(
        self,
        signal_type: Any,
        min_strength: float = 0.0,
        verified_only: bool = False,
        limit: int = 50,
    ) -> list[Any]:
        """根据信号类型获取信号（新版本）。

        Args:
            signal_type: SignalType 枚举值
            min_strength: 最低强度
            verified_only: 是否仅返回已验证的信号
            limit: 最大返回数量

        Returns:
            信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        signals = [
            s for s in self._signals.values()
            if s.signal_type == signal_type
            and s.strength >= min_strength
        ]

        if verified_only:
            signals = [s for s in signals if s.verified]

        # 按强度排序
        signals.sort(key=lambda s: s.strength, reverse=True)

        return signals[:limit]

    def get_related_signals(
        self,
        signal_id: str,
        max_distance: int = 2,
        limit: int = 20,
    ) -> list[Any]:
        """获取相关信号（基于引用关系）（新版本）。

        Args:
            signal_id: 起始信号 ID
            max_distance: 最大关联距离
            limit: 最大返回数量

        Returns:
            相关信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        related = set()
        to_visit = {signal_id}
        visited = set()

        for _ in range(max_distance):
            if not to_visit:
                break
            current = to_visit - visited
            visited |= current
            next_visit = set()
            for sid in current:
                signal = self._signals.get(sid)
                if signal:
                    related.add(signal.id)
                    next_visit.update(signal.references)
            to_visit = next_visit - visited

        signals = [self._signals[sid] for sid in related if sid in self._signals]
        signals.sort(key=lambda s: s.strength, reverse=True)

        return signals[:limit]

    def get_hot_signals(self, limit: int = 5) -> list[Any]:
        """获取热门信号（高引用计数）（新版本）。

        Args:
            limit: 最大返回数量

        Returns:
            热门信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        scored = [
            (s, self._signal_pheromones[s.id].reference_count)
            for s in self._signals.values()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored[:limit]]

    def get_fresh_signals(
        self,
        max_age_hours: int = 24,
        limit: int = 50,
    ) -> list[Any]:
        """获取新鲜信号（新版本）。

        Args:
            max_age_hours: 最大年龄（小时）
            limit: 最大返回数量

        Returns:
            新鲜信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        signals = [
            s for s in self._signals.values()
            if s.is_fresh(max_age_hours)
        ]

        signals.sort(key=lambda s: s.timestamp, reverse=True)

        return signals[:limit]

    def aggregate_signals_by_dimension(self) -> dict[Any, list[Any]]:
        """按维度聚合信号（新版本）。

        Returns:
            按维度分组的信号字典
        """
        if not SIGNALS_AVAILABLE:
            return {}

        result: dict[Any, list[Any]] = {}
        for signal in self._signals.values():
            dim = signal.dimension
            if dim not in result:
                result[dim] = []
            result[dim].append(signal)

        # 每个维度内按强度排序
        for dim in result:
            result[dim].sort(key=lambda s: s.strength, reverse=True)

        return result

    def aggregate_signals_by_type(self) -> dict[Any, list[Any]]:
        """按类型聚合信号（新版本）。

        Returns:
            按类型分组的信号字典
        """
        if not SIGNALS_AVAILABLE:
            return {}

        result: dict[Any, list[Any]] = {}
        for signal in self._signals.values():
            sig_type = signal.signal_type
            if sig_type not in result:
                result[sig_type] = []
            result[sig_type].append(signal)

        # 每个类型内按强度排序
        for sig_type in result:
            result[sig_type].sort(key=lambda s: s.strength, reverse=True)

        return result

    # ========== 跨 Agent 洞察 ==========

    def get_cross_agent_insights(self) -> list[dict[str, Any]]:
        """获取跨 Agent 的关联洞察。

        分析不同 Agent 之间的引用关系。
        优先使用 Signal，如果没有则使用 Discovery。

        Returns:
            关联洞察列表
        """
        insights = []

        # 优先使用 Signal
        if SIGNALS_AVAILABLE and self._signals:
            for signal_id, pheromone in self._signal_pheromones.items():
                if pheromone.reference_count > 0:
                    signal = self._signals.get(signal_id)
                    if signal:
                        # 找出引用了这个信号的其他 Agent
                        referrers = [
                            s.author_agent
                            for s in self._signals.values()
                            if signal_id in s.references and s.author_agent != signal.author_agent
                        ]
                        if referrers:
                            evidence = signal.evidence[:100] + "..." if len(signal.evidence) > 100 else signal.evidence
                            insights.append({
                                "item_id": signal_id,
                                "content": evidence,
                                "from_agent": signal.author_agent,
                                "referenced_by": list(set(referrers)),
                                "reference_count": pheromone.reference_count,
                                "dimension": signal.dimension.value if SIGNALS_AVAILABLE else "",
                            })
        else:
            # 使用 Discovery（向后兼容）
            for discovery_id, pheromone in self._pheromones.items():
                if pheromone.reference_count > 0:
                    discovery = self._discoveries.get(discovery_id)
                    if discovery:
                        referrers = [
                            d.agent_type
                            for d in self._discoveries.values()
                            if discovery_id in d.references and d.agent_type != discovery.agent_type
                        ]
                        if referrers:
                            insights.append({
                                "item_id": discovery_id,
                                "content": discovery.content[:100] + "..." if len(discovery.content) > 100 else discovery.content,
                                "from_agent": discovery.agent_type,
                                "referenced_by": list(set(referrers)),
                                "reference_count": pheromone.reference_count,
                                "dimension": "",
                            })

        insights.sort(key=lambda x: x["reference_count"], reverse=True)
        return insights

    # ========== 持久化 ==========

    def save(self, filename: str = "environment.json") -> None:
        """保存环境到文件。

        Args:
            filename: 文件名
        """
        cache_file = self._cache_path / filename

        data = {
            "discoveries": [d.to_dict() for d in self._discoveries.values()],
            "signals": [s.to_dict() for s in self._signals.values()] if SIGNALS_AVAILABLE else [],
            "pheromones": [
                {
                    "discovery_id": p.discovery_id,
                    "reference_count": p.reference_count,
                    "last_accessed": p.last_accessed,
                }
                for p in self._pheromones.values()
            ],
            "signal_pheromones": [
                {
                    "signal_id": p.item_id,
                    "reference_count": p.reference_count,
                    "last_accessed": p.last_accessed,
                }
                for p in self._signal_pheromones.values()
            ],
            "timestamp": datetime.now().isoformat(),
        }

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, filename: str = "environment.json") -> bool:
        """从文件加载环境。

        Args:
            filename: 文件名

        Returns:
            是否成功加载
        """
        cache_file = self._cache_path / filename

        if not cache_file.exists():
            return False

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 加载 Discoveries
            self._discoveries = {
                d["id"]: Discovery.from_dict(d)
                for d in data.get("discoveries", [])
            }

            # 加载 Signals
            if SIGNALS_AVAILABLE:
                self._signals = {
                    s["id"]: Signal.from_dict(s)
                    for s in data.get("signals", [])
                }
            else:
                self._signals = {}

            # 加载 Pheromones
            self._pheromones = {}
            for p_data in data.get("pheromones", []):
                pheromone = VirtualPheromone(
                    discovery_id=p_data["discovery_id"],
                    reference_count=p_data.get("reference_count", 0),
                    last_accessed=p_data.get("last_accessed", ""),
                )
                self._pheromones[pheromone.discovery_id] = pheromone

            # 加载 Signal Pheromones
            self._signal_pheromones = {}
            for p_data in data.get("signal_pheromones", []):
                pheromone = VirtualPheromone(
                    discovery_id=p_data["signal_id"],
                    reference_count=p_data.get("reference_count", 0),
                    last_accessed=p_data.get("last_accessed", ""),
                )
                self._signal_pheromones[pheromone.item_id] = pheromone

            return True

        except (json.JSONDecodeError, KeyError):
            return False

    def clear(self) -> None:
        """清空环境。"""
        self._discoveries.clear()
        self._pheromones.clear()
        self._signals.clear()
        self._signal_pheromones.clear()

    # ========== 属性 ==========

    @property
    def discovery_count(self) -> int:
        """发现总数（旧版本）。"""
        return len(self._discoveries)

    @property
    def signal_count(self) -> int:
        """信号总数（新版本）。"""
        return len(self._signals)

    @property
    def all_discoveries(self) -> list[Discovery]:
        """所有发现（旧版本）。"""
        return list(self._discoveries.values())

    @property
    def all_signals(self) -> list[Any]:
        """所有信号（新版本）。"""
        return list(self._signals.values())


# 全局环境实例（延迟加载）
_environment: StigmergyEnvironment | None = None


def get_environment() -> StigmergyEnvironment:
    """获取全局环境实例。

    Returns:
        共享环境
    """
    global _environment
    if _environment is None:
        _environment = StigmergyEnvironment()
    return _environment


def reset_environment() -> None:
    """重置全局环境。"""
    global _environment
    _environment = None
