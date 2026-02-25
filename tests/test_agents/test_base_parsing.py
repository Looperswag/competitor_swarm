"""Base parsing mixin tests."""

from unittest.mock import patch

from src.agents.base import AgentResult, AgentType, BaseAgent
from src.environment import DiscoverySource


class ParsingAgent(BaseAgent):
    def execute(self, **context):
        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[],
            handoffs_created=0,
            metadata={},
        )


def test_parse_json_discoveries_success(mock_llm_client, empty_environment):
    agent = ParsingAgent(
        agent_type=AgentType.SCOUT,
        name="parsing",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    payload = """```json
    [{"content": "Notion uses subscription pricing", "quality_score": 0.8}]
    ```"""

    discoveries = agent._parse_and_store_discoveries_from_text(
        payload,
        "Notion",
        DiscoverySource.WEBSITE,
    )

    assert len(discoveries) == 1
    assert discoveries[0].content.startswith("Notion uses")


def test_parse_list_discoveries_success(mock_llm_client, empty_environment):
    agent = ParsingAgent(
        agent_type=AgentType.SCOUT,
        name="parsing",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    text = """
- 第一条有效发现：Notion 支持团队协作
- 第二条有效发现：提供模板市场和 API
- 第三条有效发现：企业版提供权限控制
"""

    discoveries = agent._parse_and_store_discoveries_from_text(text, "Notion")
    assert len(discoveries) >= 3


def test_parse_fallback_when_all_strategies_fail(mock_llm_client, empty_environment):
    agent = ParsingAgent(
        agent_type=AgentType.SCOUT,
        name="parsing",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    discoveries = agent._parse_and_store_discoveries_from_text("???", "Notion")
    assert len(discoveries) == 1
    assert discoveries[0].metadata.get("parse_fallback") is True

    metadata = agent._augment_metadata({})
    assert metadata["error_type"] == "PARSE_FAILURE"


def test_ensure_min_discoveries_caps_to_max(mock_llm_client, empty_environment):
    agent = ParsingAgent(
        agent_type=AgentType.SCOUT,
        name="parsing",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )
    agent.MIN_DISCOVERIES = 3
    agent.TARGET_DISCOVERIES = 8
    agent.MAX_DISCOVERIES = 4

    with patch.object(agent, "think_with_discoveries", return_value=""):
        seeded = [
            agent.add_discovery("已有发现一：内容足够长", DiscoverySource.ANALYSIS),
            agent.add_discovery("已有发现二：内容足够长", DiscoverySource.ANALYSIS),
            agent.add_discovery("已有发现三：内容足够长", DiscoverySource.ANALYSIS),
        ]
        out = agent._ensure_min_discoveries(seeded, "Notion", {})

    assert len(out) <= 4


def test_ensure_min_signals_parser_failure_records_warning(mock_llm_client, empty_environment):
    agent = ParsingAgent(
        agent_type=AgentType.SCOUT,
        name="parsing",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    agent.MIN_DISCOVERIES = 2
    agent.TARGET_DISCOVERIES = 3

    with patch.object(agent, "think_with_signals", return_value="x"):
        with patch.object(agent, "_parse_and_store_signals", side_effect=ValueError("bad parser"), create=True):
            out = agent._ensure_min_signals([], "Notion", {})

    assert out == []
    metadata = agent._augment_metadata({})
    assert metadata["error_type"] == "PARSE_FAILURE"
