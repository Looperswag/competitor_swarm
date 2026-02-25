"""Reporter 模块测试。"""

from src.agents.base import AgentResult
from src.coordinator import CoordinatorResult
from src.reporter import Reporter


def _build_result(
    *,
    target: str = "Notion",
    red_text: str = "定价高于同类产品，存在流失风险",
    blue_text: str = "协作体验完整，适合中大型团队",
    action_title: str = "优化定价策略",
    action_desc: str = "推出面向小团队的轻量套餐并验证转化率。",
    insight_text: str = "需要在商业化路径与留存率之间建立平衡。",
    scout_text: str = "官网新增模板市场与 API 示例页",
    run_id: str = "run-1",
    insight_trace: list[dict] | None = None,
) -> CoordinatorResult:
    return CoordinatorResult(
        target=target,
        success=True,
        duration=12.3,
        agent_results={
            "red_team": [
                AgentResult(
                    agent_type="red_team",
                    agent_name="红队",
                    discoveries=[{"content": red_text}],
                    handoffs_created=0,
                )
            ],
            "blue_team": [
                AgentResult(
                    agent_type="blue_team",
                    agent_name="蓝队",
                    discoveries=[{"content": blue_text}],
                    handoffs_created=0,
                )
            ],
            "scout": [
                AgentResult(
                    agent_type="scout",
                    agent_name="侦察",
                    discoveries=[{"content": scout_text}],
                    handoffs_created=0,
                )
            ],
            "elite": [
                AgentResult(
                    agent_type="elite",
                    agent_name="综合",
                    discoveries=[],
                    handoffs_created=0,
                    metadata={
                        "report": {
                            "insights": [{"content": insight_text}],
                            "recommendations": [
                                {
                                    "title": action_title,
                                    "description": action_desc,
                                }
                            ],
                            "insight_trace": insight_trace or [],
                        }
                    },
                )
            ],
        },
        metadata={
            "total_discoveries": 2,
            "phase_progress": {
                "phase_metadata": {
                    "validation": {
                        "verified_count": 5,
                        "filtered_count": 2,
                        "strategy": {
                            "min_confidence": 0.3,
                            "min_strength": 0.0,
                            "min_weighted_score": 0.35,
                            "max_signals_per_dimension": 20,
                        },
                        "dimension_summary": {
                            "product": {
                                "candidate_count": 3,
                                "verified_count": 2,
                                "filtered_count": 1,
                            }
                        },
                    },
                    "debate": {
                        "debate_rounds": 3,
                        "red_points": 6,
                        "blue_points": 5,
                        "strategy": {
                            "strength_step": 0.05,
                            "round_decay": 0.85,
                            "max_adjustment": 0.2,
                            "verified_only": True,
                        },
                        "signal_adjustment": {
                            "adjusted_signals": 4,
                            "total_delta": -0.03,
                        },
                    },
                }
            },
            "run_id": run_id,
        },
    )


def test_generate_markdown_contains_quick_read_summary(tmp_path):
    """报告应包含固定头部的 3 分钟速读摘要区块。"""
    reporter = Reporter(output_path=str(tmp_path))
    markdown = reporter.generate_markdown(_build_result())

    assert "## 核心洞察（3 分钟速读）" in markdown
    assert "### Top Threat" in markdown
    assert "### Top Opportunity" in markdown
    assert "### Top Actions" in markdown
    assert "优化定价策略" in markdown


def test_generate_markdown_history_diff_no_previous_snapshot(tmp_path):
    """首次分析应提示暂无历史对比记录。"""
    reporter = Reporter(output_path=str(tmp_path))
    markdown = reporter.generate_markdown(_build_result(run_id="run-first"))

    assert "## 历史对比（同目标）" in markdown
    assert "暂无可对比的历史记录" in markdown


def test_generate_markdown_history_diff_detects_conclusion_evidence_risk_changes(tmp_path):
    """同目标多次分析时应输出结论/证据/风险变化。"""
    reporter = Reporter(output_path=str(tmp_path))
    first = _build_result(
        run_id="run-a",
        insight_text="优先提升团队协作效率。",
        red_text="企业版价格偏高导致中小客户流失。",
        blue_text="协作编辑体验完整。",
        scout_text="官网新增模板市场与 API 示例页。",
        action_title="强化协作模板",
        action_desc="优先优化跨团队模板复用。",
    )
    reporter.save_report(first, filename="first.md")

    second = _build_result(
        run_id="run-b",
        insight_text="优先拓展生态集成能力。",
        red_text="移动端性能瓶颈影响留存。",
        blue_text="生态 API 覆盖率提升。",
        scout_text="文档中心新增 SDK 接入指引。",
        action_title="推进 API 商业化",
        action_desc="针对企业客户推出 API 增值包。",
    )

    markdown = reporter.generate_markdown(second)

    assert "## 历史对比（同目标）" in markdown
    assert "### 结论变化" in markdown
    assert "### 证据变化" in markdown
    assert "### 风险变化" in markdown
    assert "优先拓展生态集成能力" in markdown
    assert "文档中心新增 SDK 接入指引" in markdown
    assert "移动端性能瓶颈影响留存" in markdown


def test_generate_markdown_includes_insight_trace_appendix(tmp_path):
    """报告附录应包含 insight_trace 追溯信息。"""
    reporter = Reporter(output_path=str(tmp_path))
    result = _build_result(
        run_id="run-trace-1",
        insight_trace=[
            {
                "trace_id": "emg-abc",
                "motif_type": "Tension",
                "score": 0.7444,
                "signal_ids": ["sig-a", "sig-b"],
                "claim_ids": ["claim-a"],
                "phase_trace": ["collection", "debate", "synthesis"],
            }
        ],
    )

    markdown = reporter.generate_markdown(result)

    assert "洞察追溯（insight_trace）" in markdown
    assert "Trace 1: emg-abc" in markdown
    assert "motif_type: Tension" in markdown
    assert "signal_ids: sig-a, sig-b" in markdown


def test_build_history_snapshot_returns_complete_dict(tmp_path):
    """history snapshot 应返回完整结构，供历史对比与持久化使用。"""
    reporter = Reporter(output_path=str(tmp_path))
    snapshot = reporter._section_generator.build_history_snapshot(_build_result())

    assert snapshot["target"] == "Notion"
    assert snapshot["run_id"] == "run-1"
    assert isinstance(snapshot["timestamp"], str) and snapshot["timestamp"]
    assert isinstance(snapshot["conclusions"], list)
    assert isinstance(snapshot["evidence"], list)
    assert isinstance(snapshot["risks"], list)


def test_generate_markdown_falls_back_when_snapshot_builder_returns_none(tmp_path, monkeypatch):
    """snapshot 构建异常时应降级，不阻断报告生成。"""
    reporter = Reporter(output_path=str(tmp_path))
    monkeypatch.setattr(reporter._section_generator, "build_history_snapshot", lambda result: None)

    markdown = reporter.generate_markdown(_build_result())

    assert "## 历史对比（同目标）" in markdown
    assert "暂无可对比的历史记录" in markdown


def test_save_report_deduplicates_history_snapshot_by_run_id(tmp_path):
    """同 run_id 重复保存时，history 应避免重复写入。"""
    reporter = Reporter(output_path=str(tmp_path))
    result = _build_result(run_id="run-dedup-1")

    reporter.save_report(result, filename="first.md")
    reporter.save_report(result, filename="second.md")

    history_file = tmp_path / ".history" / "Notion.jsonl"
    lines = [line for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
