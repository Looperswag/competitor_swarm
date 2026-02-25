"""Graph motif miner for emergence insights."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from src.environment import SignalGraphEdgeType, StigmergyEnvironment


@dataclass(frozen=True)
class _MotifCandidate:
    motif_type: str
    topic: str
    evidence_signal_ids: list[str]
    evidence_claim_ids: list[str]
    dimensions: list[str]
    phase_trace: list[str]
    tension: float
    novelty: float


class MotifMiner:
    """Mine convergence/tension/bridge motifs from signal and claim graph."""

    EMERGENCE_THRESHOLD = 0.62
    _TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}|[\u4e00-\u9fff]{2,}")
    _STOP_WORDS = {
        "this", "that", "with", "from", "have", "will", "would", "could", "should",
        "feature", "features", "product", "market", "analysis", "signal", "insight",
        "用户", "产品", "功能", "市场", "分析", "策略", "方面", "我们", "他们", "进行", "可能", "需要",
    }

    def __init__(self, environment: StigmergyEnvironment) -> None:
        self._environment = environment

    def mine(
        self,
        *,
        claims: list[dict[str, Any]] | None = None,
        limit: int = 5,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return (insights, traces)."""
        signals = list(self._environment.all_signals)
        if not signals:
            return [], []

        signal_by_id = {str(signal.id): signal for signal in signals}
        token_index = self._build_token_index(signals)
        claim_index, claim_sides = self._index_claims(claims or [])

        candidates: list[_MotifCandidate] = []
        candidates.extend(self._build_convergence(token_index, claim_index, claim_sides, signal_by_id))
        candidates.extend(self._build_tension(token_index, claim_index, claim_sides, signal_by_id))
        candidates.extend(self._build_bridge(signal_by_id, claim_index))

        if not candidates:
            return [], []

        deduped: dict[tuple[str, tuple[str, ...]], _MotifCandidate] = {}
        for candidate in candidates:
            key = (candidate.motif_type, tuple(sorted(candidate.evidence_signal_ids)))
            if key not in deduped:
                deduped[key] = candidate

        scored: list[tuple[_MotifCandidate, float, float]] = []
        for candidate in deduped.values():
            score, pheromone_score = self._score_candidate(candidate, signal_by_id)
            if score >= self.EMERGENCE_THRESHOLD:
                scored.append((candidate, score, pheromone_score))

        scored.sort(key=lambda item: item[1], reverse=True)
        selected = scored[: max(0, limit)]

        insights: list[dict[str, Any]] = []
        traces: list[dict[str, Any]] = []
        for idx, (candidate, score, pheromone_score) in enumerate(selected, start=1):
            trace_id = f"emg-{uuid4().hex[:12]}"
            content = self._format_content(candidate, score)
            strategic_value = "high" if score >= 0.78 else "medium"
            evidence_signal_ids = list(dict.fromkeys(candidate.evidence_signal_ids))
            evidence_claim_ids = list(dict.fromkeys(candidate.evidence_claim_ids))
            phase_trace = list(dict.fromkeys(candidate.phase_trace))

            insights.append(
                {
                    "content": content,
                    "description": content,
                    "dimensions": candidate.dimensions,
                    "strategic_value": strategic_value,
                    "motif_type": candidate.motif_type,
                    "score": round(score, 4),
                    "trace_id": trace_id,
                    "evidence_signal_ids": evidence_signal_ids,
                    "evidence_claim_ids": evidence_claim_ids,
                    "phase_trace": phase_trace,
                    "pheromone_score": round(pheromone_score, 4),
                    "rank": idx,
                }
            )
            traces.append(
                {
                    "trace_id": trace_id,
                    "motif_type": candidate.motif_type,
                    "signal_ids": evidence_signal_ids,
                    "claim_ids": evidence_claim_ids,
                    "phase_trace": phase_trace,
                    "score": round(score, 4),
                }
            )

        return insights, traces

    def _build_token_index(self, signals: list[Any]) -> dict[str, list[str]]:
        token_index: dict[str, list[str]] = defaultdict(list)
        for signal in signals:
            signal_id = str(getattr(signal, "id", "") or "")
            if not signal_id:
                continue
            tokens = self._tokenize(str(getattr(signal, "evidence", "") or ""))
            for token in tokens:
                token_index[token].append(signal_id)
        return token_index

    def _index_claims(
        self,
        claims: list[dict[str, Any]],
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        signal_to_claims: dict[str, list[str]] = defaultdict(list)
        claim_side: dict[str, str] = {}
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            claim_id = str(claim.get("claim_id") or "").strip()
            if not claim_id:
                continue
            side = str(claim.get("side") or "").strip().lower()
            if side not in {"red", "blue"}:
                side = "unknown"
            claim_side[claim_id] = side
            evidence_ids = claim.get("evidence_signal_ids")
            if not isinstance(evidence_ids, list):
                continue
            for signal_id in evidence_ids:
                sid = str(signal_id).strip()
                if sid:
                    signal_to_claims[sid].append(claim_id)
        return signal_to_claims, claim_side

    def _build_convergence(
        self,
        token_index: dict[str, list[str]],
        claim_index: dict[str, list[str]],
        claim_sides: dict[str, str],
        signal_by_id: dict[str, Any],
    ) -> list[_MotifCandidate]:
        candidates: list[_MotifCandidate] = []
        for token, signal_ids in token_index.items():
            unique_ids = list(dict.fromkeys(signal_ids))
            if len(unique_ids) < 3:
                continue
            agents = {
                str(getattr(signal_by_id[sid], "author_agent", "") or "")
                for sid in unique_ids
                if sid in signal_by_id
            }
            agents.discard("")
            if len(agents) < 3:
                continue

            selected_ids = self._top_signal_ids(unique_ids, signal_by_id, limit=5)
            claim_ids = self._collect_claim_ids(selected_ids, claim_index)
            dimensions = self._collect_dimensions(selected_ids, signal_by_id)
            red_count, blue_count = self._count_claim_sides(claim_ids, claim_sides)
            tension = self._tension_score(red_count, blue_count, default=0.15)
            novelty = self._topic_novelty(token, token_index)
            candidates.append(
                _MotifCandidate(
                    motif_type="Convergence",
                    topic=token,
                    evidence_signal_ids=selected_ids,
                    evidence_claim_ids=claim_ids,
                    dimensions=dimensions,
                    phase_trace=self._phase_trace(claim_ids),
                    tension=tension,
                    novelty=novelty,
                )
            )
        return candidates

    def _build_tension(
        self,
        token_index: dict[str, list[str]],
        claim_index: dict[str, list[str]],
        claim_sides: dict[str, str],
        signal_by_id: dict[str, Any],
    ) -> list[_MotifCandidate]:
        candidates: list[_MotifCandidate] = []
        for token, signal_ids in token_index.items():
            unique_ids = list(dict.fromkeys(signal_ids))
            if len(unique_ids) < 2:
                continue
            claim_ids = self._collect_claim_ids(unique_ids, claim_index)
            if len(claim_ids) < 2:
                continue
            red_count, blue_count = self._count_claim_sides(claim_ids, claim_sides)
            if red_count == 0 or blue_count == 0:
                continue
            selected_ids = self._top_signal_ids(unique_ids, signal_by_id, limit=4)
            dimensions = self._collect_dimensions(selected_ids, signal_by_id)
            candidates.append(
                _MotifCandidate(
                    motif_type="Tension",
                    topic=token,
                    evidence_signal_ids=selected_ids,
                    evidence_claim_ids=claim_ids[:8],
                    dimensions=dimensions,
                    phase_trace=self._phase_trace(claim_ids),
                    tension=self._tension_score(red_count, blue_count, default=0.6),
                    novelty=self._topic_novelty(token, token_index),
                )
            )
        return candidates

    def _build_bridge(
        self,
        signal_by_id: dict[str, Any],
        claim_index: dict[str, list[str]],
    ) -> list[_MotifCandidate]:
        candidates: list[_MotifCandidate] = []
        edges = self._environment.get_signal_graph_edges(
            edge_types={
                SignalGraphEdgeType.REFERENCE_EXPLICIT,
                SignalGraphEdgeType.SEMANTIC_LINK,
                SignalGraphEdgeType.DEBATE_SUPPORT,
                SignalGraphEdgeType.DEBATE_ATTACK,
            },
            min_weight=0.2,
            limit=800,
        )
        neighbors: dict[str, set[str]] = defaultdict(set)
        dimensions: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            src = str(edge.src)
            dst = str(edge.dst)
            neighbors[src].add(dst)
            neighbors[dst].add(src)

            src_signal = signal_by_id.get(src)
            dst_signal = signal_by_id.get(dst)
            if src_signal is not None and dst_signal is not None:
                src_dimension = str(getattr(src_signal, "dimension", "")).split(".")[-1].lower()
                dst_dimension = str(getattr(dst_signal, "dimension", "")).split(".")[-1].lower()
                if dst_dimension:
                    dimensions[src].add(dst_dimension)
                if src_dimension:
                    dimensions[dst].add(src_dimension)

        for signal_id, related_ids in neighbors.items():
            signal = signal_by_id.get(signal_id)
            if signal is None:
                continue
            bridge_dims = dimensions.get(signal_id, set())
            if len(bridge_dims) < 2 or len(related_ids) < 2:
                continue
            selected_ids = self._top_signal_ids([signal_id, *related_ids], signal_by_id, limit=5)
            claim_ids = self._collect_claim_ids(selected_ids, claim_index)
            candidates.append(
                _MotifCandidate(
                    motif_type="Bridge",
                    topic=self._top_topic_for_signal(signal),
                    evidence_signal_ids=selected_ids,
                    evidence_claim_ids=claim_ids[:6],
                    dimensions=sorted(bridge_dims)[:4],
                    phase_trace=self._phase_trace(claim_ids),
                    tension=0.25,
                    novelty=0.55,
                )
            )
        return candidates

    def _score_candidate(
        self,
        candidate: _MotifCandidate,
        signal_by_id: dict[str, Any],
    ) -> tuple[float, float]:
        signal_ids = [sid for sid in candidate.evidence_signal_ids if sid in signal_by_id]
        if not signal_ids:
            return 0.0, 0.0

        agent_entropy = self._cross_agent_entropy(signal_ids, signal_by_id)
        pheromone_values = [
            self._environment.get_signal_pheromone_value(signal_id)
            for signal_id in signal_ids
        ]
        evidence_strength = sum(pheromone_values) / len(pheromone_values) if pheromone_values else 0.0
        temporal_persistence = self._temporal_persistence(signal_ids, signal_by_id)

        score = (
            0.30 * agent_entropy
            + 0.25 * evidence_strength
            + 0.20 * candidate.tension
            + 0.15 * temporal_persistence
            + 0.10 * candidate.novelty
        )
        return max(0.0, min(1.0, score)), evidence_strength

    def _collect_claim_ids(
        self,
        signal_ids: list[str],
        claim_index: dict[str, list[str]],
    ) -> list[str]:
        result: list[str] = []
        for signal_id in signal_ids:
            result.extend(claim_index.get(signal_id, []))
        return list(dict.fromkeys(result))

    def _collect_dimensions(self, signal_ids: list[str], signal_by_id: dict[str, Any]) -> list[str]:
        dimensions = {
            str(getattr(signal_by_id[sid], "dimension", "")).split(".")[-1].lower()
            for sid in signal_ids
            if sid in signal_by_id
        }
        dimensions.discard("")
        return sorted(dimensions)

    def _top_signal_ids(
        self,
        signal_ids: list[str],
        signal_by_id: dict[str, Any],
        *,
        limit: int,
    ) -> list[str]:
        unique_ids = [sid for sid in dict.fromkeys(signal_ids) if sid in signal_by_id]
        unique_ids.sort(
            key=lambda sid: self._environment.get_signal_pheromone_value(sid),
            reverse=True,
        )
        return unique_ids[: max(0, limit)]

    def _count_claim_sides(self, claim_ids: list[str], claim_sides: dict[str, str]) -> tuple[int, int]:
        red_count = 0
        blue_count = 0
        for claim_id in claim_ids:
            side = claim_sides.get(claim_id)
            if side == "red":
                red_count += 1
            elif side == "blue":
                blue_count += 1
        return red_count, blue_count

    def _tension_score(self, red_count: int, blue_count: int, *, default: float) -> float:
        total = red_count + blue_count
        if total <= 0:
            return default
        balance = 1.0 - abs(red_count - blue_count) / total
        return max(0.0, min(1.0, balance))

    def _phase_trace(self, claim_ids: list[str]) -> list[str]:
        trace = ["collection", "validation"]
        if claim_ids:
            trace.append("debate")
        trace.append("synthesis")
        return trace

    def _cross_agent_entropy(self, signal_ids: list[str], signal_by_id: dict[str, Any]) -> float:
        counts: Counter[str] = Counter()
        for signal_id in signal_ids:
            signal = signal_by_id.get(signal_id)
            if signal is None:
                continue
            agent = str(getattr(signal, "author_agent", "") or "")
            if agent:
                counts[agent] += 1
        if not counts:
            return 0.0
        total = sum(counts.values())
        entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
        max_entropy = math.log(len(counts)) if len(counts) > 1 else 1.0
        return entropy / max_entropy if max_entropy > 0 else 0.0

    def _temporal_persistence(self, signal_ids: list[str], signal_by_id: dict[str, Any]) -> float:
        timestamps: list[datetime] = []
        for signal_id in signal_ids:
            signal = signal_by_id.get(signal_id)
            if signal is None:
                continue
            ts = getattr(signal, "timestamp", "")
            if not ts:
                continue
            try:
                timestamps.append(datetime.fromisoformat(str(ts)))
            except ValueError:
                continue
        if len(timestamps) <= 1:
            return 0.3
        span_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600.0
        return max(0.0, min(1.0, span_hours / 24.0))

    def _topic_novelty(self, topic: str, token_index: dict[str, list[str]]) -> float:
        if not topic:
            return 0.5
        frequencies = [len(items) for items in token_index.values()]
        if not frequencies:
            return 0.5
        max_frequency = max(frequencies)
        topic_frequency = len(token_index.get(topic, []))
        if max_frequency <= 0:
            return 0.5
        novelty = 1.0 - (topic_frequency / max_frequency)
        return max(0.0, min(1.0, novelty))

    def _top_topic_for_signal(self, signal: Any) -> str:
        tokens = self._tokenize(str(getattr(signal, "evidence", "") or ""))
        if not tokens:
            return "cross-dimension"
        return tokens[0]

    def _tokenize(self, text: str) -> list[str]:
        if not text:
            return []
        tokens = []
        for token in self._TOKEN_PATTERN.findall(text.lower()):
            normalized = token.strip()
            if not normalized or normalized in self._STOP_WORDS:
                continue
            tokens.append(normalized)
        return tokens[:20]

    def _format_content(self, candidate: _MotifCandidate, score: float) -> str:
        topic = candidate.topic or "关键主题"
        if candidate.motif_type == "Convergence":
            return (
                f"多个 Agent 在「{topic}」上形成收敛证据，显示该主题已成为跨维度共识。"
                f"（emergence_score={score:.2f}）"
            )
        if candidate.motif_type == "Tension":
            return (
                f"围绕「{topic}」同时出现高强度机会与威胁，说明该主题存在显著战略张力。"
                f"（emergence_score={score:.2f}）"
            )
        return (
            f"「{topic}」信号连接多个维度并影响辩论走向，是关键桥接节点。"
            f"（emergence_score={score:.2f}）"
        )
