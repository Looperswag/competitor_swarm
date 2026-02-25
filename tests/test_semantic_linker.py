"""Unit tests for semantic linker logic."""

from __future__ import annotations

from types import SimpleNamespace

from src.analysis.semantic_linker import CrossDimensionLink, SemanticLinker
from src.environment import Discovery, DiscoverySource


def _disc(
    discovery_id: str,
    agent_type: str,
    content: str,
    quality_score: float = 0.7,
) -> Discovery:
    return Discovery(
        id=discovery_id,
        agent_type=agent_type,
        content=content,
        source=DiscoverySource.ANALYSIS,
        quality_score=quality_score,
        timestamp="2025-01-01T00:00:00",
        references=[],
        metadata={},
    )


def test_cross_dimension_link_to_dict_truncates_contents():
    content_a = "A" * 240
    content_b = "B" * 250
    link = CrossDimensionLink(
        discovery_a=_disc("a", "market", content_a),
        discovery_b=_disc("b", "technical", content_b),
        agent_a="market",
        agent_b="technical",
        similarity=0.83,
        connection_type="reinforcing",
        rationale="Strong overlap on platform strategy.",
    )

    data = link.to_dict()

    assert data["discovery_a_id"] == "a"
    assert data["discovery_b_id"] == "b"
    assert len(data["discovery_a_content"]) == 200
    assert len(data["discovery_b_content"]) == 200


def test_group_and_filter_discoveries_sorts_and_limits():
    linker = SemanticLinker(llm_client=object())
    discoveries = [
        _disc("a1", "market", "m1", 0.1),
        _disc("a2", "market", "m2", 0.9),
        _disc("a3", "market", "m3", 0.7),
        _disc("b1", "technical", "t1", 0.8),
    ]

    grouped = linker._group_and_filter_discoveries(discoveries, top_per_agent=2)

    assert list(grouped.keys()) == ["market", "technical"]
    assert [d.id for d in grouped["market"]] == ["a2", "a3"]
    assert len(grouped["market"]) == 2


def test_keyword_match_pairs_returns_ranked_matches():
    linker = SemanticLinker(llm_client=object())
    discoveries_a = [
        _disc("a1", "market", "enterprise workflow growth and collaboration"),
        _disc("a2", "market", "low overlap sample"),
    ]
    discoveries_b = [
        _disc("b1", "technical", "collaboration platform enables enterprise API workflow"),
        _disc("b2", "technical", "unrelated content"),
    ]

    pairs = linker._keyword_match_pairs(discoveries_a, discoveries_b)

    assert pairs
    assert pairs[0][0] == 0
    assert pairs[0][1] == 0
    assert pairs[0][2] > 0


def test_build_evaluation_prompt_contains_pairs_and_truncation():
    linker = SemanticLinker(llm_client=object())
    pairs = [
        (
            (0, _disc("a1", "market", "M" * 170)),
            (0, _disc("b1", "technical", "T" * 180)),
        )
    ]

    prompt = linker._build_evaluation_prompt(pairs, "market", "technical")

    assert "配对 0" in prompt
    assert "..." in prompt
    assert "JSON 数组格式" in prompt


def test_parse_evaluation_response_and_normalize_results():
    linker = SemanticLinker(llm_client=object())

    codeblock = """```json
[
  {"index": 0, "similarity": 0.8, "connection_type": "complementary", "rationale": "r1"},
  {"index": 1, "similarity": 0.6, "connection_type": "causal", "rationale": "r2"}
]
```"""
    parsed = linker._parse_evaluation_response(codeblock, expected_count=2)
    assert len(parsed) == 2
    assert parsed[0]["idx_a"] == 0
    assert parsed[1]["connection_type"] == "causal"

    raw_json = '[{"index": 0, "similarity": 0.4, "connection_type": "conflicting", "rationale": "x"}]'
    parsed_raw = linker._parse_evaluation_response(raw_json, expected_count=1)
    assert len(parsed_raw) == 1
    assert parsed_raw[0]["connection_type"] == "conflicting"

    normalized = linker._normalize_results(
        results=[{"index": 0, "similarity": "0.9", "rationale": "ok"}, "skip-me"],
        expected_count=3,
    )
    assert normalized == [
        {
            "idx_a": 0,
            "idx_b": 0,
            "similarity": 0.9,
            "connection_type": "complementary",
            "rationale": "ok",
        }
    ]


def test_parse_evaluation_response_invalid_json_returns_empty():
    linker = SemanticLinker(llm_client=object())
    assert linker._parse_evaluation_response("not-json", expected_count=2) == []


def test_evaluate_pairs_batch_success_and_failure_paths():
    success_llm = SimpleNamespace(
        chat=lambda **_kwargs: SimpleNamespace(
            content='[{"index": 0, "similarity": 0.7, "connection_type": "reinforcing", "rationale": "ok"}]'
        )
    )
    linker = SemanticLinker(llm_client=success_llm)
    pairs = [((0, _disc("a", "market", "market content")), (0, _disc("b", "technical", "technical content")))]

    success = linker._evaluate_pairs_batch(pairs, "market", "technical")
    assert success[0]["similarity"] == 0.7
    assert success[0]["connection_type"] == "reinforcing"

    class FailingLLM:
        def chat(self, **_kwargs):
            raise RuntimeError("boom")

    fallback_linker = SemanticLinker(llm_client=FailingLLM())
    fallback = fallback_linker._evaluate_pairs_batch(pairs, "market", "technical")
    assert fallback[0]["similarity"] == 0.0
    assert "Evaluation failed" in fallback[0]["rationale"]


def test_batch_evaluate_similarity_splits_into_batches(monkeypatch):
    linker = SemanticLinker(llm_client=object())
    calls: list[int] = []

    def fake_eval(batch, _agent_a, _agent_b):
        calls.append(len(batch))
        return []

    monkeypatch.setattr(linker, "_evaluate_pairs_batch", fake_eval)

    discoveries_a = [_disc(f"a{i}", "market", f"market {i}") for i in range(3)]
    discoveries_b = [_disc(f"b{i}", "technical", f"tech {i}") for i in range(4)]
    linker._batch_evaluate_similarity(discoveries_a, discoveries_b, "market", "technical", min_similarity=0.2)

    assert calls == [10, 2]


def test_find_links_between_agents_hybrid_uses_fallback_candidates(monkeypatch):
    linker = SemanticLinker(llm_client=object())
    discoveries_a = [_disc("a1", "market", "market insight")]
    discoveries_b = [_disc("b1", "technical", "technical insight")]

    monkeypatch.setattr(linker, "_keyword_match_pairs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        linker,
        "_batch_evaluate_similarity",
        lambda *_args, **_kwargs: [
            {"similarity": 0.95, "connection_type": "causal", "rationale": "high overlap"}
        ],
    )

    links = linker._find_links_between_agents_hybrid(
        discoveries_a,
        discoveries_b,
        "market",
        "technical",
        min_similarity=0.2,
        max_links=3,
    )

    assert len(links) == 1
    assert links[0].agent_a == "market"
    assert links[0].agent_b == "technical"
    assert links[0].connection_type == "causal"


def test_find_cross_dimension_links_and_format_links_for_prompt(monkeypatch):
    linker = SemanticLinker(llm_client=object())
    discoveries = [
        _disc("a1", "market", "market growth pattern"),
        _disc("b1", "technical", "technical scale pattern"),
        _disc("c1", "experience", "experience quality pattern"),
    ]

    def fake_links(d_a, d_b, agent_a, agent_b, *_args, **_kwargs):
        if {agent_a, agent_b} == {"market", "technical"}:
            similarity = 0.9
        else:
            similarity = 0.4
        return [
            CrossDimensionLink(
                discovery_a=d_a[0],
                discovery_b=d_b[0],
                agent_a=agent_a,
                agent_b=agent_b,
                similarity=similarity,
                connection_type="complementary",
                rationale="related",
            )
        ]

    monkeypatch.setattr(linker, "_find_links_between_agents_hybrid", fake_links)

    links = linker.find_cross_dimension_links(discoveries)
    assert len(links) == 3
    assert links[0].similarity >= links[-1].similarity

    empty_text = linker.format_links_for_prompt([])
    formatted = linker.format_links_for_prompt(links, max_links=1)

    assert empty_text == "暂无跨维度语义关联。"
    assert "跨维度语义关联" in formatted
    assert "还有 2 个关联未显示" in formatted
