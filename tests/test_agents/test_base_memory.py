"""Base memory mixin tests."""

from unittest.mock import MagicMock

import pytest

from src.agents.base import AgentResult, AgentType, BaseAgent, SIGNALS_AVAILABLE
from src.environment import DiscoverySource


class MemoryAgent(BaseAgent):
    def execute(self, **context):
        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[],
            handoffs_created=0,
            metadata={},
        )


def test_add_discovery_and_handoff(mock_llm_client, empty_environment):
    from src.handoff import HandoffContext, HandoffManager

    manager = HandoffManager()
    agent = MemoryAgent(
        agent_type=AgentType.SCOUT,
        name="memory",
        llm_client=mock_llm_client,
        environment=empty_environment,
        handoff_manager=manager,
        search_tool=object(),
    )

    discovery = agent.add_discovery(
        content="found x",
        source=DiscoverySource.ANALYSIS,
        quality_score=0.7,
        metadata={"target": "Notion"},
    )

    assert discovery.content == "found x"

    ctx = HandoffContext(reasoning="need technical")
    agent.create_handoff("technical", ctx)
    pending = agent.get_pending_handoffs()
    assert len(pending) == 0


def test_signal_query_methods_delegate_environment(mock_llm_client):
    env = MagicMock()
    env.get_signals_by_dimension.return_value = ["a"]
    env.get_signals_by_type.return_value = ["b"]
    env.get_related_signals.return_value = ["c"]
    env.get_fresh_signals.return_value = ["d"]

    agent = MemoryAgent(
        agent_type=AgentType.SCOUT,
        name="memory",
        llm_client=mock_llm_client,
        environment=env,
        search_tool=object(),
    )

    assert agent.get_signals_by_dimension("product") == ["a"]
    assert agent.get_signals_by_type("insight") == ["b"]
    assert agent.get_related_signals("id") == ["c"]
    assert agent.get_fresh_signals() == ["d"]


@pytest.mark.skipif(not SIGNALS_AVAILABLE, reason="Signal schema not available")
def test_emit_signal_can_sync_to_discovery_when_compat_enabled(mock_llm_client, empty_environment, monkeypatch):
    from src.schemas.signals import SignalType

    monkeypatch.setenv("COMPETITOR_SWARM_SYNC_DISCOVERY_COMPAT", "1")

    agent = MemoryAgent(
        agent_type=AgentType.SCOUT,
        name="memory",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    signal = agent.emit_signal(
        signal_type=SignalType.INSIGHT,
        evidence="signal evidence",
        confidence=0.8,
        strength=0.7,
    )

    assert signal is not None
    assert empty_environment.signal_count == 1
    assert empty_environment.discovery_count == 1
