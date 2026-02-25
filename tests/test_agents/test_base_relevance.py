"""Base relevance mixin tests."""

from unittest.mock import MagicMock

from src.agents.base import AgentResult, AgentType, BaseAgent
from src.environment import DiscoverySource
from src.llm import LLMResponse


class RelevanceAgent(BaseAgent):
    def execute(self, **context):
        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[],
            handoffs_created=0,
            metadata={},
        )


def _seed(env):
    env.add_discovery(
        agent_type="scout",
        content="Notion offers team collaboration templates",
        source=DiscoverySource.ANALYSIS,
        quality_score=0.8,
    )
    env.add_discovery(
        agent_type="market",
        content="Notion pricing is higher than some alternatives",
        source=DiscoverySource.ANALYSIS,
        quality_score=0.7,
    )


def test_find_relevant_discoveries_excludes_own(mock_llm_client, empty_environment):
    _seed(empty_environment)
    empty_environment.add_discovery(
        agent_type="scout",
        content="own discovery should be filtered",
        source=DiscoverySource.ANALYSIS,
        quality_score=0.2,
    )

    agent = RelevanceAgent(
        agent_type=AgentType.SCOUT,
        name="rel",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    results = agent.find_relevant_discoveries("pricing", exclude_own=True, limit=5)
    assert results
    assert all(item.agent_type != "scout" for item in results)


def test_parse_relevance_response_uses_json_scores(mock_llm_client, empty_environment):
    _seed(empty_environment)
    agent = RelevanceAgent(
        agent_type=AgentType.MARKET,
        name="rel",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    discovery_list = empty_environment.all_discoveries
    scored = agent._parse_relevance_response(
        '[{"index": 1, "score": 0.9}]',
        discovery_list,
    )
    assert scored[0][0] == discovery_list[1]
    assert scored[0][1] == 0.9


def test_evaluate_relevance_batch_falls_back_on_exception(mock_llm_client, empty_environment):
    _seed(empty_environment)
    mock_llm_client.chat.side_effect = RuntimeError("llm down")

    agent = RelevanceAgent(
        agent_type=AgentType.MARKET,
        name="rel",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    scored = agent._evaluate_relevance_batch("pricing", empty_environment.all_discoveries)
    assert len(scored) == len(empty_environment.all_discoveries)


def test_fallback_text_matching_boosts_query_hit(mock_llm_client, empty_environment):
    _seed(empty_environment)
    agent = RelevanceAgent(
        agent_type=AgentType.MARKET,
        name="rel",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    scored = agent._fallback_text_matching("pricing", empty_environment.all_discoveries)
    boosted = [score for discovery, score in scored if "pricing" in discovery.content.lower()]
    assert boosted and boosted[0] >= 0.7
