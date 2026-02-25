"""Memory/discovery/signal/handoff mixin for BaseAgent."""

from __future__ import annotations

from typing import Any

from src.agents.base_types import SIGNALS_AVAILABLE
from src.environment import Discovery, DiscoverySource
from src.handoff import HandoffContext, HandoffPriority


class BaseAgentMemoryMixin:
    """Shared memory and handoff methods."""

    def add_discovery(
        self,
        content: str,
        source: DiscoverySource,
        quality_score: float = 0.5,
        references: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Discovery:
        return self._environment.add_discovery(
            agent_type=self.agent_type.value,
            content=content,
            source=source,
            quality_score=quality_score,
            references=references,
            metadata=metadata or {},
        )

    def emit_signal(
        self,
        signal_type: Any,
        evidence: str,
        confidence: float = 0.5,
        strength: float = 0.5,
        sentiment: Any = None,
        tags: list[str] | None = None,
        source: str = "",
        references: list[str] | None = None,
        actionability: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any | None:
        if not SIGNALS_AVAILABLE or not self.USE_SIGNALS:
            return None

        from src.schemas.signals import Actionability, Sentiment, Signal

        signal = Signal(
            id="",
            signal_type=signal_type,
            dimension=self._dimension,
            evidence=evidence,
            confidence=confidence,
            strength=strength,
            sentiment=sentiment or Sentiment.NEUTRAL,
            tags=tags or [],
            source=source,
            timestamp="",
            references=references or [],
            author_agent=self.agent_type.value,
            verified=False,
            debate_points=[],
            actionability=actionability or Actionability.INFORMATIONAL,
            metadata=metadata or {},
        )

        stored_signal = self._environment.add_signal(signal)

        if self._sync_discovery_compat:
            try:
                if evidence:
                    discovery_metadata = {
                        "signal_id": stored_signal.id,
                        "signal_type": stored_signal.signal_type.value
                        if hasattr(stored_signal, "signal_type") else "",
                        "signal_source": source,
                        **(metadata or {}),
                    }
                    self.add_discovery(
                        content=evidence,
                        source=DiscoverySource.ANALYSIS,
                        quality_score=confidence,
                        references=stored_signal.references,
                        metadata=discovery_metadata,
                    )
            except Exception:
                pass

        return stored_signal

    def get_signals_by_dimension(
        self,
        dimension: Any,
        min_confidence: float = 0.0,
        min_strength: float = 0.0,
        verified_only: bool = False,
        limit: int = 50,
    ) -> list[Any]:
        if not SIGNALS_AVAILABLE:
            return []
        return self._environment.get_signals_by_dimension(
            dimension=dimension,
            min_confidence=min_confidence,
            min_strength=min_strength,
            verified_only=verified_only,
            limit=limit,
        )

    def get_signals_by_type(
        self,
        signal_type: Any,
        min_strength: float = 0.0,
        verified_only: bool = False,
        limit: int = 50,
    ) -> list[Any]:
        if not SIGNALS_AVAILABLE:
            return []
        return self._environment.get_signals_by_type(
            signal_type=signal_type,
            min_strength=min_strength,
            verified_only=verified_only,
            limit=limit,
        )

    def get_related_signals(
        self,
        signal_id: str,
        max_distance: int = 2,
        limit: int = 20,
    ) -> list[Any]:
        if not SIGNALS_AVAILABLE:
            return []
        return self._environment.get_related_signals(
            signal_id=signal_id,
            max_distance=max_distance,
            limit=limit,
        )

    def get_fresh_signals(
        self,
        max_age_hours: int = 24,
        limit: int = 50,
    ) -> list[Any]:
        if not SIGNALS_AVAILABLE:
            return []
        return self._environment.get_fresh_signals(
            max_age_hours=max_age_hours,
            limit=limit,
        )

    def create_handoff(
        self,
        to_agent: str,
        context: HandoffContext,
        priority: HandoffPriority = HandoffPriority.MEDIUM,
    ) -> None:
        self._handoff_manager.create_handoff(
            from_agent=self.agent_type.value,
            to_agent=to_agent,
            context=context,
            priority=priority,
        )

    def get_pending_handoffs(self) -> list[HandoffContext]:
        return self._handoff_manager.get_context_for_agent(self.agent_type.value)
