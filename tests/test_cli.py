"""CLI 命令测试。"""

import json
from types import SimpleNamespace
from typing import Any

from click.testing import CliRunner

from src.agents.base import AgentResult
from src.coordinator import CoordinatorResult
from src.cli import cli


class _HealthySearchTool:
    """用于测试的健康搜索工具。"""

    def check_health(self) -> bool:
        return True


def _build_mock_config(tmp_path):
    """构造最小可用配置对象。"""
    return SimpleNamespace(
        cache=SimpleNamespace(path=str(tmp_path / "cache")),
        output=SimpleNamespace(path=str(tmp_path / "output")),
        search=SimpleNamespace(provider="multi", api_key=""),
    )


def test_check_env_success(monkeypatch, tmp_path):
    """check-env 成功路径。"""
    from src import cli as cli_module

    monkeypatch.setenv("ZHIPUAI_API_KEY", "test.key")
    monkeypatch.setattr(cli_module, "get_config", lambda: _build_mock_config(tmp_path))
    monkeypatch.setattr(cli_module, "get_client", lambda: object())

    monkeypatch.setattr("src.search.get_search_tool", lambda *args, **kwargs: _HealthySearchTool())

    runner = CliRunner()
    result = runner.invoke(cli, ["check-env"])

    assert result.exit_code == 0
    assert "环境检查通过" in result.output


def test_check_env_missing_api_key(monkeypatch, tmp_path):
    """check-env 缺少 API Key 应该失败。"""
    from src import cli as cli_module

    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    monkeypatch.setattr(cli_module, "get_config", lambda: _build_mock_config(tmp_path))
    monkeypatch.setattr(cli_module, "get_client", lambda: object())

    monkeypatch.setattr("src.search.get_search_tool", lambda *args, **kwargs: _HealthySearchTool())

    runner = CliRunner()
    result = runner.invoke(cli, ["check-env"])

    assert result.exit_code != 0
    assert "ZHIPUAI_API_KEY 未设置" in result.output


def test_analyze_passes_phase_overrides_to_coordinator(monkeypatch, tmp_path):
    """analyze 应将 --phase-* 参数透传给 Coordinator。"""
    from src import cli as cli_module

    captured_init_kwargs: dict[str, object] = {}

    class _FakeCoordinator:
        def __init__(self, **kwargs):
            captured_init_kwargs.update(kwargs)

        def analyze(self, **kwargs):
            return CoordinatorResult(
                target=kwargs.get("target", "Notion"),
                success=True,
                duration=0.1,
                agent_results={},
                metadata={"total_discoveries": 1},
            )

    class _FakeReporter:
        def save_report(self, result, filename=None):
            return str(tmp_path / "analysis.md")

    monkeypatch.setenv("ZHIPUAI_API_KEY", "test.key")
    monkeypatch.setattr(cli_module, "get_client", lambda: object())
    monkeypatch.setattr(cli_module, "reset_coordinator", lambda: None)
    monkeypatch.setattr(cli_module, "Coordinator", _FakeCoordinator)
    monkeypatch.setattr(cli_module, "get_reporter", lambda: _FakeReporter())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "analyze",
            "Notion",
            "--phase-validation-min-confidence",
            "0.66",
            "--phase-validation-min-strength",
            "0.2",
            "--phase-validation-min-weighted-score",
            "0.6",
            "--phase-debate-rounds",
            "5",
            "--phase-debate-strength-step",
            "0.12",
            "--phase-debate-round-decay",
            "0.9",
            "--phase-debate-max-adjustment",
            "0.3",
            "--phase-debate-scope",
            "all",
        ],
    )

    assert result.exit_code == 0
    phase_overrides = captured_init_kwargs["phase_executor_overrides"]
    assert phase_overrides == {
        "min_confidence": 0.66,
        "min_strength": 0.2,
        "min_weighted_score": 0.6,
        "debate_rounds": 5,
        "debate_strength_step": 0.12,
        "debate_round_decay": 0.9,
        "debate_max_adjustment": 0.3,
        "debate_verified_only": False,
    }


def test_analyze_failure_prints_readable_error_reasons(monkeypatch):
    """analyze 失败时应以可读结构输出失败原因。"""
    from src import cli as cli_module

    class _FakeCoordinator:
        def __init__(self, **kwargs):
            self._on_phase_start = kwargs.get("on_phase_start")
            self._on_phase_complete = kwargs.get("on_phase_complete")
            self._on_agent_start = kwargs.get("on_agent_start")

        def analyze(self, **kwargs):
            if self._on_phase_start:
                self._on_phase_start("信息收集")
            if self._on_agent_start:
                self._on_agent_start("侦察专家")
            if self._on_phase_complete:
                self._on_phase_complete("信息收集", 30)

            return CoordinatorResult(
                target=kwargs.get("target", "Notion"),
                success=False,
                duration=0.2,
                agent_results={},
                errors=[
                    {"phase": "collection", "agent_type": "scout", "error": "request timeout"},
                    {"phase": "debate", "agent_type": "red_team", "error": "weak evidence"},
                ],
                metadata={"run_id": "run-fail-1"},
            )

    monkeypatch.setenv("ZHIPUAI_API_KEY", "test.key")
    monkeypatch.setattr(cli_module, "get_client", lambda: object())
    monkeypatch.setattr(cli_module, "reset_coordinator", lambda: None)
    monkeypatch.setattr(cli_module, "Coordinator", _FakeCoordinator)

    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", "Notion"])
    combined = "\n".join([result.output, getattr(result, "stderr", "")])

    assert result.exit_code != 0
    assert "✗ 分析失败" in combined
    assert "失败原因" in combined
    assert "Run ID: run-fail-1" in combined
    assert "1. 信息收集 / scout [UNKNOWN]: request timeout" in combined
    assert "2. 红蓝队对抗 / red_team [UNKNOWN]: weak evidence" in combined


def test_analyze_prints_phase_and_agent_observability_summary(monkeypatch, tmp_path):
    """analyze 成功但含异常时，应输出阶段与 Agent 总览。"""
    from src import cli as cli_module

    captured_init_kwargs: dict[str, Any] = {}

    class _FakeCoordinator:
        def __init__(self, **kwargs):
            captured_init_kwargs.update(kwargs)

        def analyze(self, **kwargs):
            return CoordinatorResult(
                target=kwargs.get("target", "Notion"),
                success=True,
                duration=0.3,
                agent_results={},
                errors=[
                    {
                        "phase": "validation",
                        "agent_type": "technical",
                        "error": "empty output",
                        "error_type": "EMPTY_OUTPUT",
                        "hint": "review llm prompt constraints",
                    }
                ],
                metadata={
                    "run_id": "run-partial-1",
                    "total_discoveries": 6,
                    "phase_progress": {
                        "completed_phases": ["collection", "validation", "debate", "synthesis"],
                        "phase_errors": {
                            "validation": [
                                {
                                    "agent_type": "technical",
                                    "error": "empty output",
                                    "error_type": "EMPTY_OUTPUT",
                                }
                            ],
                        },
                    },
                    "agent_status": {
                        "total_agents": 7,
                        "failed_agents": ["technical"],
                        "successful_agents": ["scout", "market"],
                        "empty_agents": ["experience"],
                    },
                },
            )

    class _FakeReporter:
        def save_report(self, result, filename=None):
            return str(tmp_path / "analysis.md")

    monkeypatch.setenv("ZHIPUAI_API_KEY", "test.key")
    monkeypatch.setattr(cli_module, "get_client", lambda: object())
    monkeypatch.setattr(cli_module, "reset_coordinator", lambda: None)
    monkeypatch.setattr(cli_module, "Coordinator", _FakeCoordinator)
    monkeypatch.setattr(cli_module, "get_reporter", lambda: _FakeReporter())

    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", "Notion"])
    combined = "\n".join([result.output, getattr(result, "stderr", "")])

    assert result.exit_code == 0
    assert "阶段执行总览" in combined
    assert "信息收集: 完成" in combined
    assert "交叉验证: 异常(1: EMPTY_OUTPUT×1)" in combined
    assert "Agent 执行总览" in combined
    assert "失败: technical" in combined
    assert "⚠ 本次分析存在部分异常" in combined
    assert "Run ID: run-partial-1" in combined
    assert "1. 交叉验证 / technical [EMPTY_OUTPUT]: empty output | hint=review llm prompt constraints" in combined


def test_analyze_explain_emergence_outputs_trace(monkeypatch, tmp_path):
    """--explain-emergence 应输出结构化追溯链。"""
    from src import cli as cli_module

    class _FakeCoordinator:
        def __init__(self, **kwargs):
            pass

        def analyze(self, **kwargs):
            return CoordinatorResult(
                target=kwargs.get("target", "Notion"),
                success=True,
                duration=0.2,
                agent_results={
                    "elite": [
                        AgentResult(
                            agent_type="elite",
                            agent_name="综合",
                            discoveries=[],
                            handoffs_created=0,
                            metadata={
                                "report": {
                                    "insight_trace": [
                                        {
                                            "trace_id": "emg-123",
                                            "motif_type": "Convergence",
                                            "score": 0.7012,
                                            "signal_ids": ["sig-1", "sig-2"],
                                            "claim_ids": ["cl-1"],
                                            "phase_trace": ["collection", "debate", "synthesis"],
                                        }
                                    ]
                                }
                            },
                        )
                    ]
                },
                metadata={"run_id": "run-emg-1", "total_discoveries": 2},
            )

    class _FakeReporter:
        def save_report(self, result, filename=None):
            return str(tmp_path / "analysis.md")

    monkeypatch.setenv("ZHIPUAI_API_KEY", "test.key")
    monkeypatch.setattr(cli_module, "get_client", lambda: object())
    monkeypatch.setattr(cli_module, "reset_coordinator", lambda: None)
    monkeypatch.setattr(cli_module, "Coordinator", _FakeCoordinator)
    monkeypatch.setattr(cli_module, "get_reporter", lambda: _FakeReporter())

    runner = CliRunner()
    result = runner.invoke(cli, ["analyze", "Notion", "--explain-emergence"])
    combined = "\n".join([result.output, getattr(result, "stderr", "")])

    assert result.exit_code == 0
    assert "Emergence Explain" in combined
    assert "Run ID: run-emg-1" in combined
    assert "[Convergence] emg-123 (score=0.7012)" in combined
    assert "signals: sig-1, sig-2" in combined


def test_convert_report_generates_markdown_and_optionally_deletes_json(tmp_path):
    """convert-report 应生成可读 Markdown，并可删除源 JSON。"""
    json_path = tmp_path / "analysis_Anker_20260214_131710.json"
    json_path.write_text(
        json.dumps(
            {
                "target": "Anker",
                "timestamp": "2026-02-14T13:17:10",
                "total_discoveries": 3,
                "summary": "===== 综合报告 ===== **测试摘要** | 维度 | 竞品表现 |",
                "quick_read": {
                    "threats": ["质量风险 — 证据: 召回 — 时间: 2025 — 置信度: 高"],
                    "opportunities": ["VOC 机制可提升迭代效率 — 证据: 研报 — 时间: 长期 — 置信度: 高"],
                    "actions": ["先做质量整改"],
                },
                "strategic_matrix": [],
                "risk_opportunity_matrix": [],
                "recommendations": [{"description": "**[red_team]** 先修复供应链"}],
                "phase_strategy": {
                    "validation": {"verified_count": 1, "filtered_count": 0, "strategy": {}},
                    "debate": {"debate_rounds": 1, "red_points": 1, "blue_points": 1, "claims": []},
                },
                "agent_discoveries": {
                    "scout": [{"content": "发现 A — 证据: 官网 — 时间: 2025 — 置信度: 中"}],
                    "experience": [],
                    "technical": [],
                    "market": [],
                    "red_team": [],
                    "blue_team": [],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "convert-report",
            "--input",
            str(json_path),
            "--delete-json",
            "--readable",
        ],
    )
    combined = "\n".join([result.output, getattr(result, "stderr", "")])

    expected_md = tmp_path / "analysis_Anker_20260214_131710_readable.md"
    assert result.exit_code == 0
    assert expected_md.exists()
    assert not json_path.exists()
    assert "Markdown 报告已生成" in combined
    content = expected_md.read_text(encoding="utf-8")
    assert "# Anker 竞品分析（可读版）" in content
    assert "## 一页结论（先看这里）" in content
