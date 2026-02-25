"""Base thinking mixin tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base import AgentResult, AgentType, BaseAgent, SIGNALS_AVAILABLE
from src.llm import LLMResponse


class ThinkingAgent(BaseAgent):
    def execute(self, **context):
        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[],
            handoffs_created=0,
            metadata={},
        )


def test_think_records_empty_output_warning(mock_llm_client, empty_environment):
    mock_llm_client.chat.return_value = LLMResponse(
        content="",
        model="glm-4.7",
        input_tokens=1,
        output_tokens=0,
        total_tokens=1,
        thinking_content=None,
    )
    agent = ThinkingAgent(
        agent_type=AgentType.SCOUT,
        name="thinking",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    response = agent.think("analyze")
    assert response == ""
    metadata = agent._augment_metadata({})
    assert metadata["error_type"] == "EMPTY_OUTPUT"
    assert metadata["warnings"][0]["error_type"] == "EMPTY_OUTPUT"


@pytest.mark.asyncio
async def test_think_async_records_empty_output_warning(mock_llm_client, empty_environment):
    mock_llm_client.chat_async = AsyncMock(
        return_value=LLMResponse(
            content="   ",
            model="glm-4.7",
            input_tokens=1,
            output_tokens=0,
            total_tokens=1,
            thinking_content=None,
        )
    )
    agent = ThinkingAgent(
        agent_type=AgentType.SCOUT,
        name="thinking",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    response = await agent.think_async("analyze")
    assert response.strip() == ""
    metadata = agent._augment_metadata({})
    assert metadata["error_type"] == "EMPTY_OUTPUT"


def test_format_context_includes_internal_sections(mock_llm_client, empty_environment):
    agent = ThinkingAgent(
        agent_type=AgentType.SCOUT,
        name="thinking",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    text = agent._format_context(
        {
            "target": "Notion",
            "_discoveries": "d1",
            "_signals": "s1",
            "_handoff": {"reasoning": "r1"},
            "_search_context": "web1",
        }
    )

    assert "target: Notion" in text
    assert "Previous Discoveries" in text
    assert "Previous Signals" in text
    assert "Handoff Context" in text
    assert "Web Search Results" in text


def test_think_with_discoveries_prefers_signals_route(mock_llm_client):
    if not SIGNALS_AVAILABLE:
        pytest.skip("Signal schema not available")

    env = MagicMock()
    env.signal_count = 1

    agent = ThinkingAgent(
        agent_type=AgentType.SCOUT,
        name="thinking",
        llm_client=mock_llm_client,
        environment=env,
        search_tool=object(),
    )

    with patch.object(agent, "think_with_signals", return_value="signal-path") as mocked:
        output = agent.think_with_discoveries("foo", agent_types=["scout"], context={})

    assert output == "signal-path"
    mocked.assert_called_once()
