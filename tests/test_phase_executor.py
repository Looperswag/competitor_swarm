"""PhaseExecutor 核心流程测试。"""

import json
import re
import time
from types import SimpleNamespace

import pytest

from src.agents.base import AgentResult
from src.core.phase_executor import Phase, PhaseExecutor, PhaseResult, create_phase_executor
from src.core import phase_executor as phase_executor_module
from src.error_types import ErrorType

if phase_executor_module.SIGNALS_AVAILABLE:
    from src.schemas.signals import Signal, SignalType, Dimension, Sentiment, Actionability


def _result(agent_type: str, content: str = "ok") -> AgentResult:
    return AgentResult(
        agent_type=agent_type,
        agent_name=agent_type,
        discoveries=[{"content": content}],
        handoffs_created=0,
        metadata={},
    )


def test_execute_propagates_search_tool_and_collects_phase_errors(empty_environment, monkeypatch):
    """execute 应将 search_tool 传给辩论/综合阶段，并聚合阶段错误。"""
    executor = PhaseExecutor(environment=empty_environment)
    sentinel_search_tool = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        executor,
        "_execute_collection_phase",
        lambda context, search_tool: PhaseResult(
            phase=Phase.COLLECTION,
            success=True,
            duration=0.01,
            signal_count=1,
            agent_results=[_result("scout")],
            errors=[],
        ),
    )
    monkeypatch.setattr(
        executor,
        "_execute_validation_phase",
        lambda context: PhaseResult(
            phase=Phase.VALIDATION,
            success=True,
            duration=0.01,
            signal_count=1,
            agent_results=[],
            errors=[],
        ),
    )

    def _fake_debate(context, search_tool=None):
        captured["debate_search_tool"] = search_tool
        return PhaseResult(
            phase=Phase.DEBATE,
            success=False,
            duration=0.01,
            signal_count=1,
            agent_results=[_result("red_team")],
            errors=["red_team: weak evidence"],
        )

    def _fake_synthesis(context, search_tool=None):
        captured["synthesis_search_tool"] = search_tool
        return PhaseResult(
            phase=Phase.SYNTHESIS,
            success=True,
            duration=0.01,
            signal_count=1,
            agent_results=[_result("elite")],
            errors=[],
        )

    monkeypatch.setattr(executor, "_execute_debate_phase", _fake_debate)
    monkeypatch.setattr(executor, "_execute_synthesis_phase", _fake_synthesis)

    progress = executor.execute(
        target="Notion",
        competitors=["Lark"],
        focus_areas=["pricing"],
        search_tool=sentinel_search_tool,
    )

    assert progress.current_phase == Phase.SYNTHESIS
    assert progress.completed_phases == [
        Phase.COLLECTION,
        Phase.VALIDATION,
        Phase.DEBATE,
        Phase.SYNTHESIS,
    ]
    assert captured["debate_search_tool"] is sentinel_search_tool
    assert captured["synthesis_search_tool"] is sentinel_search_tool
    assert progress.phase_errors[Phase.DEBATE] == ["red_team: weak evidence"]


def test_execute_returns_progress_with_executor_error_on_exception(empty_environment, monkeypatch):
    """阶段异常时 execute 不抛出，应返回带 executor 错误的进度。"""
    executor = PhaseExecutor(environment=empty_environment)

    def _raise_collection_error(context, search_tool):
        raise RuntimeError("collection crashed")

    monkeypatch.setattr(executor, "_execute_collection_phase", _raise_collection_error)

    progress = executor.execute(target="Notion")

    assert progress.current_phase == Phase.COLLECTION
    assert progress.phase_errors[Phase.COLLECTION] == ["collection crashed"]
    assert progress.agent_results[Phase.COLLECTION][0].agent_type == "executor"
    assert progress.agent_results[Phase.COLLECTION][0].metadata == {"error": "collection crashed"}


def test_execute_passes_debate_claims_to_synthesis_context(empty_environment, monkeypatch):
    """综合阶段应收到辩论 claim 与 transcript 上下文。"""
    executor = PhaseExecutor(environment=empty_environment)
    captured_context: dict[str, object] = {}

    class _FakeElite:
        def __init__(self, environment=None, search_tool=None):
            self.name = "综合分析专家"

        def execute(self, **context):
            captured_context.update(context)
            return _result("elite")

    monkeypatch.setattr("src.core.phase_executor.EliteAgent", _FakeElite)
    executor._progress.phase_metadata[Phase.DEBATE] = {
        "debate_transcript_id": "debate-1",
        "claims": [{"claim_id": "cl-1", "side": "red", "evidence_signal_ids": ["sig-1"]}],
    }

    result = executor._execute_synthesis_phase(context={"target": "Notion"})

    assert result.success is True
    assert captured_context["debate_transcript_id"] == "debate-1"
    assert captured_context["debate_claims"] == [{"claim_id": "cl-1", "side": "red", "evidence_signal_ids": ["sig-1"]}]


def test_collection_phase_notifies_agents_and_forwards_search_tool(empty_environment, monkeypatch):
    """信息收集阶段应触发 Agent 回调并透传 search_tool。"""
    started_agents: list[str] = []
    created_search_tools: list[object] = []
    injected_environments: list[object] = []
    sentinel_search_tool = object()

    def _agent_factory(agent_type: str, name: str):
        class _FakeAgent:
            def __init__(self, environment=None, search_tool=None):
                created_search_tools.append(search_tool)
                injected_environments.append(environment)
                self.name = name
                self.agent_type = type("AgentTypeStub", (), {"value": agent_type})()

            def execute(self, **context):
                return _result(agent_type=agent_type, content=context.get("target", "unknown"))

        return _FakeAgent

    monkeypatch.setattr("src.core.phase_executor.ScoutAgent", _agent_factory("scout", "侦察专家"))
    monkeypatch.setattr("src.core.phase_executor.ExperienceAgent", _agent_factory("experience", "体验专家"))
    monkeypatch.setattr("src.core.phase_executor.TechnicalAgent", _agent_factory("technical", "技术分析专家"))
    monkeypatch.setattr("src.core.phase_executor.MarketAgent", _agent_factory("market", "市场分析专家"))

    executor = PhaseExecutor(
        environment=empty_environment,
        on_agent_start=lambda name: started_agents.append(name),
    )

    result = executor._execute_collection_phase(
        context={"target": "Notion"},
        search_tool=sentinel_search_tool,
    )

    assert result.success is True
    assert len(result.agent_results) == 4
    assert started_agents == ["侦察专家", "体验专家", "技术分析专家", "市场分析专家"]
    assert created_search_tools == [
        sentinel_search_tool,
        sentinel_search_tool,
        sentinel_search_tool,
        sentinel_search_tool,
    ]
    assert injected_environments == [
        empty_environment,
        empty_environment,
        empty_environment,
        empty_environment,
    ]


def test_collection_phase_emits_structured_errors(empty_environment, monkeypatch):
    """信息收集阶段异常应产出结构化 error 信息。"""

    class _FailingAgent:
        def __init__(self, environment=None, search_tool=None):
            self.name = "失败 Agent"
            self.agent_type = type("AgentTypeStub", (), {"value": "scout"})()

        def execute(self, **context):
            raise RuntimeError("request timed out")

    monkeypatch.setattr("src.core.phase_executor.ScoutAgent", _FailingAgent)
    monkeypatch.setattr("src.core.phase_executor.ExperienceAgent", _FailingAgent)
    monkeypatch.setattr("src.core.phase_executor.TechnicalAgent", _FailingAgent)
    monkeypatch.setattr("src.core.phase_executor.MarketAgent", _FailingAgent)

    executor = PhaseExecutor(environment=empty_environment)
    result = executor._execute_collection_phase(context={"target": "Notion"}, search_tool=object())

    assert result.success is False
    assert result.errors
    first_error = result.errors[0]
    assert first_error["phase"] == "collection"
    assert first_error["agent_type"] == "scout"
    assert first_error["error_type"] == "UPSTREAM_TIMEOUT"
    assert first_error["recoverable"] is True


def test_classify_error_marks_internal_failures():
    """NameError / AttributeError / TypeError 应标记为 INTERNAL_FAILURE。"""
    err_type, recoverable, hint = PhaseExecutor._classify_error(NameError("name 'Signal' is not defined"))
    assert err_type == ErrorType.INTERNAL_FAILURE.value
    assert recoverable is True
    assert "stack trace" in hint

    err_type, recoverable, hint = PhaseExecutor._classify_error("AttributeError: object has no attribute 'get'")
    assert err_type == ErrorType.INTERNAL_FAILURE.value
    assert recoverable is True
    assert "stack trace" in hint


def test_collection_phase_runs_agents_in_parallel(empty_environment, monkeypatch):
    """信息收集阶段应并发执行基础 Agent。"""
    sleep_seconds = 0.3

    monkeypatch.setattr(
        "src.core.phase_executor.get_config",
        lambda: SimpleNamespace(scheduler=SimpleNamespace(max_concurrent=4)),
    )

    def _agent_factory(agent_type: str, name: str):
        class _FakeAgent:
            def __init__(self, environment=None, search_tool=None):
                self.name = name
                self.agent_type = type("AgentTypeStub", (), {"value": agent_type})()

            def execute(self, **context):
                time.sleep(sleep_seconds)
                return _result(agent_type=agent_type, content=context.get("target", "unknown"))

        return _FakeAgent

    monkeypatch.setattr("src.core.phase_executor.ScoutAgent", _agent_factory("scout", "侦察专家"))
    monkeypatch.setattr("src.core.phase_executor.ExperienceAgent", _agent_factory("experience", "体验专家"))
    monkeypatch.setattr("src.core.phase_executor.TechnicalAgent", _agent_factory("technical", "技术分析专家"))
    monkeypatch.setattr("src.core.phase_executor.MarketAgent", _agent_factory("market", "市场分析专家"))

    executor = PhaseExecutor(environment=empty_environment)

    start = time.perf_counter()
    result = executor._execute_collection_phase(
        context={"target": "Notion"},
        search_tool=object(),
    )
    elapsed = time.perf_counter() - start

    assert result.success is True
    assert result.metadata["parallel_execution"] is True
    assert result.metadata["max_workers"] == 4
    assert elapsed < 1.0


def test_collection_phase_uses_sync_execute_path(empty_environment, monkeypatch):
    """信息收集阶段在 executor 线程中应走同步 execute 路径。"""
    class _SyncOnlyAgent:
        def __init__(self, environment=None, search_tool=None):
            self.name = "异步 Agent"
            self.agent_type = type("AgentTypeStub", (), {"value": "scout"})()

        def execute(self, **context):
            return _result(agent_type="scout", content=context.get("target", "unknown"))

        async def execute_async(self, **context):
            raise AssertionError("execute_async should not be called in collection phase")

    monkeypatch.setattr("src.core.phase_executor.ScoutAgent", _SyncOnlyAgent)
    monkeypatch.setattr("src.core.phase_executor.ExperienceAgent", _SyncOnlyAgent)
    monkeypatch.setattr("src.core.phase_executor.TechnicalAgent", _SyncOnlyAgent)
    monkeypatch.setattr("src.core.phase_executor.MarketAgent", _SyncOnlyAgent)

    executor = PhaseExecutor(environment=empty_environment)
    result = executor._execute_collection_phase(
        context={"target": "Notion"},
        search_tool=object(),
    )

    assert result.success is True
    assert len(result.agent_results) == 4


def test_debate_phase_runs_multiple_rounds_and_notifies_agents(empty_environment, monkeypatch):
    """辩论阶段应按轮次执行红蓝队并触发回调。"""
    started_agents: list[str] = []
    red_calls: list[dict] = []
    blue_calls: list[dict] = []
    sentinel_search_tool = object()

    class _RedAgent:
        def __init__(self, environment=None, search_tool=None):
            self.name = "红队专家"
            self.environment = environment
            self.search_tool = search_tool

        def execute(self, **context):
            red_calls.append({"search_tool": self.search_tool, "context": context})
            return _result("red_team", content="red point")

    class _BlueAgent:
        def __init__(self, environment=None, search_tool=None):
            self.name = "蓝队专家"
            self.environment = environment
            self.search_tool = search_tool

        def execute(self, **context):
            blue_calls.append({"search_tool": self.search_tool, "context": context})
            return _result("blue_team", content="blue point")

    monkeypatch.setattr("src.core.phase_executor.RedTeamAgent", _RedAgent)
    monkeypatch.setattr("src.core.phase_executor.BlueTeamAgent", _BlueAgent)

    executor = PhaseExecutor(
        environment=empty_environment,
        debate_rounds=3,
        on_agent_start=lambda name: started_agents.append(name),
    )

    result = executor._execute_debate_phase(
        context={"target": "Notion"},
        search_tool=sentinel_search_tool,
    )

    assert result.success is True
    assert result.metadata["debate_rounds"] == 3
    assert len(result.agent_results) == 6
    assert len(red_calls) == 3
    assert len(blue_calls) == 3
    assert all(call["search_tool"] is sentinel_search_tool for call in red_calls)
    assert all(call["search_tool"] is sentinel_search_tool for call in blue_calls)
    assert result.success is True
    assert started_agents == [
        "红队专家",
        "蓝队专家",
        "红队专家",
        "蓝队专家",
        "红队专家",
        "蓝队专家",
    ]


@pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
def test_validation_phase_applies_weighted_strategy(empty_environment):
    """交叉验证应按加权分数和阈值筛选并提升强度。"""
    passing_signal = Signal(
        id="signal-pass",
        signal_type=SignalType.INSIGHT,
        dimension=Dimension.PRODUCT,
        evidence="Pricing model is clear and transparent",
        confidence=0.8,
        strength=0.4,
        sentiment=Sentiment.NEUTRAL,
        actionability=Actionability.INFORMATIONAL,
        author_agent="scout",
    )
    filtered_signal = Signal(
        id="signal-filtered",
        signal_type=SignalType.INSIGHT,
        dimension=Dimension.PRODUCT,
        evidence="Pricing may be confusing",
        confidence=0.4,
        strength=0.1,
        sentiment=Sentiment.NEUTRAL,
        actionability=Actionability.INFORMATIONAL,
        author_agent="scout",
    )
    empty_environment.add_signal(passing_signal)
    empty_environment.add_signal(filtered_signal)

    executor = PhaseExecutor(
        environment=empty_environment,
        min_confidence=0.5,
        min_strength=0.2,
        min_weighted_score=0.5,
        confidence_weight=0.7,
        strength_weight=0.3,
        verification_boost=0.1,
    )

    result = executor._execute_validation_phase(context={})
    updated_passing_signal = empty_environment.get_signal("signal-pass")
    updated_filtered_signal = empty_environment.get_signal("signal-filtered")

    assert result.metadata["verified_count"] >= 1
    assert result.metadata["filtered_count"] >= 1
    assert updated_passing_signal.verified is True
    assert updated_passing_signal.strength > passing_signal.strength
    assert updated_filtered_signal.verified is False


@pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
def test_debate_strength_adjustment_uses_relevance(empty_environment):
    """辩论强度调整应基于观点相关性并写回环境。"""
    signal = Signal(
        id="signal-debate",
        signal_type=SignalType.INSIGHT,
        dimension=Dimension.MARKET,
        evidence="pricing strategy is expensive for startups",
        confidence=0.8,
        strength=0.6,
        sentiment=Sentiment.NEGATIVE,
        actionability=Actionability.SHORT_TERM,
        author_agent="market",
        verified=True,
    )
    empty_environment.add_signal(signal)

    executor = PhaseExecutor(
        environment=empty_environment,
        debate_strength_step=0.1,
        debate_round_decay=1.0,
        debate_max_adjustment=0.2,
        debate_verified_only=True,
    )

    stats = executor._update_signal_strengths_from_debate(
        red_arguments=[["pricing too expensive", "high pricing hurts adoption"]],
        blue_arguments=[["excellent user experience"]],
    )
    updated_signal = empty_environment.get_signal("signal-debate")

    assert stats["adjusted_signals"] == 1
    assert stats["total_delta"] < 0
    assert updated_signal.strength < signal.strength
    assert updated_signal.verified is True


def test_create_phase_executor_reads_strategy_from_config(monkeypatch):
    """工厂函数应从配置注入 phase strategy。"""
    config = SimpleNamespace(
        phase_executor=SimpleNamespace(
            validation=SimpleNamespace(
                min_confidence=0.55,
                min_strength=0.25,
                confidence_weight=0.6,
                strength_weight=0.4,
                min_weighted_score=0.5,
                max_signals_per_dimension=12,
                verification_boost=0.08,
            ),
            debate=SimpleNamespace(
                rounds=4,
                strength_step=0.12,
                round_decay=0.9,
                max_adjustment=0.3,
                max_points_per_round=7,
                verified_only=False,
                llm_batch_size=7,
                llm_max_tokens=96,
                llm_temperature=0.0,
            ),
        ),
    )
    monkeypatch.setattr("src.core.phase_executor.get_config", lambda: config)

    executor = create_phase_executor()

    assert executor._validation_strategy.min_confidence == 0.55
    assert executor._validation_strategy.min_strength == 0.25
    assert executor._validation_strategy.max_signals_per_dimension == 12
    assert executor._debate_strategy.rounds == 4
    assert executor._debate_strategy.strength_step == 0.12
    assert executor._debate_strategy.max_points_per_round == 7
    assert executor._debate_strategy.verified_only is False
    assert executor._debate_llm_batch_size == 7
    assert executor._debate_llm_max_tokens == 96
    assert executor._debate_llm_temperature == 0.0


def test_create_phase_executor_reads_quantitative_validation_switch(monkeypatch):
    """工厂函数应读取定量验证开关与容差。"""
    config = SimpleNamespace(
        phase_executor=SimpleNamespace(
            validation=SimpleNamespace(
                min_confidence=0.3,
                min_strength=0.0,
                confidence_weight=0.7,
                strength_weight=0.3,
                min_weighted_score=0.35,
                max_signals_per_dimension=20,
                verification_boost=0.03,
                enable_quantitative_validation=False,
                quantitative_tolerance_threshold=0.11,
            ),
            debate=SimpleNamespace(
                rounds=2,
                strength_step=0.05,
                round_decay=0.85,
                max_adjustment=0.2,
                max_points_per_round=10,
                verified_only=True,
                llm_batch_size=10,
                llm_max_tokens=128,
                llm_temperature=0.0,
            ),
        ),
    )
    monkeypatch.setattr("src.core.phase_executor.get_config", lambda: config)

    executor = create_phase_executor()

    assert executor._enable_quantitative_validation is False
    assert executor._quantitative_extractor is None
    assert executor._quantitative_validator is None


@pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
def test_validation_threshold_sensitivity_changes_verified_count(empty_environment):
    """更严格的验证阈值应减少通过数量。"""
    signals = [
        Signal(
            id="signal-sensitivity-1",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.PRODUCT,
            evidence="product pricing clarity for enterprise users",
            confidence=0.85,
            strength=0.65,
            sentiment=Sentiment.NEUTRAL,
            actionability=Actionability.INFORMATIONAL,
            author_agent="scout",
        ),
        Signal(
            id="signal-sensitivity-2",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.PRODUCT,
            evidence="product onboarding has moderate friction",
            confidence=0.55,
            strength=0.35,
            sentiment=Sentiment.NEUTRAL,
            actionability=Actionability.SHORT_TERM,
            author_agent="scout",
        ),
        Signal(
            id="signal-sensitivity-3",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.PRODUCT,
            evidence="product support response may be slow",
            confidence=0.3,
            strength=0.2,
            sentiment=Sentiment.NEGATIVE,
            actionability=Actionability.SHORT_TERM,
            author_agent="scout",
        ),
    ]

    lenient_env = empty_environment
    strict_env = type(lenient_env)(cache_path="test_cache_strict")
    for signal in signals:
        lenient_env.add_signal(signal)
        strict_env.add_signal(signal)

    lenient_executor = PhaseExecutor(
        environment=lenient_env,
        min_confidence=0.2,
        min_strength=0.1,
        min_weighted_score=0.2,
    )
    strict_executor = PhaseExecutor(
        environment=strict_env,
        min_confidence=0.8,
        min_strength=0.6,
        min_weighted_score=0.8,
    )

    lenient_result = lenient_executor._execute_validation_phase(context={})
    strict_result = strict_executor._execute_validation_phase(context={})

    assert lenient_result.metadata["verified_count"] > strict_result.metadata["verified_count"]


@pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
def test_validation_phase_handles_quantitative_signals_without_signal_nameerror(empty_environment):
    """包含数字证据时，验证阶段不应再出现 `Signal is not defined`。"""
    product_signal = Signal(
        id="signal-quant-product",
        signal_type=SignalType.INSIGHT,
        dimension=Dimension.PRODUCT,
        evidence="conversion increased by 20% in Q4",
        confidence=0.82,
        strength=0.65,
        sentiment=Sentiment.POSITIVE,
        actionability=Actionability.SHORT_TERM,
        author_agent="scout",
    )
    market_signal = Signal(
        id="signal-quant-market",
        signal_type=SignalType.OPPORTUNITY,
        dimension=Dimension.MARKET,
        evidence="market share reached 12.5% this year",
        confidence=0.84,
        strength=0.62,
        sentiment=Sentiment.POSITIVE,
        actionability=Actionability.SHORT_TERM,
        author_agent="market",
    )
    empty_environment.add_signal(product_signal)
    empty_environment.add_signal(market_signal)

    executor = PhaseExecutor(environment=empty_environment)
    result = executor._execute_validation_phase(context={})

    assert result.metadata["verified_count"] >= 1
    assert all("signal' is not defined" not in str(err.get("error", "")).lower() for err in result.errors)


@pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
def test_validation_phase_continues_on_single_signal_error(empty_environment, monkeypatch):
    """单个 signal 异常不应拖垮整个维度。"""
    good_signal = Signal(
        id="signal-good",
        signal_type=SignalType.INSIGHT,
        dimension=Dimension.PRODUCT,
        evidence="enterprise conversion improved by 18%",
        confidence=0.81,
        strength=0.61,
        sentiment=Sentiment.POSITIVE,
        actionability=Actionability.SHORT_TERM,
        author_agent="scout",
    )
    bad_signal = Signal(
        id="signal-bad",
        signal_type=SignalType.INSIGHT,
        dimension=Dimension.PRODUCT,
        evidence="retention fell by 7%",
        confidence=0.8,
        strength=0.6,
        sentiment=Sentiment.NEGATIVE,
        actionability=Actionability.SHORT_TERM,
        author_agent="scout",
    )
    empty_environment.add_signal(good_signal)
    empty_environment.add_signal(bad_signal)

    executor = PhaseExecutor(environment=empty_environment)
    real_impl = executor._apply_quantitative_validation

    def _flaky_apply_quantitative_validation(signal, all_signals):
        if signal.id == "signal-bad":
            raise TypeError("simulated metric extraction failure")
        return real_impl(signal, all_signals)

    monkeypatch.setattr(
        executor,
        "_apply_quantitative_validation",
        _flaky_apply_quantitative_validation,
    )

    result = executor._execute_validation_phase(context={})

    assert result.metadata["dimension_summary"]["product"]["verified_count"] >= 1
    assert any(err.get("error_type") == ErrorType.INTERNAL_FAILURE.value for err in result.errors)


@pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
def test_debate_step_sensitivity_changes_adjustment_strength():
    """更高辩论步长应产生更明显的强度调整。"""
    base_signal = Signal(
        id="signal-step-sensitivity",
        signal_type=SignalType.INSIGHT,
        dimension=Dimension.MARKET,
        evidence="pricing strategy is expensive for startups",
        confidence=0.85,
        strength=0.7,
        sentiment=Sentiment.NEGATIVE,
        actionability=Actionability.SHORT_TERM,
        author_agent="market",
        verified=True,
    )

    from src.environment import StigmergyEnvironment

    zero_step_env = StigmergyEnvironment(cache_path="test_cache_step_zero")
    high_step_env = StigmergyEnvironment(cache_path="test_cache_step_high")
    zero_step_env.add_signal(base_signal)
    high_step_env.add_signal(base_signal)

    zero_step_executor = PhaseExecutor(
        environment=zero_step_env,
        debate_strength_step=0.0,
    )
    high_step_executor = PhaseExecutor(
        environment=high_step_env,
        debate_strength_step=0.12,
    )

    red_rounds = [["pricing too expensive", "high pricing hurts adoption"]]
    blue_rounds = [["strong collaboration feature"]]

    zero_stats = zero_step_executor._update_signal_strengths_from_debate(red_rounds, blue_rounds)
    high_stats = high_step_executor._update_signal_strengths_from_debate(red_rounds, blue_rounds)

    zero_signal = zero_step_env.get_signal("signal-step-sensitivity")
    high_signal = high_step_env.get_signal("signal-step-sensitivity")

    assert zero_stats["adjusted_signals"] == 0
    assert zero_signal.strength == 0.7
    assert high_stats["adjusted_signals"] >= 1
    assert high_signal.strength < zero_signal.strength


def test_debate_llm_batch_adjudication_avoids_duplicate_evaluations(empty_environment, monkeypatch):
    """批量裁决应利用缓存，避免对同一 claim 重复请求 LLM。"""

    class _RedAgent:
        def __init__(self, environment=None, search_tool=None):
            self.name = "红队专家"

        def execute(self, **context):
            discoveries = [{"content": f"red point {idx}"} for idx in range(10)]
            return AgentResult(
                agent_type="red_team",
                agent_name="red_team",
                discoveries=discoveries,
                handoffs_created=0,
                metadata={},
            )

    class _BlueAgent:
        def __init__(self, environment=None, search_tool=None):
            self.name = "蓝队专家"

        def execute(self, **context):
            discoveries = [{"content": f"blue point {idx}"} for idx in range(10)]
            return AgentResult(
                agent_type="blue_team",
                agent_name="blue_team",
                discoveries=discoveries,
                handoffs_created=0,
                metadata={},
            )

    class _FakeLLMClient:
        def chat(self, messages, **kwargs):
            prompt = messages[0].content
            claim_ids = re.findall(r"claim_id:\s*([^\n]+)", prompt)
            payload = {
                "results": [
                    {"claim_id": claim_id.strip(), "verdict": "UNCERTAIN"}
                    for claim_id in claim_ids
                ]
            }
            return SimpleNamespace(content=json.dumps(payload))

    monkeypatch.setattr("src.core.phase_executor.RedTeamAgent", _RedAgent)
    monkeypatch.setattr("src.core.phase_executor.BlueTeamAgent", _BlueAgent)

    executor = PhaseExecutor(
        environment=empty_environment,
        debate_rounds=2,
        debate_llm_adjudication=True,
        debate_llm_batch_size=10,
        debate_llm_max_tokens=128,
        debate_llm_temperature=0.0,
    )
    executor._debate_llm_client = _FakeLLMClient()
    monkeypatch.setattr(executor, "_rule_score_claim", lambda claim, claim_by_id: 0.0)

    result = executor._execute_debate_phase(context={"target": "Notion"})
    strategy = result.metadata["strategy"]

    assert result.metadata["claim_count"] == 40
    assert strategy["llm_batch_calls"] == 4
    assert strategy["llm_claim_evaluations"] == 40
    assert strategy["llm_cache_hits"] >= 20


def test_debate_llm_batch_invalid_payload_falls_back_to_uncertain(empty_environment):
    """批量裁决返回非法内容时应降级为 UNCERTAIN。"""

    class _BrokenLLMClient:
        def chat(self, messages, **kwargs):
            return SimpleNamespace(content="NOT_JSON_PAYLOAD")

    executor = PhaseExecutor(
        environment=empty_environment,
        debate_rounds=1,
        debate_llm_adjudication=True,
        debate_llm_batch_size=10,
    )
    executor._debate_llm_client = _BrokenLLMClient()

    claim = phase_executor_module.DebateClaim(
        claim_id="claim-1",
        side="red",
        round=1,
        text="Some uncertain claim",
    )
    verdicts = executor._llm_adjudicate_claims_batch([claim], {"claim-1": claim})

    assert verdicts["claim-1"] == "UNCERTAIN"
