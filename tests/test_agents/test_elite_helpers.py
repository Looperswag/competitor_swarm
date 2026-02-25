"""Unit tests for EliteAgent helper logic."""

from __future__ import annotations

from src.agents.elite import EliteAgent, NormalizedDiscovery
from src.environment import DiscoverySource
from src.utils.imports import Actionability, Sentiment, SignalType


def _nd(
    agent_type: str,
    content: str,
    quality_score: float = 0.8,
    metadata: dict[str, object] | None = None,
    discovery_id: str | None = None,
) -> NormalizedDiscovery:
    return NormalizedDiscovery(
        id=discovery_id or f"test-{agent_type}-{content[:10]}",
        agent_type=agent_type,
        content=content,
        quality_score=quality_score,
        metadata=metadata or {},
    )


def test_collect_all_discoveries_prefers_signals(mock_llm_client, empty_environment):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    agent.USE_SIGNALS = True

    empty_environment.add_discovery(
        agent_type="scout",
        content="Legacy discovery should be ignored when signals exist.",
        source=DiscoverySource.WEBSITE,
        quality_score=0.7,
    )
    agent.emit_signal(
        signal_type=SignalType.INSIGHT,
        evidence="Signal evidence about product positioning and user growth.",
        confidence=0.8,
        strength=0.7,
        sentiment=Sentiment.NEUTRAL,
        tags=["growth"],
        source="test",
        actionability=Actionability.INFORMATIONAL,
        metadata={"target": "Notion"},
    )

    normalized = agent._collect_all_discoveries()

    assert normalized
    assert all(isinstance(item, NormalizedDiscovery) for item in normalized)
    assert normalized[0].content.startswith("Signal evidence")


def test_collect_all_discoveries_falls_back_to_legacy_discoveries(mock_llm_client, empty_environment):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    agent.USE_SIGNALS = True

    empty_environment.add_discovery(
        agent_type="market",
        content="Legacy market insight used when no signal exists.",
        source=DiscoverySource.ANALYSIS,
        quality_score=0.6,
    )

    normalized = agent._collect_all_discoveries()

    assert len(normalized) == 1
    assert normalized[0].agent_type == "market"
    assert normalized[0].content.startswith("Legacy market insight")


def test_generate_keyword_based_insights_requires_cross_dimension_support(mock_llm_client, empty_environment):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    discoveries = [
        _nd("scout", "Integration quality drives enterprise retention and integration roadmap."),
        _nd("market", "Market feedback highlights integration as a buying criterion."),
        _nd("technical", "API integration maturity impacts developer adoption."),
        _nd("market", "Integration mention but low quality.", quality_score=0.2),
    ]

    insights = agent._generate_keyword_based_insights("Notion", discoveries)

    assert insights
    assert insights[0]["source"] == "keyword_analysis"
    assert len(insights[0]["dimensions"]) >= 2


def test_generate_semantic_insights_supports_no_link_and_link_paths(
    mock_llm_client,
    empty_environment,
    monkeypatch,
):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    discoveries = [_nd("market", "Enterprise segment keeps growing in Asia.")]

    class NoLinker:
        def __init__(self, _llm_client):
            pass

        def find_cross_dimension_links(self, *_args, **_kwargs):
            return []

        def format_links_for_prompt(self, *_args, **_kwargs):
            return ""

    monkeypatch.setattr("src.analysis.semantic_linker.SemanticLinker", NoLinker)
    assert agent._generate_semantic_insights("Notion", discoveries, has_search=False) == []

    class HasLinker:
        def __init__(self, _llm_client):
            pass

        def find_cross_dimension_links(self, *_args, **_kwargs):
            return [object()]

        def format_links_for_prompt(self, *_args, **_kwargs):
            return "link context"

    monkeypatch.setattr("src.analysis.semantic_linker.SemanticLinker", HasLinker)
    monkeypatch.setattr(
        agent,
        "think",
        lambda *_args, **_kwargs: '[{"content":"Cross insight","dimensions":["market","technical"],"strategic_value":"high"}]',
    )

    parsed = agent._generate_semantic_insights("Notion", discoveries, has_search=True)
    assert len(parsed) == 1
    assert parsed[0]["content"] == "Cross insight"


def test_generate_deep_insights_respects_quality_threshold_and_parses_response(
    mock_llm_client,
    empty_environment,
    monkeypatch,
):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    small = [_nd("market", "Only one insight.")]
    assert agent._generate_deep_insights("Notion", small, has_search=False) == []

    rich = [
        _nd("market", f"Market discovery {i} with strategic signal", 0.9 - i * 0.05)
        for i in range(4)
    ] + [
        _nd("technical", f"Technical discovery {i} indicates architectural risk", 0.85 - i * 0.05)
        for i in range(4)
    ]
    monkeypatch.setattr(
        agent,
        "think",
        lambda *_args, **_kwargs: '[{"content":"Deep insight from cross tension","strategic_value":"high"}]',
    )

    insights = agent._generate_deep_insights("Notion", rich, has_search=False)
    assert insights
    assert insights[0]["description"] == "Deep insight from cross tension"


def test_store_elite_discoveries_writes_summary_insight_and_recommendation(mock_llm_client, empty_environment):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    stored = agent._store_elite_discoveries(
        target="Notion",
        report={"summary": "Comprehensive summary"},
        insights=[{"description": "Cross-agent synthesis", "dimensions": ["market", "technical"], "significance": "high"}],
        recommendations=[{"description": "Prioritize enterprise onboarding", "priority": "高", "impact": "高", "difficulty": "中"}],
    )

    assert len(stored) == 3
    types = [item.metadata["type"] for item in stored]
    assert "summary" in types
    assert "emergent_insight" in types
    assert "recommendation" in types


def test_build_format_and_extract_helpers(mock_llm_client, empty_environment):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    discoveries = [
        _nd("market", "Market share rising in mid-market segment", 0.8),
        _nd("technical", "API stability improved after architecture refactor", 0.9),
    ]

    grouped = agent._group_discoveries_by_agent(discoveries)
    prompt = agent._build_synthesis_prompt("Notion", grouped, has_search=True)
    summary = agent._format_discoveries_summary(grouped)
    cross = agent._format_cross_agent_insights(
        [{"from_agent": "market", "referenced_by": ["technical"], "content": "Evidence overlap", "reference_count": 2}]
    )
    high_value = agent._format_high_value_discoveries(discoveries)
    extracted = agent._extract_summary(
        "\n".join(
            [
                "This line is too short.",
                "This is a longer line that should be selected in summary output.",
                "Another useful line for summary extraction in the report.",
            ]
        )
    )
    legacy_parsed = agent._parse_insights("Paragraph A\n\nParagraph B")

    assert "已结合最新市场动态进行分析" in prompt
    assert "## market 分析" in summary
    assert "market → technical" in cross
    assert high_value.startswith("- ")
    assert "summary extraction" in extracted
    assert len(legacy_parsed) == 2


def test_parse_insights_with_json_and_markdown_fallback(mock_llm_client, empty_environment):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    json_block = """```json
[
  {"content": "Insight from JSON", "dimensions": ["market"], "strategic_value": "high"}
]
```"""
    parsed_json = agent._parse_insights_with_json(json_block)
    assert len(parsed_json) == 1
    assert parsed_json[0]["content"] == "Insight from JSON"

    markdown = """## Insight 1
Cross-dimensional opportunity identified.
- Evidence A
- Evidence B
"""
    parsed_md = agent._parse_insights_with_json(markdown)
    assert len(parsed_md) == 1
    assert "Cross-dimensional opportunity" in parsed_md[0]["content"]
    assert parsed_md[0]["evidence"] == ["Evidence A", "Evidence B"]


def test_parse_recommendations_filters_short_and_limits_to_ten(mock_llm_client, empty_environment):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    lines = [f"- Recommendation line {i} with enough detail to be accepted." for i in range(12)]
    lines.insert(0, "- too short")

    parsed = agent._parse_recommendations("\n".join(lines))

    assert len(parsed) == 10
    assert all(item["description"].startswith("Recommendation line") for item in parsed)


def test_get_search_context_aggregates_non_empty_results(mock_llm_client, empty_environment, monkeypatch):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    calls: list[str] = []

    def fake_search(query: str, max_results: int = 5) -> str:
        calls.append(query)
        return "result body" if "行业趋势" in query else ""

    monkeypatch.setattr(agent, "search_context", fake_search)
    context = agent._get_search_context("Notion")

    assert len(calls) == 3
    assert "搜索结果" in context
    assert "行业趋势" in context


def test_extract_emergent_insights_returns_motif_trace(
    mock_llm_client,
    empty_environment,
    monkeypatch,
):
    agent = EliteAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    class _FakeMotifMiner:
        def __init__(self, environment):
            self._environment = environment

        def mine(self, *, claims=None, limit=5):
            return (
                [
                    {
                        "content": "Motif insight",
                        "description": "Motif insight",
                        "dimensions": ["market", "technical"],
                        "strategic_value": "high",
                        "motif_type": "Convergence",
                        "trace_id": "emg-001",
                        "evidence_signal_ids": ["sig-1"],
                        "evidence_claim_ids": ["claim-1"],
                        "phase_trace": ["collection", "debate", "synthesis"],
                        "pheromone_score": 0.77,
                    }
                ],
                [
                    {
                        "trace_id": "emg-001",
                        "motif_type": "Convergence",
                        "signal_ids": ["sig-1"],
                        "claim_ids": ["claim-1"],
                        "phase_trace": ["collection", "debate", "synthesis"],
                        "score": 0.77,
                    }
                ],
            )

    monkeypatch.setattr("src.agents.elite.MotifMiner", _FakeMotifMiner)
    monkeypatch.setattr(agent, "_generate_keyword_based_insights", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(agent, "_generate_semantic_insights", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(agent, "_generate_deep_insights", lambda *_args, **_kwargs: [])

    insights, traces = agent._extract_emergent_insights(
        "Notion",
        discoveries=[_nd("market", "Some signal text")],
        has_search=False,
        debate_claims=[{"claim_id": "claim-1"}],
    )

    assert len(insights) == 1
    assert insights[0]["trace_id"] == "emg-001"
    assert len(traces) == 1
    assert traces[0]["trace_id"] == "emg-001"
