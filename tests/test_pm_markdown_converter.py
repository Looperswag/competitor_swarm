"""PM Markdown 转换器测试。"""

from src.reporting.pm_markdown_converter import PMMarkdownConverter


def _build_report_data() -> dict:
    return {
        "target": "Anker",
        "timestamp": "2026-02-14T13:17:10",
        "total_discoveries": 50,
        "summary": (
            "===== 综合报告 ===== **Anker** 面临供应链风险与 AI 转型压力。"
            " | 维度 | 竞品表现 | 我方差距 | 战略含义 |"
        ),
        "quick_read": {
            "threats": ["核心业务存在安全事故 — 证据: 多次召回 — 时间: 2023-2025 — 置信度: 高"],
            "opportunities": ["VOC 机制可缩短迭代周期 — 证据: 研报披露 — 时间: 长期 — 置信度: 高"],
            "actions": ["先修复供应链质量，再推进 AI 商业化"],
        },
        "strategic_matrix": [
            {
                "dimension": "技术能力",
                "competitor_performance": "中",
                "our_gap": "领先/错位",
                "strategic_implication": "端侧隐私优势明显，但云端能力偏弱。",
            }
        ],
        "risk_opportunity_matrix": [],
        "recommendations": [
            {"description": "**[red_team]** 先完成供应链整改 — 证据: 召回事件 — 时间: 2025 — 置信度: 高"}
        ],
        "phase_strategy": {
            "validation": {
                "verified_count": 10,
                "filtered_count": 2,
                "strategy": {
                    "min_confidence": 0.3,
                    "min_strength": 0.0,
                    "min_weighted_score": 0.35,
                    "max_signals_per_dimension": 20,
                },
            },
            "debate": {
                "debate_rounds": 2,
                "red_points": 6,
                "blue_points": 5,
                "claim_count": 11,
                "unresolved_claim_count": 0,
                "claims": [
                    {
                        "side": "red",
                        "round": 1,
                        "text": "3C认证与产品合规性风险 — 证据: 型号认证暂停 — 时间: 2025.06 — 置信度: 高",
                        "verdict": "SUPPORTED",
                        "confidence": 0.85,
                    },
                    {
                        "side": "blue",
                        "round": 1,
                        "text": "全球第一品牌与渠道覆盖优势 — 证据: 排名第一 — 时间: 2024 — 置信度: 高",
                        "verdict": "SUPPORTED",
                        "confidence": 0.80,
                    },
                ],
            },
        },
        "agent_discoveries": {
            "scout": [{"content": "发现 A — 证据: 官网 — 时间: 2025 — 置信度: 中"}],
            "experience": [],
            "technical": [],
            "market": [],
            "red_team": [
                {
                    "content": (
                        "3C认证与产品合规性风险，面临平台下架与监管红线"
                        " — 证据: 认证暂停 — 时间: 2025.06 — 置信度: 高"
                    )
                },
                {
                    "content": (
                        "全球第一品牌护城河稳固"
                        " — 证据: 行业排名第一 — 时间: 2024 — 置信度: 高"
                    )
                },
            ],
            "blue_team": [],
        },
    }


def test_convert_data_generates_required_sections_and_cleans_markup():
    converter = PMMarkdownConverter()
    markdown = converter.convert_data(_build_report_data(), readable=True)

    assert "# Anker 竞品分析（可读版）" in markdown
    assert "## 一页结论（先看这里）" in markdown
    assert "## 战略结论" in markdown
    assert "## 战略定位（文本化）" in markdown
    assert "## 风险与机会" in markdown
    assert "## 调研全过程" in markdown
    assert "## 过滤说明" in markdown
    assert "**" not in markdown
    assert "===== 综合报告 =====" not in markdown
    assert "| 维度 |" not in markdown


def test_convert_data_filters_promotional_honor_but_keeps_compliance():
    converter = PMMarkdownConverter()
    markdown = converter.convert_data(_build_report_data(), readable=True)

    assert "全球第一品牌护城河稳固" not in markdown
    assert "行业排名第一" not in markdown
    assert "3C认证与产品合规性风险" in markdown
    assert converter.stats.filtered_promotional_items > 0
