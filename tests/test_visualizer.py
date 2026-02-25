"""HTML 可视化报告生成器测试。"""

import re
import shutil
import subprocess

from src.agents.base import AgentResult
from src.coordinator import CoordinatorResult
from src.reporting.visualizer import HTMLReportGenerator


def _extract_last_inline_script(content: str) -> str:
    script_blocks = re.findall(
        r"<script(?:\s[^>]*)?>(.*?)</script>",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    inline_scripts = [block for block in script_blocks if block.strip()]
    assert inline_scripts, "生成的 HTML 中未找到内联脚本"
    return inline_scripts[-1]


def _build_result() -> CoordinatorResult:
    return CoordinatorResult(
        target="Notion",
        success=True,
        duration=10.5,
        agent_results={
            "red_team": [
                AgentResult(
                    agent_type="red_team",
                    agent_name="红队",
                    discoveries=[{
                        "content": "定价高于竞品，存在中小客户流失风险 — 时间: 2024-10 — 置信度: 高",
                        "metadata": {
                            "url": "https://example.com/red",
                            "source": "官方公告",
                        },
                    }],
                    handoffs_created=1,
                )
            ],
            "blue_team": [
                AgentResult(
                    agent_type="blue_team",
                    agent_name="蓝队",
                    discoveries=[{
                        "content": "协作编辑体验稳定，适合中大型团队扩展 — 时间: 2024-06 — 置信度: 中",
                    }],
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
                            "summary": "这是一个可用但需要优化商业化路径的系统。",
                            "full_analysis": (
                                "## 执行摘要\n"
                                "===== 综合报告 =====\n"
                                "**核心结论**：产品存在增长压力。\n\n"
                                "| 维度 | 结论 |\n|---|---|\n| 产品 | 需优化 |\n"
                                "机会在于企业市场。"
                            ),
                            "recommendations": [
                                {
                                    "title": "优化定价策略",
                                    "description": "**[red_team]** 推出小团队套餐并验证转化率 — 时间: 2024-09 — 置信度: 高",
                                }
                            ],
                        }
                    },
                )
            ],
        },
        metadata={
            "total_discoveries": 8,
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
                    "synthesis": {
                        "report_generated": True,
                    },
                }
            },
            "total_signals": 12,
        },
    )


def test_prepare_report_data_contains_phase_strategy(tmp_path):
    """_prepare_report_data 应包含 phase_strategy 与 quick_read 摘要。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    prepared = generator._prepare_report_data(_build_result())

    assert "phase_strategy" in prepared
    assert "quick_read" in prepared
    assert prepared["phase_strategy"]["validation"]["verified_count"] == 5
    assert prepared["phase_strategy"]["debate"]["signal_adjustment"]["adjusted_signals"] == 4
    assert prepared["quick_read"]["threats"][0].startswith("定价高于竞品")
    assert prepared["quick_read"]["actions"][0].startswith("优化定价策略")


def test_prepare_report_data_builds_summary_paragraphs_for_html(tmp_path):
    """summary_paragraphs 应去除 Markdown/表格噪音。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    prepared = generator._prepare_report_data(_build_result())

    paragraphs = prepared.get("summary_paragraphs", [])
    assert isinstance(paragraphs, list)
    assert len(paragraphs) >= 1
    assert all("**" not in paragraph for paragraph in paragraphs)
    assert all("=====" not in paragraph for paragraph in paragraphs)
    assert all("|---|" not in paragraph for paragraph in paragraphs)


def test_prepare_report_data_collects_agent_source_links_and_hints(tmp_path):
    """应生成 agent_source_links / agent_source_hints，并保留兜底提示。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    result = _build_result()
    result.agent_results["blue_team"][0].discoveries.append({
        "content": "文档更新记录，支持按 workspace 维度追踪指标。",
        "metadata": {"source": "产品文档"},
    })

    prepared = generator._prepare_report_data(result)
    links = prepared["agent_source_links"]
    hints = prepared["agent_source_hints"]

    assert links["red_team"][0]["url"] == "https://example.com/red"
    assert hints["blue_team"]
    assert "elite" in hints  # 无发现也应保留兜底提示


def test_prepare_report_data_contains_agent_flow_appendix_payload(tmp_path):
    """agent_flow 应包含阶段和关键 run 统计。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    prepared = generator._prepare_report_data(_build_result())
    flow = prepared["agent_flow"]

    assert isinstance(flow.get("stages"), list)
    assert len(flow["stages"]) == 4
    assert flow["handoff"]["total"] >= 1
    assert flow["debate"]["claim_count"] >= 0
    assert flow["validation"]["verified_count"] == 5


def test_generate_html_contains_phase_strategy_section_and_payload(tmp_path):
    """生成的 HTML 应包含速读/阶段策略区块及 payload 数据。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    html_path = generator.generate_html(_build_result(), filename="visualizer_test.html")

    content = (tmp_path / "visualizer_test.html").read_text(encoding="utf-8")
    assert html_path.endswith("visualizer_test.html")
    assert 'id="quick-read"' in content
    assert "Top Threat" in content
    assert "Top Opportunity" in content
    assert "Top Actions" in content
    assert 'id="phase-strategy"' in content
    assert '"quick_read": {' in content
    assert '"phase_strategy": {' in content
    assert '"verified_count": 5' in content


def test_generate_html_contains_appendix_and_source_link_renderer(tmp_path):
    """HTML 应包含附录区块及来源链接渲染器。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    generator.generate_html(_build_result(), filename="visualizer_appendix_test.html")
    content = (tmp_path / "visualizer_appendix_test.html").read_text(encoding="utf-8")

    assert 'id="appendix-agent-flow"' in content
    assert "附录：Agent 信息传递" in content
    assert "function renderAgentFlowAppendix()" in content
    assert "function buildSearchFallbackUrl(target, agentKey, sourceHint)" in content
    assert '"agent_flow": {' in content
    assert '"agent_source_links": {' in content


def test_generate_html_contains_mobile_drawer_navigation_logic(tmp_path):
    """移动端导航抽屉应包含按钮、遮罩和初始化逻辑。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    generator.generate_html(_build_result(), filename="visualizer_mobile_nav_test.html")
    content = (tmp_path / "visualizer_mobile_nav_test.html").read_text(encoding="utf-8")

    assert 'id="mobile-menu-btn"' in content
    assert 'id="mobile-menu-close"' in content
    assert 'id="mobile-nav-overlay"' in content
    assert "function initMobileDrawer()" in content
    assert "classList.add('open')" in content


def test_generate_html_contains_narrative_block_and_expand_toggle(tmp_path):
    """长文本折叠渲染 helper 与展开按钮标记应存在。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    generator.generate_html(_build_result(), filename="visualizer_narrative_test.html")
    content = (tmp_path / "visualizer_narrative_test.html").read_text(encoding="utf-8")

    assert "function renderNarrativeBlock(text, options = {})" in content
    assert "data-collapse-target" in content
    assert ".line-clamp {" in content
    assert "function initNarrativeToggle()" in content


def test_generate_html_meta_styles_allow_wrapping_and_no_nowrap(tmp_path):
    """元信息样式应支持换行，避免单行 nowrap 溢出。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    generator.generate_html(_build_result(), filename="visualizer_meta_wrap_test.html")
    content = (tmp_path / "visualizer_meta_wrap_test.html").read_text(encoding="utf-8")

    assert ".meta-row {" in content
    assert ".meta-chip {" in content
    assert "white-space: nowrap;" not in content


def test_generate_html_dimensions_copy_includes_count_phrase(tmp_path):
    """维度卡片文案应包含“数字 + 条发现”。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    generator.generate_html(_build_result(), filename="visualizer_dimensions_copy_test.html")
    content = (tmp_path / "visualizer_dimensions_copy_test.html").read_text(encoding="utf-8")

    assert "${stats.count} 条发现" in content


def test_generate_html_escapes_script_breaking_sequences(tmp_path):
    """报告数据包含 </script> 时，生成 HTML 仍应保持脚本完整。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    result = _build_result()
    result.agent_results["red_team"][0].discoveries = [
        {"content": "payload </script><script>alert('xss')</script> value"}
    ]
    result.agent_results["elite"][0].metadata["report"]["summary"] = "summary </script> value"

    generator.generate_html(result, filename="visualizer_escape_test.html")
    content = (tmp_path / "visualizer_escape_test.html").read_text(encoding="utf-8")

    # 模板中仅应存在固定的 3 个脚本闭合标签（2 个外链 + 1 个内联）。
    assert content.count("</script>") == 3
    assert "payload </script><script>alert('xss')</script> value" not in content
    assert "summary </script> value" not in content
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert('xss')\\u003c/script\\u003e value" in content


def test_generate_html_inline_script_is_syntax_valid(tmp_path):
    """生成 HTML 后，内联脚本应可被 JS 语法检查通过。"""
    generator = HTMLReportGenerator(output_path=str(tmp_path))
    generator.generate_html(_build_result(), filename="visualizer_syntax_test.html")
    content = (tmp_path / "visualizer_syntax_test.html").read_text(encoding="utf-8")
    inline_script = _extract_last_inline_script(content)

    # 回归保护：禁止出现 `.replace(/` + 换行 + `/g` 的断裂正则。
    broken_replace_pattern = re.compile(r"\.replace\(/\s*\n\s*/g,\s*'<br>'\)")
    assert not broken_replace_pattern.search(inline_script)

    node_bin = shutil.which("node")
    if node_bin:
        js_file = tmp_path / "visualizer_inline_script.js"
        js_file.write_text(inline_script, encoding="utf-8")
        check_result = subprocess.run(
            [node_bin, "--check", str(js_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert check_result.returncode == 0, check_result.stderr or check_result.stdout
    else:
        assert ".replace(/\\n/g, '<br>')" in inline_script
