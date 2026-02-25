"""Base runtime mixin tests."""

from unittest.mock import patch

from src.agents.base import AgentResult, AgentType, BaseAgent


class RuntimeAgent(BaseAgent):
    def execute(self, **context):
        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[],
            handoffs_created=0,
            metadata=self._augment_metadata({"ok": True}),
        )


def test_runtime_augment_metadata_contains_run_and_warnings(mock_llm_client, empty_environment):
    empty_environment.begin_run(run_id="run-rt", clear=True)
    agent = RuntimeAgent(
        agent_type=AgentType.SCOUT,
        name="runtime",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    agent._record_runtime_warning(
        message="search degraded",
        error_type="SEARCH_FAILURE",
        recoverable=True,
        hint="check provider",
        retry_count=2,
    )

    metadata = agent._augment_metadata({"foo": "bar"})
    assert metadata["foo"] == "bar"
    assert metadata["run_id"] == "run-rt"
    assert metadata["error_type"] == "SEARCH_FAILURE"
    assert metadata["retry_count"] == 2
    assert metadata["warnings"][0]["message"] == "search degraded"


def test_runtime_reset_diagnostics(mock_llm_client, empty_environment):
    agent = RuntimeAgent(
        agent_type=AgentType.SCOUT,
        name="runtime",
        llm_client=mock_llm_client,
        environment=empty_environment,
        search_tool=object(),
    )

    agent._record_runtime_warning(
        message="x",
        error_type="PARSE_FAILURE",
        recoverable=True,
        hint="h",
        retry_count=1,
    )
    agent._reset_runtime_diagnostics()

    metadata = agent._augment_metadata({})
    assert "warnings" not in metadata
    assert "error_type" not in metadata
    assert "retry_count" not in metadata


def test_runtime_reads_config_via_base_patch_hook(mock_llm_client, sample_config):
    with patch("src.agents.base.get_config", return_value=sample_config):
        agent = RuntimeAgent(
            agent_type=AgentType.SCOUT,
            name="runtime",
            llm_client=mock_llm_client,
            search_tool=object(),
        )

    assert agent.system_prompt
    assert agent.MIN_DISCOVERIES == sample_config.agents.scout.min_discoveries
