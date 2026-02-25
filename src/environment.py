"""共享环境模块。

实现 Stigmergy 通信机制，允许 Agent 之间通过共享环境间接通信。

支持两种数据结构：
- Discovery: 旧版本发现格式（向后兼容）
- Signal: 新版本信号格式（推荐使用）
"""

import json
import math
import re
import threading
import uuid
from collections import Counter
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


class SignalGraphEdgeType(str, Enum):
    """Signal 图边类型。"""

    REFERENCE_EXPLICIT = "reference_explicit"
    SEMANTIC_LINK = "semantic_link"
    DEBATE_SUPPORT = "debate_support"
    DEBATE_ATTACK = "debate_attack"


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

    @property
    def discovery_id(self) -> str:
        """兼容旧字段名。"""
        return self.item_id

    def update_access(self) -> None:
        """更新访问时间。"""
        self.last_accessed = datetime.now().isoformat()


@dataclass
class PheromoneState:
    """动态信息素状态。"""

    signal_id: str
    value: float = 0.0
    last_updated_at: str = ""
    source_breakdown: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.last_updated_at:
            self.last_updated_at = datetime.now().isoformat()
        self.value = max(0.0, min(1.0, float(self.value)))


@dataclass(frozen=True)
class SignalGraphEdge:
    """Signal 图边。"""

    src: str
    dst: str
    edge_type: SignalGraphEdgeType
    weight: float
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            object.__setattr__(self, "created_at", datetime.now().isoformat())


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

    # 动态信息素参数默认值（平衡版）
    DEFAULT_PHEROMONE_DECAY_LAMBDA: float = 0.08
    DEFAULT_PHEROMONE_REFERENCE_WEIGHT: float = 0.20
    DEFAULT_PHEROMONE_VALIDATION_WEIGHT: float = 0.15
    DEFAULT_PHEROMONE_DEBATE_WEIGHT: float = 0.25
    DEFAULT_PHEROMONE_FRESHNESS_WEIGHT: float = 0.05
    DEFAULT_PHEROMONE_DIFFUSION_WEIGHT: float = 0.10
    DEFAULT_SEMANTIC_LINK_THRESHOLD: float = 0.30
    DEFAULT_SEMANTIC_LINK_MAX_EDGES: int = 8

    def __init__(
        self,
        cache_path: str | None = None,
        signal_ttl_hours: int | None = None,
        discovery_ttl_hours: int | None = None,
        max_signals: int | None = None,
        max_discoveries: int | None = None,
        run_isolation: bool | None = None,
        discovery_migration_deadline: str | None = None,
    ) -> None:
        """初始化环境。

        Args:
            cache_path: 缓存目录路径
        """
        config = get_config()
        env_config = getattr(config, "environment", None)

        self._cache_path = Path(cache_path or config.cache.path)
        self._cache_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        self._signal_ttl_hours = (
            signal_ttl_hours
            if signal_ttl_hours is not None
            else getattr(env_config, "signal_ttl_hours", 24)
        )
        self._discovery_ttl_hours = (
            discovery_ttl_hours
            if discovery_ttl_hours is not None
            else getattr(env_config, "discovery_ttl_hours", 24)
        )
        self._max_signals = (
            max_signals
            if max_signals is not None
            else getattr(env_config, "max_signals", 5000)
        )
        self._max_discoveries = (
            max_discoveries
            if max_discoveries is not None
            else getattr(env_config, "max_discoveries", 1000)
        )
        self._run_isolation = (
            run_isolation
            if run_isolation is not None
            else getattr(env_config, "run_isolation", True)
        )
        self._discovery_migration_deadline = (
            discovery_migration_deadline
            if discovery_migration_deadline is not None
            else getattr(env_config, "discovery_migration_deadline", "2026-06-30")
        )
        self._pheromone_decay_lambda = float(
            getattr(env_config, "pheromone_decay_lambda", self.DEFAULT_PHEROMONE_DECAY_LAMBDA)
        )
        self._pheromone_reference_weight = float(
            getattr(env_config, "pheromone_reference_weight", self.DEFAULT_PHEROMONE_REFERENCE_WEIGHT)
        )
        self._pheromone_validation_weight = float(
            getattr(env_config, "pheromone_validation_weight", self.DEFAULT_PHEROMONE_VALIDATION_WEIGHT)
        )
        self._pheromone_debate_weight = float(
            getattr(env_config, "pheromone_debate_weight", self.DEFAULT_PHEROMONE_DEBATE_WEIGHT)
        )
        self._pheromone_freshness_weight = float(
            getattr(env_config, "pheromone_freshness_weight", self.DEFAULT_PHEROMONE_FRESHNESS_WEIGHT)
        )
        self._pheromone_diffusion_weight = float(
            getattr(env_config, "pheromone_diffusion_weight", self.DEFAULT_PHEROMONE_DIFFUSION_WEIGHT)
        )
        self._semantic_link_threshold = float(
            getattr(env_config, "semantic_link_threshold", self.DEFAULT_SEMANTIC_LINK_THRESHOLD)
        )
        self._semantic_link_max_edges = int(
            getattr(env_config, "semantic_link_max_edges", self.DEFAULT_SEMANTIC_LINK_MAX_EDGES)
        )
        self._current_run_id: str | None = None

        # 旧版本 Discovery 存储
        self._discoveries: dict[str, Discovery] = {}
        self._pheromones: dict[str, VirtualPheromone] = {}

        # 新版本 Signal 存储
        self._signals: dict[str, Any] = {} if not SIGNALS_AVAILABLE else {}
        self._signal_pheromones: dict[str, VirtualPheromone] = {}
        self._signal_pheromone_states: dict[str, PheromoneState] = {}
        self._signal_graph_edges: dict[tuple[str, str, str], SignalGraphEdge] = {}

    def begin_run(self, run_id: str | None = None, clear: bool = True) -> str:
        """开启一个新的分析运行上下文。"""
        with self._lock:
            if clear:
                self.clear()
            self._current_run_id = run_id or str(uuid.uuid4())
            return self._current_run_id

    @property
    def current_run_id(self) -> str | None:
        """当前运行 ID。"""
        return self._current_run_id

    def _extract_run_id(self, metadata: dict[str, Any] | None) -> str | None:
        if not isinstance(metadata, dict):
            return None
        run_id = metadata.get("_run_id")
        return str(run_id) if run_id else None

    def _apply_runtime_metadata(self, metadata: dict[str, Any] | None, compat_layer: bool = False) -> dict[str, Any]:
        """补充兼容层与运行时元数据。"""
        normalized = dict(metadata or {})
        if compat_layer:
            normalized.setdefault("_compat_layer", True)
            normalized.setdefault("migration_deadline", self._discovery_migration_deadline)

        if self._run_isolation and self._current_run_id:
            normalized.setdefault("_run_id", self._current_run_id)
        return normalized

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def _is_expired(self, timestamp: str | None, ttl_hours: int) -> bool:
        if ttl_hours <= 0:
            return False
        dt = self._parse_timestamp(timestamp)
        if dt is None:
            return False
        return (datetime.now() - dt).total_seconds() > ttl_hours * 3600

    def _is_discovery_visible(self, discovery: Discovery) -> bool:
        if not self._run_isolation or not self._current_run_id:
            return True
        return self._extract_run_id(discovery.metadata) == self._current_run_id

    def _is_signal_visible(self, signal: Any) -> bool:
        if not self._run_isolation or not self._current_run_id:
            return True
        signal_metadata = getattr(signal, "metadata", {})
        return self._extract_run_id(signal_metadata) == self._current_run_id

    @staticmethod
    def _clip01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def _hours_since(self, timestamp: str | None) -> float:
        dt = self._parse_timestamp(timestamp)
        if dt is None:
            return 0.0
        return max(0.0, (datetime.now() - dt).total_seconds() / 3600.0)

    @staticmethod
    def _tokenize_text(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", str(text).lower())
            if len(token) >= 2
        }

    def _semantic_similarity(self, left: str, right: str) -> float:
        left_tokens = self._tokenize_text(left)
        right_tokens = self._tokenize_text(right)
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = left_tokens & right_tokens
        if not overlap:
            return 0.0
        union = left_tokens | right_tokens
        return len(overlap) / max(1, len(union))

    def _make_edge_key(self, src: str, dst: str, edge_type: SignalGraphEdgeType) -> tuple[str, str, str]:
        return (src, dst, edge_type.value)

    def _upsert_signal_edge(
        self,
        src: str,
        dst: str,
        edge_type: SignalGraphEdgeType,
        weight: float,
    ) -> None:
        if not src or not dst or src == dst:
            return
        if src not in self._signals or dst not in self._signals:
            return
        key = self._make_edge_key(src, dst, edge_type)
        normalized_weight = max(0.0, min(1.0, float(weight)))
        existing = self._signal_graph_edges.get(key)
        if existing is not None:
            normalized_weight = max(normalized_weight, existing.weight)
        self._signal_graph_edges[key] = SignalGraphEdge(
            src=src,
            dst=dst,
            edge_type=edge_type,
            weight=normalized_weight,
            created_at=datetime.now().isoformat(),
        )

    def _ensure_pheromone_state(self, signal_id: str) -> PheromoneState:
        state = self._signal_pheromone_states.get(signal_id)
        if state is not None:
            return state

        signal = self._signals.get(signal_id)
        initial_value = getattr(signal, "strength", 0.0) if signal is not None else 0.0
        state = PheromoneState(
            signal_id=signal_id,
            value=self._clip01(initial_value),
            source_breakdown={
                "reference": 0.0,
                "validation": 0.0,
                "debate": 0.0,
                "freshness": 0.0,
                "diffusion": 0.0,
            },
        )
        self._signal_pheromone_states[signal_id] = state
        return state

    def _decay_pheromone_state(self, signal_id: str, now: datetime | None = None) -> float:
        state = self._ensure_pheromone_state(signal_id)
        now_dt = now or datetime.now()
        elapsed_hours = self._hours_since(state.last_updated_at)
        if elapsed_hours <= 0:
            return state.value
        decay = math.exp(-self._pheromone_decay_lambda * elapsed_hours)
        decayed_value = self._clip01(state.value * decay)
        self._signal_pheromone_states[signal_id] = PheromoneState(
            signal_id=state.signal_id,
            value=decayed_value,
            last_updated_at=now_dt.isoformat(),
            source_breakdown=dict(state.source_breakdown),
        )
        return decayed_value

    def _apply_decay_to_all_signal_pheromones(self) -> None:
        now = datetime.now()
        for signal_id in list(self._signal_pheromone_states.keys()):
            if signal_id not in self._signals:
                self._signal_pheromone_states.pop(signal_id, None)
                continue
            self._decay_pheromone_state(signal_id, now=now)

    def _calculate_diffusion_delta(self, signal_id: str) -> float:
        state = self._ensure_pheromone_state(signal_id)
        current_value = state.value
        diffusion_raw = 0.0

        for edge in self._signal_graph_edges.values():
            if edge.dst != signal_id:
                continue
            src_state = self._signal_pheromone_states.get(edge.src)
            if src_state is None:
                continue
            diffusion_raw += edge.weight * (src_state.value - current_value)

        return self._pheromone_diffusion_weight * diffusion_raw

    def _update_signal_pheromone(
        self,
        signal_id: str,
        *,
        reference_delta: float = 0.0,
        validation_delta: float = 0.0,
        debate_delta: float = 0.0,
        freshness_delta: float = 0.0,
    ) -> float:
        if signal_id not in self._signals:
            return 0.0

        self._apply_decay_to_all_signal_pheromones()
        state = self._ensure_pheromone_state(signal_id)
        diffusion_delta = self._calculate_diffusion_delta(signal_id)

        new_value = self._clip01(
            state.value
            + self._pheromone_reference_weight * reference_delta
            + self._pheromone_validation_weight * validation_delta
            + self._pheromone_debate_weight * debate_delta
            + self._pheromone_freshness_weight * freshness_delta
            + diffusion_delta
        )

        source_breakdown = dict(state.source_breakdown)
        source_breakdown["reference"] = source_breakdown.get("reference", 0.0) + (
            self._pheromone_reference_weight * reference_delta
        )
        source_breakdown["validation"] = source_breakdown.get("validation", 0.0) + (
            self._pheromone_validation_weight * validation_delta
        )
        source_breakdown["debate"] = source_breakdown.get("debate", 0.0) + (
            self._pheromone_debate_weight * debate_delta
        )
        source_breakdown["freshness"] = source_breakdown.get("freshness", 0.0) + (
            self._pheromone_freshness_weight * freshness_delta
        )
        source_breakdown["diffusion"] = source_breakdown.get("diffusion", 0.0) + diffusion_delta

        self._signal_pheromone_states[signal_id] = PheromoneState(
            signal_id=signal_id,
            value=new_value,
            last_updated_at=datetime.now().isoformat(),
            source_breakdown=source_breakdown,
        )
        return new_value

    def _register_semantic_edges_for_signal(self, signal_obj: Any) -> None:
        if self._semantic_link_threshold <= 0:
            return

        signal_text = str(getattr(signal_obj, "evidence", "") or "")
        if not signal_text.strip():
            return

        candidates: list[tuple[str, float]] = []
        for other in self._signals.values():
            other_id = getattr(other, "id", "")
            if not other_id or other_id == signal_obj.id:
                continue
            if not self._is_signal_visible(other):
                continue
            similarity = self._semantic_similarity(
                signal_text,
                str(getattr(other, "evidence", "") or ""),
            )
            if similarity >= self._semantic_link_threshold:
                candidates.append((other_id, similarity))

        candidates.sort(key=lambda item: item[1], reverse=True)
        for other_id, similarity in candidates[: max(0, self._semantic_link_max_edges)]:
            self._upsert_signal_edge(
                signal_obj.id,
                other_id,
                SignalGraphEdgeType.SEMANTIC_LINK,
                similarity,
            )
            self._upsert_signal_edge(
                other_id,
                signal_obj.id,
                SignalGraphEdgeType.SEMANTIC_LINK,
                similarity,
            )

    def _calculate_query_relevance(self, signal: Any, query: str | None) -> float:
        if not query:
            return 0.0
        signal_tokens = self._tokenize_text(str(getattr(signal, "evidence", "") or ""))
        query_tokens = self._tokenize_text(query)
        if not signal_tokens or not query_tokens:
            return 0.0
        overlap = signal_tokens & query_tokens
        return len(overlap) / max(1, len(query_tokens))

    def _calculate_cross_agent_entropy(self, signal_id: str) -> float:
        source_agents: list[str] = []
        for edge in self._signal_graph_edges.values():
            if edge.dst != signal_id:
                continue
            src_signal = self._signals.get(edge.src)
            if src_signal is None:
                continue
            src_agent = str(getattr(src_signal, "author_agent", "") or "")
            if src_agent:
                source_agents.append(src_agent)

        if not source_agents:
            return 0.0

        counts = Counter(source_agents)
        total = sum(counts.values())
        if total <= 0:
            return 0.0
        probabilities = [count / total for count in counts.values()]
        entropy = -sum(prob * math.log(prob) for prob in probabilities if prob > 0)
        max_entropy = math.log(len(counts)) if len(counts) > 1 else 1.0
        return entropy / max_entropy if max_entropy > 0 else 0.0

    def get_signal_pheromone_value(self, signal_id: str) -> float:
        """获取信号的信息素强度（0-1）。"""
        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            state = self._signal_pheromone_states.get(signal_id)
            if state is not None:
                return self._clip01(state.value)
            signal = self._signals.get(signal_id)
            if signal is None:
                return 0.0
            return self._clip01(getattr(signal, "strength", 0.0))

    def apply_signal_event(
        self,
        signal_id: str,
        *,
        reference_delta: float = 0.0,
        validation_delta: float = 0.0,
        debate_delta: float = 0.0,
        freshness_delta: float = 0.0,
    ) -> float:
        """应用信号事件并更新动态信息素。"""
        with self._lock:
            self.prune()
            return self._update_signal_pheromone(
                signal_id,
                reference_delta=reference_delta,
                validation_delta=validation_delta,
                debate_delta=debate_delta,
                freshness_delta=freshness_delta,
            )

    def register_debate_relation(
        self,
        src_signal_id: str,
        dst_signal_id: str,
        *,
        support: bool,
        weight: float = 1.0,
    ) -> None:
        """注册辩论关系边。"""
        with self._lock:
            self.prune()
            edge_type = SignalGraphEdgeType.DEBATE_SUPPORT if support else SignalGraphEdgeType.DEBATE_ATTACK
            self._upsert_signal_edge(
                src_signal_id,
                dst_signal_id,
                edge_type,
                weight,
            )

    def get_signal_graph_edges(
        self,
        edge_types: set[SignalGraphEdgeType] | None = None,
        *,
        min_weight: float = 0.0,
        limit: int = 5000,
    ) -> list[SignalGraphEdge]:
        """返回可见信号之间的图边。"""
        with self._lock:
            self.prune()
            visible_signal_ids = {
                signal.id
                for signal in self._signals.values()
                if self._is_signal_visible(signal)
            }
            edges = [
                edge
                for edge in self._signal_graph_edges.values()
                if edge.src in visible_signal_ids
                and edge.dst in visible_signal_ids
                and edge.weight >= min_weight
                and (edge_types is None or edge.edge_type in edge_types)
            ]
            edges.sort(key=lambda item: item.weight, reverse=True)
            return edges[: max(0, limit)]

    def get_signal_neighbors(
        self,
        signal_id: str,
        edge_types: set[SignalGraphEdgeType] | None = None,
        *,
        min_weight: float = 0.0,
        limit: int = 100,
    ) -> list[SignalGraphEdge]:
        """返回指定信号的出入边。"""
        with self._lock:
            self.prune()
            neighbors = [
                edge
                for edge in self._signal_graph_edges.values()
                if (edge.src == signal_id or edge.dst == signal_id)
                and edge.weight >= min_weight
                and (edge_types is None or edge.edge_type in edge_types)
            ]
            neighbors.sort(key=lambda item: item.weight, reverse=True)
            return neighbors[: max(0, limit)]

    def _signal_gradient_score(self, signal: Any, query: str | None = None) -> float:
        signal_id = str(getattr(signal, "id", "") or "")
        if not signal_id:
            return 0.0

        state = self._signal_pheromone_states.get(signal_id)
        if state is not None:
            pheromone_score = self._clip01(state.value)
        else:
            pheromone_score = self._clip01(getattr(signal, "strength", 0.0))
        age_hours = self._hours_since(getattr(signal, "timestamp", ""))
        fresh_score = 1.0 / (1.0 + max(0.0, age_hours))
        relevance_score = self._calculate_query_relevance(signal, query)
        entropy_score = self._calculate_cross_agent_entropy(signal_id)

        return (
            0.35 * pheromone_score
            + 0.25 * fresh_score
            + 0.25 * relevance_score
            + 0.15 * entropy_score
        )

    def prune(self) -> None:
        """执行过期和容量治理。"""
        with self._lock:
            self._prune_expired()
            self._enforce_capacity()
            visible_signal_ids = set(self._signals.keys())
            for signal_id in list(self._signal_pheromone_states.keys()):
                if signal_id not in visible_signal_ids:
                    self._signal_pheromone_states.pop(signal_id, None)
            stale_edges = [
                key
                for key, edge in self._signal_graph_edges.items()
                if edge.src not in visible_signal_ids or edge.dst not in visible_signal_ids
            ]
            for key in stale_edges:
                self._signal_graph_edges.pop(key, None)

    def _prune_expired(self) -> None:
        expired_discovery_ids = [
            item_id
            for item_id, discovery in self._discoveries.items()
            if self._is_expired(discovery.timestamp, self._discovery_ttl_hours)
        ]
        for item_id in expired_discovery_ids:
            self._discoveries.pop(item_id, None)
            self._pheromones.pop(item_id, None)

        expired_signal_ids = [
            item_id
            for item_id, signal in self._signals.items()
            if self._is_expired(getattr(signal, "timestamp", ""), self._signal_ttl_hours)
        ]
        for item_id in expired_signal_ids:
            self._signals.pop(item_id, None)
            self._signal_pheromones.pop(item_id, None)
            self._signal_pheromone_states.pop(item_id, None)

        if expired_signal_ids:
            expired_set = set(expired_signal_ids)
            stale_keys = [
                key
                for key, edge in self._signal_graph_edges.items()
                if edge.src in expired_set or edge.dst in expired_set
            ]
            for key in stale_keys:
                self._signal_graph_edges.pop(key, None)

    def _enforce_capacity(self) -> None:
        if self._max_discoveries > 0 and len(self._discoveries) > self._max_discoveries:
            overflow = len(self._discoveries) - self._max_discoveries
            ordered_ids = sorted(
                self._discoveries.keys(),
                key=lambda item_id: self._parse_timestamp(self._discoveries[item_id].timestamp) or datetime.min,
            )
            for item_id in ordered_ids[:overflow]:
                self._discoveries.pop(item_id, None)
                self._pheromones.pop(item_id, None)

        if self._max_signals > 0 and len(self._signals) > self._max_signals:
            overflow = len(self._signals) - self._max_signals
            ordered_ids = sorted(
                self._signals.keys(),
                key=lambda item_id: self._parse_timestamp(getattr(self._signals[item_id], "timestamp", "")) or datetime.min,
            )
            for item_id in ordered_ids[:overflow]:
                self._signals.pop(item_id, None)
                self._signal_pheromones.pop(item_id, None)
                self._signal_pheromone_states.pop(item_id, None)

            visible_signal_ids = set(self._signals.keys())
            stale_keys = [
                key
                for key, edge in self._signal_graph_edges.items()
                if edge.src not in visible_signal_ids or edge.dst not in visible_signal_ids
            ]
            for key in stale_keys:
                self._signal_graph_edges.pop(key, None)

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
        with self._lock:
            self.prune()
            discovery_id = str(uuid.uuid4())

            discovery = Discovery(
                id=discovery_id,
                agent_type=agent_type,
                content=content,
                source=source,
                quality_score=max(0.0, min(1.0, quality_score)),
                timestamp=datetime.now().isoformat(),
                references=references or [],
                metadata=self._apply_runtime_metadata(metadata, compat_layer=True),
            )

            self._discoveries[discovery_id] = discovery
            self._pheromones[discovery_id] = VirtualPheromone(discovery_id)

            # 更新被引用发现的计数
            for ref_id in discovery.references:
                if ref_id in self._pheromones:
                    self._pheromones[ref_id].reference_count += 1

            self._enforce_capacity()
            return discovery

    def get_discovery(self, discovery_id: str) -> Discovery | None:
        """获取特定发现（旧版本）。

        Args:
            discovery_id: 发现 ID

        Returns:
            发现对象，如果不存在返回 None
        """
        with self._lock:
            self.prune()
            discovery = self._discoveries.get(discovery_id)
            if discovery and not self._is_discovery_visible(discovery):
                return None
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
        with self._lock:
            self.prune()
            return [
                d for d in self._discoveries.values()
                if d.agent_type == agent_type and self._is_discovery_visible(d)
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
        with self._lock:
            self.prune()
            discoveries = [d for d in self._discoveries.values() if self._is_discovery_visible(d)]

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
        with self._lock:
            self.prune()
            scored = [
                (d, self._pheromones[d.id].reference_count)
                for d in self._discoveries.values()
                if self._is_discovery_visible(d)
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

        with self._lock:
            self.prune()

            signal_obj = signal
            if self._run_isolation and self._current_run_id and hasattr(signal_obj, "to_dict"):
                signal_data = signal_obj.to_dict()
                signal_data["metadata"] = self._apply_runtime_metadata(
                    signal_data.get("metadata"),
                    compat_layer=False,
                )
                signal_obj = Signal.from_dict(signal_data)

            self._signals[signal_obj.id] = signal_obj
            self._signal_pheromones[signal_obj.id] = VirtualPheromone(signal_obj.id)
            self._ensure_pheromone_state(signal_obj.id)

            # 更新被引用信号的计数
            for ref_id in signal_obj.references:
                if ref_id in self._signal_pheromones:
                    self._signal_pheromones[ref_id].reference_count += 1
                    self._update_signal_pheromone(
                        ref_id,
                        reference_delta=1.0,
                    )
                if ref_id in self._signals:
                    # 显式引用边（双向建边，支持扩散）
                    self._upsert_signal_edge(
                        signal_obj.id,
                        ref_id,
                        SignalGraphEdgeType.REFERENCE_EXPLICIT,
                        1.0,
                    )
                    self._upsert_signal_edge(
                        ref_id,
                        signal_obj.id,
                        SignalGraphEdgeType.REFERENCE_EXPLICIT,
                        1.0,
                    )

            self._register_semantic_edges_for_signal(signal_obj)
            self._update_signal_pheromone(
                signal_obj.id,
                reference_delta=float(len(signal_obj.references)),
                freshness_delta=1.0,
            )

            self._enforce_capacity()
            return signal_obj

    def get_signal(self, signal_id: str) -> Any | None:
        """获取特定信号（新版本）。

        Args:
            signal_id: 信号 ID

        Returns:
            信号对象，如果不存在返回 None
        """
        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            signal = self._signals.get(signal_id)
            if signal and not self._is_signal_visible(signal):
                return None
            if signal and signal_id in self._signal_pheromones:
                self._signal_pheromones[signal_id].update_access()
                self._update_signal_pheromone(signal_id, freshness_delta=0.1)
            return signal

    def get_signals_by_filter(
        self,
        filter_obj: Any | None = None,
        limit: int = 50,
        query: str | None = None,
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

        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            signals = [s for s in self._signals.values() if self._is_signal_visible(s)]

            # 应用过滤器
            if filter_obj:
                signals = [s for s in signals if filter_obj.matches(s)]

            signals.sort(
                key=lambda signal: self._signal_gradient_score(signal, query=query),
                reverse=True,
            )
            return signals[:limit]

    def rank_signals_for_query(
        self,
        query: str,
        *,
        limit: int = 20,
        verified_only: bool = False,
        min_confidence: float = 0.0,
        min_strength: float = 0.0,
    ) -> list[Any]:
        """按梯度评分检索最相关信号。"""
        if not SIGNALS_AVAILABLE:
            return []

        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            signals = [
                signal
                for signal in self._signals.values()
                if self._is_signal_visible(signal)
                and signal.confidence >= min_confidence
                and signal.strength >= min_strength
                and (not verified_only or signal.verified)
            ]
            signals.sort(
                key=lambda signal: self._signal_gradient_score(signal, query=query),
                reverse=True,
            )
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

        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            signals = [
                s for s in self._signals.values()
                if self._is_signal_visible(s)
                and s.dimension == dimension
                and s.confidence >= min_confidence
                and s.strength >= min_strength
            ]

            if verified_only:
                signals = [s for s in signals if s.verified]

            signals.sort(key=lambda s: self._signal_gradient_score(s), reverse=True)
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

        with self._lock:
            self.prune()
            signals = [
                s for s in self._signals.values()
                if self._is_signal_visible(s)
                and s.signal_type == signal_type
                and s.strength >= min_strength
            ]

            if verified_only:
                signals = [s for s in signals if s.verified]

            signals.sort(key=lambda s: self._signal_gradient_score(s), reverse=True)
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

        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
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
                    if signal and self._is_signal_visible(signal):
                        related.add(signal.id)
                        next_visit.update(signal.references)
                to_visit = next_visit - visited

            signals = [
                self._signals[sid]
                for sid in related
                if sid in self._signals and self._is_signal_visible(self._signals[sid])
            ]
            signals.sort(key=lambda s: self._signal_gradient_score(s), reverse=True)
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

        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            scored = [
                (s, self.get_signal_pheromone_value(s.id))
                for s in self._signals.values()
                if self._is_signal_visible(s)
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

        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            signals = [
                s for s in self._signals.values()
                if self._is_signal_visible(s) and s.is_fresh(max_age_hours)
            ]

            signals.sort(key=lambda s: self._signal_gradient_score(s), reverse=True)
            return signals[:limit]

    def aggregate_signals_by_dimension(self) -> dict[Any, list[Any]]:
        """按维度聚合信号（新版本）。

        Returns:
            按维度分组的信号字典
        """
        if not SIGNALS_AVAILABLE:
            return {}

        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            result: dict[Any, list[Any]] = {}
            for signal in self._signals.values():
                if not self._is_signal_visible(signal):
                    continue
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

        with self._lock:
            self.prune()
            self._apply_decay_to_all_signal_pheromones()
            result: dict[Any, list[Any]] = {}
            for signal in self._signals.values():
                if not self._is_signal_visible(signal):
                    continue
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
        with self._lock:
            self.prune()
            insights = []
            # 优先使用 Signal
            if SIGNALS_AVAILABLE and self._signals:
                for signal_id, pheromone in self._signal_pheromones.items():
                    if pheromone.reference_count <= 0:
                        continue
                    signal = self._signals.get(signal_id)
                    if not signal or not self._is_signal_visible(signal):
                        continue

                    # 找出引用了这个信号的其他 Agent
                    referrers = [
                        s.author_agent
                        for s in self._signals.values()
                        if (
                            self._is_signal_visible(s)
                            and signal_id in s.references
                            and s.author_agent != signal.author_agent
                        )
                    ]
                    if not referrers:
                        continue

                    evidence = signal.evidence[:100] + "..." if len(signal.evidence) > 100 else signal.evidence
                    insights.append({
                        "item_id": signal_id,
                        "signal_id": signal_id,
                        "content": evidence,
                        "from_agent": signal.author_agent,
                        "referenced_by": sorted(set(referrers)),
                        "reference_count": pheromone.reference_count,
                        "dimension": signal.dimension.value,
                    })
            else:
                # 使用 Discovery（向后兼容）
                for discovery_id, pheromone in self._pheromones.items():
                    if pheromone.reference_count <= 0:
                        continue
                    discovery = self._discoveries.get(discovery_id)
                    if not discovery or not self._is_discovery_visible(discovery):
                        continue

                    referrers = [
                        d.agent_type
                        for d in self._discoveries.values()
                        if (
                            self._is_discovery_visible(d)
                            and discovery_id in d.references
                            and d.agent_type != discovery.agent_type
                        )
                    ]
                    if not referrers:
                        continue

                    insights.append({
                        "item_id": discovery_id,
                        "discovery_id": discovery_id,
                        "content": discovery.content[:100] + "..." if len(discovery.content) > 100 else discovery.content,
                        "from_agent": discovery.agent_type,
                        "referenced_by": sorted(set(referrers)),
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
        with self._lock:
            self.prune()

            visible_discovery_ids = {
                d.id for d in self._discoveries.values() if self._is_discovery_visible(d)
            }
            visible_signal_ids = {
                s.id for s in self._signals.values() if self._is_signal_visible(s)
            }

            data = {
                "discoveries": [
                    d.to_dict() for d in self._discoveries.values() if d.id in visible_discovery_ids
                ],
                "signals": [
                    s.to_dict() for s in self._signals.values() if s.id in visible_signal_ids
                ] if SIGNALS_AVAILABLE else [],
                "pheromones": [
                    {
                        "item_id": p.item_id,
                        "discovery_id": p.discovery_id,
                        "reference_count": p.reference_count,
                        "last_accessed": p.last_accessed,
                    }
                    for p in self._pheromones.values()
                    if p.item_id in visible_discovery_ids
                ],
                "signal_pheromones": [
                    {
                        "item_id": p.item_id,
                        "signal_id": p.item_id,
                        "reference_count": p.reference_count,
                        "last_accessed": p.last_accessed,
                    }
                    for p in self._signal_pheromones.values()
                    if p.item_id in visible_signal_ids
                ],
                "signal_pheromone_states": [
                    {
                        "signal_id": state.signal_id,
                        "value": state.value,
                        "last_updated_at": state.last_updated_at,
                        "source_breakdown": state.source_breakdown,
                    }
                    for state in self._signal_pheromone_states.values()
                    if state.signal_id in visible_signal_ids
                ],
                "signal_graph_edges": [
                    {
                        "src": edge.src,
                        "dst": edge.dst,
                        "edge_type": edge.edge_type.value,
                        "weight": edge.weight,
                        "created_at": edge.created_at,
                    }
                    for edge in self._signal_graph_edges.values()
                    if edge.src in visible_signal_ids and edge.dst in visible_signal_ids
                ],
                "timestamp": datetime.now().isoformat(),
                "run_id": self._current_run_id,
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

            with self._lock:
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
                    item_id = p_data.get("item_id") or p_data.get("discovery_id")
                    if not item_id:
                        continue
                    pheromone = VirtualPheromone(
                        item_id=item_id,
                        reference_count=p_data.get("reference_count", 0),
                        last_accessed=p_data.get("last_accessed", ""),
                    )
                    self._pheromones[pheromone.item_id] = pheromone

                # 加载 Signal Pheromones
                self._signal_pheromones = {}
                for p_data in data.get("signal_pheromones", []):
                    item_id = p_data.get("item_id") or p_data.get("signal_id")
                    if not item_id:
                        continue
                    pheromone = VirtualPheromone(
                        item_id=item_id,
                        reference_count=p_data.get("reference_count", 0),
                        last_accessed=p_data.get("last_accessed", ""),
                    )
                    self._signal_pheromones[pheromone.item_id] = pheromone

                # 加载动态信息素状态
                self._signal_pheromone_states = {}
                for state_data in data.get("signal_pheromone_states", []):
                    signal_id = state_data.get("signal_id")
                    if not signal_id:
                        continue
                    self._signal_pheromone_states[signal_id] = PheromoneState(
                        signal_id=signal_id,
                        value=state_data.get("value", 0.0),
                        last_updated_at=state_data.get("last_updated_at", ""),
                        source_breakdown=state_data.get("source_breakdown", {}) or {},
                    )

                # 兼容旧文件：没有动态信息素时从 signal_pheromones 回填
                if not self._signal_pheromone_states:
                    for signal_id, pheromone in self._signal_pheromones.items():
                        signal = self._signals.get(signal_id)
                        base_strength = getattr(signal, "strength", 0.0) if signal else 0.0
                        ref_score = min(1.0, float(pheromone.reference_count) / 10.0)
                        self._signal_pheromone_states[signal_id] = PheromoneState(
                            signal_id=signal_id,
                            value=self._clip01(0.6 * base_strength + 0.4 * ref_score),
                            last_updated_at=pheromone.last_accessed or datetime.now().isoformat(),
                            source_breakdown={"reference": ref_score},
                        )

                # 加载图边
                self._signal_graph_edges = {}
                for edge_data in data.get("signal_graph_edges", []):
                    src = str(edge_data.get("src") or "")
                    dst = str(edge_data.get("dst") or "")
                    edge_type_raw = str(edge_data.get("edge_type") or SignalGraphEdgeType.SEMANTIC_LINK.value)
                    if not src or not dst:
                        continue
                    try:
                        edge_type = SignalGraphEdgeType(edge_type_raw)
                    except ValueError:
                        edge_type = SignalGraphEdgeType.SEMANTIC_LINK
                    edge = SignalGraphEdge(
                        src=src,
                        dst=dst,
                        edge_type=edge_type,
                        weight=edge_data.get("weight", 0.0),
                        created_at=edge_data.get("created_at", ""),
                    )
                    self._signal_graph_edges[self._make_edge_key(src, dst, edge.edge_type)] = edge

                loaded_run_id = data.get("run_id")
                self._current_run_id = str(loaded_run_id) if loaded_run_id else self._current_run_id
                self.prune()
            return True

        except (json.JSONDecodeError, KeyError):
            return False

    def clear(self) -> None:
        """清空环境。"""
        with self._lock:
            self._discoveries.clear()
            self._pheromones.clear()
            self._signals.clear()
            self._signal_pheromones.clear()
            self._signal_pheromone_states.clear()
            self._signal_graph_edges.clear()

    # ========== 属性 ==========

    @property
    def discovery_count(self) -> int:
        """发现总数（旧版本）。"""
        with self._lock:
            self.prune()
            return sum(1 for discovery in self._discoveries.values() if self._is_discovery_visible(discovery))

    @property
    def signal_count(self) -> int:
        """信号总数（新版本）。"""
        with self._lock:
            self.prune()
            return sum(1 for signal in self._signals.values() if self._is_signal_visible(signal))

    @property
    def all_discoveries(self) -> list[Discovery]:
        """所有发现（旧版本）。"""
        with self._lock:
            self.prune()
            return [discovery for discovery in self._discoveries.values() if self._is_discovery_visible(discovery)]

    @property
    def all_signals(self) -> list[Any]:
        """所有信号（新版本）。"""
        with self._lock:
            self.prune()
            return [signal for signal in self._signals.values() if self._is_signal_visible(signal)]


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
