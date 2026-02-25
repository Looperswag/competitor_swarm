"""Unit tests for ScoutAgent parsing and classification helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agents.scout import ScoutAgent
from src.utils.imports import (
    SIGNALS_AVAILABLE,
    Actionability,
    Sentiment,
    SignalType,
)


@pytest.mark.skipif(not SIGNALS_AVAILABLE, reason="Signal models are unavailable")
def test_try_parse_json_signals_from_code_block(mock_llm_client, empty_environment):
    agent = ScoutAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    response = """```json
[
  {
    "content": "Strong API ecosystem creates a clear opportunity for enterprise expansion.",
    "quality_score": 0.9
  }
]
```"""
    signals = agent._try_parse_json_signals(response, "Notion")

    assert signals is not None
    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.OPPORTUNITY
    assert signals[0].metadata["target"] == "Notion"


@pytest.mark.skipif(not SIGNALS_AVAILABLE, reason="Signal models are unavailable")
def test_try_parse_list_and_paragraph_signals(mock_llm_client, empty_environment):
    agent = ScoutAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    list_response = "\n".join(
        [
            "1. The platform has a powerful feature set with clear market traction.",
            "2. API quality remains a risk for complex integrations in enterprise use.",
            "- User feedback signals an opportunity to improve onboarding conversion rates.",
        ]
    )
    list_signals = agent._try_parse_list_signals(list_response, "Notion")
    assert list_signals is not None
    assert len(list_signals) == 3

    paragraph_response = """发现: 用户增长持续，但存在技术债务风险。

结论：The roadmap reveals a strong opportunity in the developer ecosystem.
"""
    paragraph_signals = agent._try_parse_paragraph_signals(paragraph_response, "Notion")
    assert len(paragraph_signals) >= 1


@pytest.mark.skipif(not SIGNALS_AVAILABLE, reason="Signal models are unavailable")
def test_parse_and_store_signals_uses_fallback_chain(mock_llm_client, empty_environment, monkeypatch):
    agent = ScoutAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    fake_signal = agent._create_signal_from_evidence(
        "This evidence is long enough and highlights an opportunity in market expansion.",
        "Notion",
    )

    monkeypatch.setattr(agent, "_try_parse_json_signals", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent, "_try_parse_list_signals", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent, "_try_parse_paragraph_signals", lambda *_args, **_kwargs: [fake_signal])

    parsed = agent._parse_and_store_signals("not-json text", "Notion")
    assert parsed == [fake_signal]


def test_valid_discovery_filters(mock_llm_client, empty_environment):
    agent = ScoutAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    assert not agent._is_valid_discovery("too short")
    assert not agent._is_valid_discovery("暂无相关数据")
    assert not agent._is_valid_discovery("the following points are listed")
    assert agent._is_valid_discovery("This sentence contains enough useful product information.")


@pytest.mark.skipif(not SIGNALS_AVAILABLE, reason="Signal models are unavailable")
def test_sentiment_type_actionability_and_tags_classification(mock_llm_client, empty_environment):
    agent = ScoutAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())

    assert agent._analyze_sentiment("Excellent growth and innovative strategy.") == Sentiment.POSITIVE
    assert agent._analyze_sentiment("重大问题导致用户流失 failure risk.") == Sentiment.NEGATIVE
    assert agent._analyze_sentiment("Plain neutral statement.") == Sentiment.NEUTRAL

    assert agent._classify_signal_type("This is a market opportunity.") == SignalType.OPPORTUNITY
    assert agent._classify_signal_type("This is a threat from competitors.") == SignalType.THREAT
    assert agent._classify_signal_type("用户痛点属于核心需求问题") == SignalType.NEED
    assert agent._classify_signal_type("系统依赖导致较大不确定性") == SignalType.RISK
    assert agent._classify_signal_type("General observation only") == SignalType.INSIGHT

    assert agent._determine_actionability("critical urgent issue") == Actionability.IMMEDIATE
    assert agent._determine_actionability("建议应该优化流程") == Actionability.SHORT_TERM
    assert agent._determine_actionability("长期战略规划") == Actionability.LONG_TERM
    assert agent._determine_actionability("neutral note") == Actionability.INFORMATIONAL

    tags = agent._extract_tags("Pricing and feature strategy for users in a competitive market")
    assert {"pricing", "features", "users", "market"} <= set(tags)


def test_get_search_context_and_prompt_variants(mock_llm_client, empty_environment, monkeypatch):
    agent = ScoutAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    queries: list[list[str]] = []

    def fake_search_context_async(items: list[str], max_results: int = 5):
        queries.append(items)
        return {
            items[0]: "result 1",
            items[1]: "result 2" if len(items) > 1 else "",
        }

    monkeypatch.setattr(agent, "search_context_async", fake_search_context_async)

    context = agent._get_search_context("Notion", ["Confluence"])
    prompt = agent._build_scout_prompt("Notion", ["Confluence"], has_search=True)

    assert queries and len(queries[0]) == 2
    assert "搜索结果" in context
    assert "Confluence" in prompt
    assert "已提供搜索结果作为参考" in prompt


def test_check_for_handoffs_creates_technical_handoff(mock_llm_client, empty_environment):
    agent = ScoutAgent(llm_client=mock_llm_client, environment=empty_environment, search_tool=object())
    agent.create_handoff = MagicMock()

    discoveries = [
        {"id": "d1", "content": "The API and SDK design imply a microservice architecture."},
        {"id": "d2", "content": "General market observation without technical details."},
    ]

    created = agent._check_for_handoffs(discoveries, {"target": "Notion"})

    assert created == 1
    assert agent.create_handoff.call_count == 1
    kwargs = agent.create_handoff.call_args.kwargs
    assert kwargs["to_agent"] == "technical"
