"""Base search mixin tests."""

import concurrent.futures
import time
from unittest.mock import patch

from src.agents.base import AgentResult, AgentType, BaseAgent


class SearchAgent(BaseAgent):
    def execute(self, **context):
        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[],
            handoffs_created=0,
            metadata={},
        )


class _Result:
    def __init__(self, title: str):
        self.title = title
        self.site_name = "site"
        self.summary = "summary"
        self.url = "https://example.com"


def test_search_context_without_tool_records_warning(mock_llm_client, empty_environment):
    agent = SearchAgent(
        agent_type=AgentType.SCOUT,
        name="search",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )
    agent._search_tool = None

    text = agent.search_context("notion")
    assert text == ""
    metadata = agent._augment_metadata({})
    assert metadata["error_type"] == "SEARCH_FAILURE"


def test_search_context_timeout_records_timeout_warning(mock_llm_client, empty_environment):
    class SlowTool:
        def search(self, **kwargs):
            time.sleep(0.05)
            return [_Result("x")]

    agent = SearchAgent(
        agent_type=AgentType.SCOUT,
        name="search",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=SlowTool(),
    )

    text = agent.search_context("notion", timeout=0.001)
    assert text == ""
    metadata = agent._augment_metadata({})
    assert metadata["error_type"] == "UPSTREAM_TIMEOUT"


def test_search_context_formats_results(mock_llm_client, empty_environment):
    class Tool:
        def search(self, **kwargs):
            return [_Result("Notion pricing")]

    agent = SearchAgent(
        agent_type=AgentType.SCOUT,
        name="search",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=Tool(),
    )

    text = agent.search_context("notion")
    assert "Notion pricing" in text
    assert "来源" in text


def test_search_context_async_handles_timeout_gracefully(mock_llm_client, empty_environment):
    class Tool:
        def search(self, **kwargs):
            return [_Result("ok")]

    agent = SearchAgent(
        agent_type=AgentType.SCOUT,
        name="search",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=Tool(),
    )

    with patch("src.agents.base_search.concurrent.futures.as_completed", side_effect=concurrent.futures.TimeoutError):
        result = agent.search_context_async(["q1", "q2"], timeout=0.01)

    assert isinstance(result, dict)
    metadata = agent._augment_metadata({})
    assert metadata["error_type"] == "UPSTREAM_TIMEOUT"
