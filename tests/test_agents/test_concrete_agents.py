"""Concrete agent execution-path tests for stability and coverage."""

import asyncio
from unittest.mock import patch

import pytest

from src.agents.blue_team import BlueTeamAgent
from src.agents.elite import EliteAgent, NormalizedDiscovery
from src.agents.experience import ExperienceAgent
from src.agents.market import MarketAgent
from src.agents.red_team import RedTeamAgent
from src.agents.scout import ScoutAgent
from src.agents.technical import TechnicalAgent
from src.environment import DiscoverySource


@pytest.mark.parametrize(
    "agent_cls",
    [ScoutAgent, ExperienceAgent, TechnicalAgent, MarketAgent, RedTeamAgent, BlueTeamAgent, EliteAgent],
)
def test_agents_return_error_metadata_when_target_missing(agent_cls, mock_llm_client, empty_environment):
    agent = agent_cls(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    result = agent.execute()
    assert result.discoveries == []
    assert result.metadata
    assert result.metadata.get("error") == "No target specified"


def test_scout_execute_and_async_happy_path(mock_llm_client, empty_environment):
    agent = ScoutAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    agent.USE_SIGNALS = False

    with patch.object(agent, "_get_search_context", return_value=""), \
        patch.object(agent, "_parse_and_store_discoveries", return_value=[{"content": "d1"}]), \
        patch.object(agent, "_ensure_min_discoveries", side_effect=lambda d, *_: d), \
        patch.object(agent, "_ensure_min_discoveries_async", side_effect=lambda d, *_: d), \
        patch.object(agent, "_check_for_handoffs", return_value=0), \
        patch.object(agent, "think", return_value="ok"), \
        patch.object(agent, "think_async", return_value="ok"):
        sync_result = agent.execute(target="Notion", competitors=["Feishu"])
        async_result = asyncio.run(agent.execute_async(target="Notion", competitors=["Feishu"]))

    assert sync_result.discoveries
    assert async_result.discoveries


def test_experience_execute_and_async_happy_path(mock_llm_client, empty_environment):
    agent = ExperienceAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    agent.USE_SIGNALS = False

    with patch.object(agent, "_get_search_context", return_value=""), \
        patch.object(agent, "_parse_and_store_discoveries", return_value=[{"content": "ux"}]), \
        patch.object(agent, "_ensure_min_discoveries", side_effect=lambda d, *_: d), \
        patch.object(agent, "_ensure_min_discoveries_async", side_effect=lambda d, *_: d), \
        patch.object(agent, "think_with_discoveries", return_value="ok"), \
        patch.object(agent, "think_with_discoveries_async", return_value="ok"):
        sync_result = agent.execute(target="Notion")
        async_result = asyncio.run(agent.execute_async(target="Notion"))

    assert sync_result.discoveries
    assert async_result.discoveries


def test_technical_execute_and_async_happy_path(mock_llm_client, empty_environment):
    agent = TechnicalAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    agent.USE_SIGNALS = False

    with patch.object(agent, "_get_search_context", return_value=""), \
        patch.object(agent, "_parse_and_store_discoveries", return_value=[{"content": "tech"}]), \
        patch.object(agent, "_ensure_min_discoveries", side_effect=lambda d, *_: d), \
        patch.object(agent, "_ensure_min_discoveries_async", side_effect=lambda d, *_: d), \
        patch.object(agent, "think_with_discoveries", return_value="ok"), \
        patch.object(agent, "think_with_discoveries_async", return_value="ok"):
        sync_result = agent.execute(target="Notion", _handoff={"reasoning": "focus API"})
        async_result = asyncio.run(agent.execute_async(target="Notion", _handoff={"reasoning": "focus API"}))

    assert sync_result.discoveries
    assert async_result.discoveries


def test_market_execute_and_async_happy_path(mock_llm_client, empty_environment):
    agent = MarketAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    agent.USE_SIGNALS = False

    with patch.object(agent, "_get_search_context", return_value=""), \
        patch.object(agent, "_parse_and_store_discoveries", return_value=[{"content": "market"}]), \
        patch.object(agent, "_ensure_min_discoveries", side_effect=lambda d, *_: d), \
        patch.object(agent, "_ensure_min_discoveries_async", side_effect=lambda d, *_: d), \
        patch.object(agent, "think_with_discoveries", return_value="ok"), \
        patch.object(agent, "think_with_discoveries_async", return_value="ok"):
        sync_result = agent.execute(target="Notion", competitors=["A"])
        async_result = asyncio.run(agent.execute_async(target="Notion", competitors=["A"]))

    assert sync_result.discoveries
    assert async_result.discoveries


def test_red_blue_execute_and_async_happy_path(mock_llm_client, empty_environment):
    red = RedTeamAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    blue = BlueTeamAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    red_discovery = empty_environment.add_discovery(
        agent_type="red_team",
        content="Critical issue for enterprise rollout",
        source=DiscoverySource.DEBATE,
        quality_score=0.8,
    )
    blue_discovery = empty_environment.add_discovery(
        agent_type="blue_team",
        content="Strong moat from collaboration ecosystem",
        source=DiscoverySource.DEBATE,
        quality_score=0.8,
    )

    for agent, discovery in [(red, red_discovery), (blue, blue_discovery)]:
        with patch.object(agent, "_get_search_context", return_value=""), \
            patch.object(agent, "_parse_and_store_discoveries", return_value=[discovery]), \
            patch.object(agent, "_ensure_min_discoveries", side_effect=lambda d, *_: d), \
            patch.object(agent, "_ensure_min_discoveries_async", side_effect=lambda d, *_: d), \
            patch.object(agent, "think_with_discoveries", return_value="ok"), \
            patch.object(agent, "think_with_discoveries_async", return_value="ok"):
            sync_result = agent.execute(target="Notion")
            async_result = asyncio.run(agent.execute_async(target="Notion"))

        assert sync_result.discoveries
        assert async_result.discoveries


def test_elite_execute_happy_path(mock_llm_client, empty_environment):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    output_discovery = empty_environment.add_discovery(
        agent_type="elite",
        content="Executive synthesis with clear actionability",
        source=DiscoverySource.ANALYSIS,
        quality_score=0.9,
    )

    with patch.object(agent, "_get_search_context", return_value=""), \
        patch.object(agent, "_collect_all_discoveries", return_value=[
            NormalizedDiscovery(
                id="test-market-1",
                agent_type="market",
                content="pricing pressure",
                quality_score=0.7,
                metadata={},
            )
        ]), \
        patch.object(
            agent,
            "_generate_report_and_recommendations",
            return_value=({"summary": "s"}, [{"title": "r"}]),
        ), \
        patch.object(
            agent,
            "_extract_emergent_insights",
            return_value=([{"content": "i"}], [{"trace_id": "emg-1"}]),
        ), \
        patch.object(agent, "_store_elite_discoveries", return_value=[output_discovery]):
        result = agent.execute(target="Notion")

    assert result.discoveries
    assert result.metadata
    assert result.metadata["report"]["summary"] == "s"
