"""Coordinator 执行链路测试。"""

import logging
from typing import Any

import pytest

from src.agents.base import AgentResult
from src.coordinator import Coordinator
from src.core.phase_executor import Phase, PhaseProgress


def _build_agent_result(agent_type: str, content: str) -> AgentResult:
    return AgentResult(
        agent_type=agent_type,
        agent_name=agent_type,
        discoveries=[{"content": content}],
        handoffs_created=0,
    )


def test_analyze_flattens_phase_executor_output(monkeypatch, empty_environment):
    """analyze 应整合四阶段结果并保留错误上下文。"""
    search_tool = object()
    captured_execute_kwargs: dict[str, Any] = {}

    progress = PhaseProgress(
        current_phase=Phase.SYNTHESIS,
        completed_phases=[Phase.COLLECTION, Phase.VALIDATION, Phase.DEBATE, Phase.SYNTHESIS],
        total_duration=1.23,
        agent_results={
            Phase.COLLECTION: [_build_agent_result("scout", "scout finding")],
            Phase.DEBATE: [_build_agent_result("red_team", "red finding")],
            Phase.SYNTHESIS: [_build_agent_result("elite", "elite finding")],
        },
        phase_errors={Phase.DEBATE: ["red_team: weak evidence"]},
    )

    class _FakeExecutor:
        def execute(self, **kwargs):
            captured_execute_kwargs.update(kwargs)
            return progress

    monkeypatch.setattr("src.coordinator.create_phase_executor", lambda **_: _FakeExecutor())

    coordinator = Coordinator(environment=empty_environment, search_tool=search_tool)
    result = coordinator.analyze(target="Notion")

    assert result.success is True
    assert result.metadata["execution_mode"] == "phase_executor"
    assert result.metadata["run_id"] == empty_environment.current_run_id
    assert result.metadata["completed_phases"] == ["collection", "validation", "debate", "synthesis"]
    assert set(result.agent_results.keys()) >= {"scout", "red_team", "elite"}

    assert len(result.errors) == 1
    first_error = result.errors[0]
    assert first_error["phase"] == "debate"
    assert first_error["agent_type"] == "red_team"
    assert first_error["error"] == "weak evidence"
    assert first_error["error_type"] == "UNKNOWN"
    assert first_error["recoverable"] is True
    assert first_error["run_id"] == result.metadata["run_id"]
    assert first_error["hint"]

    assert captured_execute_kwargs["target"] == "Notion"
    assert captured_execute_kwargs["search_tool"] is search_tool


def test_analyze_phase_callbacks_follow_four_phase_progress(monkeypatch, empty_environment):
    """四阶段进度应映射为信息收集/交叉验证/红蓝队对抗/报告综合。"""
    starts: list[str] = []
    completes: list[tuple[str, int]] = []
    started_agents: list[str] = []

    class _FakeExecutor:
        def __init__(self, progress_callback, on_agent_start):
            self._progress_callback = progress_callback
            self._on_agent_start = on_agent_start

        def execute(self, **kwargs):
            if self._on_agent_start:
                self._on_agent_start("侦察专家")
            self._progress_callback(PhaseProgress(current_phase=Phase.COLLECTION))
            self._progress_callback(PhaseProgress(current_phase=Phase.VALIDATION))
            self._progress_callback(PhaseProgress(current_phase=Phase.DEBATE))
            self._progress_callback(PhaseProgress(current_phase=Phase.SYNTHESIS))
            return PhaseProgress(
                current_phase=Phase.SYNTHESIS,
                completed_phases=[Phase.COLLECTION, Phase.VALIDATION, Phase.DEBATE, Phase.SYNTHESIS],
                total_duration=0.42,
                agent_results={Phase.COLLECTION: [_build_agent_result("scout", "finding")]},
            )

    def _fake_factory(**kwargs):
        return _FakeExecutor(
            progress_callback=kwargs["progress_callback"],
            on_agent_start=kwargs["on_agent_start"],
        )

    monkeypatch.setattr("src.coordinator.create_phase_executor", _fake_factory)

    coordinator = Coordinator(
        environment=empty_environment,
        search_tool=object(),
        on_phase_start=lambda phase_name: starts.append(phase_name),
        on_phase_complete=lambda phase_name, delta: completes.append((phase_name, delta)),
        on_agent_start=lambda agent_name: started_agents.append(agent_name),
    )

    result = coordinator.analyze(target="Notion")

    assert result.success is True
    assert starts == ["信息收集", "交叉验证", "红蓝队对抗", "报告综合"]
    assert completes == [("信息收集", 30), ("交叉验证", 20), ("红蓝队对抗", 30), ("报告综合", 20)]
    assert started_agents == ["侦察专家"]


def test_analyze_raises_when_phase_executor_fails(monkeypatch, empty_environment):
    """主链路异常时应直接向上抛出，避免双实现分叉。"""
    def _raise_executor_error(self, **kwargs):
        raise RuntimeError("phase executor crashed")

    monkeypatch.setattr(Coordinator, "_analyze_with_phase_executor", _raise_executor_error)

    coordinator = Coordinator(environment=empty_environment, search_tool=object())
    with pytest.raises(RuntimeError, match="phase executor crashed"):
        coordinator.analyze(target="Notion")


def test_analyze_passes_phase_executor_overrides(monkeypatch, empty_environment):
    """Coordinator 应将 phase_executor_overrides 透传到 create_phase_executor。"""
    captured_factory_kwargs: dict[str, Any] = {}

    class _FakeExecutor:
        def execute(self, **kwargs):
            return PhaseProgress(
                current_phase=Phase.SYNTHESIS,
                completed_phases=[Phase.COLLECTION, Phase.VALIDATION, Phase.DEBATE, Phase.SYNTHESIS],
                total_duration=0.2,
                agent_results={Phase.COLLECTION: [_build_agent_result("scout", "finding")]},
            )

    def _fake_factory(**kwargs):
        captured_factory_kwargs.update(kwargs)
        return _FakeExecutor()

    monkeypatch.setattr("src.coordinator.create_phase_executor", _fake_factory)

    coordinator = Coordinator(
        environment=empty_environment,
        search_tool=object(),
        phase_executor_overrides={
            "min_confidence": 0.65,
            "debate_rounds": 4,
            "debate_verified_only": False,
        },
    )

    result = coordinator.analyze(target="Notion")

    assert result.success is True
    assert captured_factory_kwargs["min_confidence"] == 0.65
    assert captured_factory_kwargs["debate_rounds"] == 4
    assert captured_factory_kwargs["debate_verified_only"] is False


def test_flatten_phase_errors_preserves_structured_error_fields(empty_environment):
    """结构化 phase error 应保留 error_type/recoverable/hint 字段。"""
    coordinator = Coordinator(environment=empty_environment, search_tool=object())
    flattened = coordinator._flatten_phase_errors(
        {
            Phase.COLLECTION: [
                {
                    "error": "search timed out",
                    "agent_type": "scout",
                    "error_type": "UPSTREAM_TIMEOUT",
                    "recoverable": True,
                    "hint": "retry",
                }
            ]
        }
    )

    assert flattened == [
        {
            "phase": "collection",
            "error": "search timed out",
            "agent_type": "scout",
            "error_type": "UPSTREAM_TIMEOUT",
            "recoverable": True,
            "hint": "retry",
        }
    ]


def test_flatten_phase_errors_infers_unknown_type_and_run_id(empty_environment):
    """字符串错误应补全 error_type 和 run_id。"""
    coordinator = Coordinator(environment=empty_environment, search_tool=object())
    flattened = coordinator._flatten_phase_errors(
        {
            Phase.DEBATE: ["red_team: weak evidence"],
        },
        run_id="run-123",
    )

    assert flattened == [
        {
            "phase": "debate",
            "agent_type": "red_team",
            "error": "weak evidence",
            "error_type": "UNKNOWN",
            "recoverable": True,
            "hint": "Inspect coordinator logs for raw error context.",
            "run_id": "run-123",
        }
    ]


def test_flatten_phase_errors_preserves_claim_trace_fields(empty_environment):
    """结构化错误应保留 claim/evidence/verdict/run_id 等追溯字段。"""
    coordinator = Coordinator(environment=empty_environment, search_tool=object())
    flattened = coordinator._flatten_phase_errors(
        {
            Phase.DEBATE: [
                {
                    "phase": "debate",
                    "agent_type": "red_team",
                    "error": "claim unresolved",
                    "error_type": "PARSE_FAILURE",
                    "recoverable": True,
                    "hint": "inspect transcript",
                    "claim_id": "red-1-abc",
                    "evidence_signal_ids": ["sig-a", "sig-b"],
                    "verdict": "UNCERTAIN",
                    "run_id": "run-claim-1",
                }
            ]
        }
    )

    assert flattened == [
        {
            "phase": "debate",
            "agent_type": "red_team",
            "error": "claim unresolved",
            "error_type": "PARSE_FAILURE",
            "recoverable": True,
            "hint": "inspect transcript",
            "claim_id": "red-1-abc",
            "evidence_signal_ids": ["sig-a", "sig-b"],
            "verdict": "UNCERTAIN",
            "run_id": "run-claim-1",
        }
    ]


def test_analyze_logs_structured_phase_errors(monkeypatch, caplog, empty_environment):
    """analyze 应输出包含 run_id/error_type 的结构化错误日志。"""
    progress = PhaseProgress(
        current_phase=Phase.SYNTHESIS,
        completed_phases=[Phase.COLLECTION, Phase.VALIDATION, Phase.DEBATE, Phase.SYNTHESIS],
        total_duration=0.1,
        agent_results={Phase.COLLECTION: [_build_agent_result("scout", "finding")]},
        phase_errors={Phase.DEBATE: ["red_team: weak evidence"]},
    )

    class _FakeExecutor:
        def execute(self, **kwargs):
            return progress

    monkeypatch.setattr("src.coordinator.create_phase_executor", lambda **_: _FakeExecutor())

    coordinator = Coordinator(environment=empty_environment, search_tool=object())
    with caplog.at_level(logging.WARNING, logger="src.coordinator"):
        result = coordinator.analyze(target="Notion")

    log_text = caplog.text
    assert "analysis_error run_id=" in log_text
    assert f"run_id={result.metadata['run_id']}" in log_text
    assert "phase=debate" in log_text
    assert "agent_type=red_team" in log_text
    assert "error_type=UNKNOWN" in log_text
