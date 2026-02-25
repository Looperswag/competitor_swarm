"""四阶段执行引擎模块。

实现 Agent Swarm 框架的核心执行流程：
1. Information Collection - 信息收集阶段
2. Cross Validation - 交叉验证阶段
3. Adversarial Debate - 对抗辩论阶段
4. Report Synthesis - 报告综合阶段
"""

import asyncio
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from src.agents.base import AgentType, AgentResult, BaseAgent
from src.agents.scout import ScoutAgent
from src.agents.experience import ExperienceAgent
from src.agents.technical import TechnicalAgent
from src.agents.market import MarketAgent
from src.agents.red_team import RedTeamAgent
from src.agents.blue_team import BlueTeamAgent
from src.agents.elite import EliteAgent
from src.environment import StigmergyEnvironment, get_environment
from src.error_types import ErrorType
from src.llm import Message, get_client
from src.utils.config import get_config
from src.analysis.quantitative import (
    QuantitativeExtractor,
    QuantitativeValidator,
    ExtractedNumber,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

# 尝试导入 Signal 结构
try:
    from src.schemas.signals import (
        Signal,
        Dimension,
        Sentiment,
        Actionability,
    )
    SIGNALS_AVAILABLE = True
except ImportError:
    SIGNALS_AVAILABLE = False
    # 创建 Dimension 占位符以支持代码
    class Dimension:
        PRODUCT = "product"
        UX = "ux"
        TECHNICAL = "technical"
        MARKET = "market"


class Phase(str, Enum):
    """执行阶段枚举。"""

    COLLECTION = "collection"  # 信息收集阶段
    VALIDATION = "validation"  # 交叉验证阶段
    DEBATE = "debate"  # 对抗辩论阶段
    SYNTHESIS = "synthesis"  # 报告综合阶段


@dataclass
class PhaseProgress:
    """阶段进度。

    跟踪执行过程中的进度信息。
    """

    current_phase: Phase
    completed_phases: list[Phase] = field(default_factory=list)
    phase_start_time: float = 0.0
    total_duration: float = 0.0
    signals_per_phase: dict[Phase, int] = field(default_factory=dict)
    agent_results: dict[Phase, list[AgentResult]] = field(default_factory=dict)
    phase_errors: dict[Phase, list[Any]] = field(default_factory=dict)
    phase_metadata: dict[Phase, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "current_phase": self.current_phase.value,
            "completed_phases": [p.value for p in self.completed_phases],
            "phase_start_time": self.phase_start_time,
            "total_duration": self.total_duration,
            "signals_per_phase": {p.value: c for p, c in self.signals_per_phase.items()},
            "phase_errors": {p.value: e for p, e in self.phase_errors.items()},
            "phase_metadata": {p.value: m for p, m in self.phase_metadata.items()},
        }


@dataclass
class PhaseResult:
    """阶段执行结果。"""

    phase: Phase
    success: bool
    duration: float
    signal_count: int = 0
    agent_results: list[AgentResult] = field(default_factory=list)
    errors: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "phase": self.phase.value,
            "success": self.success,
            "duration": self.duration,
            "signal_count": self.signal_count,
            "agent_count": len(self.agent_results),
            "errors": self.errors,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ValidationStrategy:
    """交叉验证策略。"""

    min_confidence: float = 0.3
    min_strength: float = 0.0
    confidence_weight: float = 0.7
    strength_weight: float = 0.3
    min_weighted_score: float = 0.35
    max_signals_per_dimension: int = 20
    verification_boost: float = 0.03


@dataclass(frozen=True)
class DebateStrategy:
    """辩论阶段策略。"""

    rounds: int = 3
    strength_step: float = 0.05
    round_decay: float = 0.85
    max_adjustment: float = 0.2
    max_points_per_round: int = 10
    verified_only: bool = True


class DebateVerdict(str, Enum):
    """Claim 裁决标签。"""

    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    REFUTED = "REFUTED"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class DebateClaim:
    """结构化辩论 claim。"""

    claim_id: str
    side: str
    round: int
    text: str
    evidence_signal_ids: list[str] = field(default_factory=list)
    reply_to_claim_ids: list[str] = field(default_factory=list)
    target_dimensions: list[str] = field(default_factory=list)
    confidence: float = 0.5
    rule_score: float = 0.0
    verdict: str = DebateVerdict.UNCERTAIN.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "side": self.side,
            "round": self.round,
            "text": self.text,
            "evidence_signal_ids": list(self.evidence_signal_ids),
            "reply_to_claim_ids": list(self.reply_to_claim_ids),
            "target_dimensions": list(self.target_dimensions),
            "confidence": self.confidence,
            "rule_score": self.rule_score,
            "verdict": self.verdict,
        }


@dataclass
class DebateTranscript:
    """多轮辩论结构化记录。"""

    transcript_id: str
    claims: list[DebateClaim] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcript_id": self.transcript_id,
            "claims": [claim.to_dict() for claim in self.claims],
        }


class PhaseExecutor:
    """四阶段执行引擎。

    实现新的 Agent Swarm 执行流程，替代原有的 Coordinator 逻辑。

    流程：
    1. Collection: 并发执行 Scout、Experience、Technical、Market Agent
    2. Validation: 按维度交叉验证信号
    3. Debate: Red/Blue Team 多轮对抗辩论
    4. Synthesis: Elite Agent 综合生成报告
    """

    # 维度到 Agent 的映射
    DIMENSION_AGENTS = {
        "product": AgentType.SCOUT,
        "ux": AgentType.EXPERIENCE,
        "technical": AgentType.TECHNICAL,
        "market": AgentType.MARKET,
    }

    # 验证 Agent 映射（维度 -> 验证者）
    VALIDATOR_AGENTS = {
        "product": AgentType.EXPERIENCE,  # Experience 验证 Product
        "ux": AgentType.TECHNICAL,  # Technical 验证 UX
        "technical": AgentType.SCOUT,  # Scout 验证 Technical
        "market": AgentType.SCOUT,  # Scout 验证 Market
    }

    # 默认配置
    DEFAULT_DEBATE_ROUNDS: int = 3
    MIN_CONFIDENCE_THRESHOLD: float = 0.3
    MIN_SIGNALS_PER_AGENT: int = 5

    def __init__(
        self,
        environment: StigmergyEnvironment | None = None,
        debate_rounds: int = 3,
        min_confidence: float = 0.3,
        min_strength: float = 0.0,
        min_weighted_score: float = 0.35,
        confidence_weight: float = 0.7,
        strength_weight: float = 0.3,
        max_signals_per_dimension: int = 20,
        verification_boost: float = 0.03,
        enable_quantitative_validation: bool = True,
        quantitative_tolerance_threshold: float = 0.2,
        debate_strength_step: float = 0.05,
        debate_round_decay: float = 0.85,
        debate_max_adjustment: float = 0.2,
        max_points_per_round: int = 10,
        debate_verified_only: bool = True,
        debate_rule_score_threshold: float = 0.35,
        debate_llm_uncertainty_threshold: float = 0.15,
        debate_llm_adjudication: bool = False,
        debate_llm_batch_size: int = 10,
        debate_llm_max_tokens: int = 128,
        debate_llm_temperature: float = 0.0,
        progress_callback: Callable[[PhaseProgress], None] | None = None,
        on_agent_start: Callable[[str], None] | None = None,
    ) -> None:
        """初始化阶段执行器。

        Args:
            environment: 共享环境
            debate_rounds: 辩论轮数
            min_confidence: 最低置信度阈值
            progress_callback: 进度回调函数
        """
        self._environment = environment or get_environment()
        self._validation_strategy = ValidationStrategy(
            min_confidence=max(0.0, min(1.0, min_confidence)),
            min_strength=max(0.0, min(1.0, min_strength)),
            confidence_weight=max(0.0, confidence_weight),
            strength_weight=max(0.0, strength_weight),
            min_weighted_score=max(0.0, min(1.0, min_weighted_score)),
            max_signals_per_dimension=max(1, max_signals_per_dimension),
            verification_boost=max(0.0, min(0.5, verification_boost)),
        )
        self._debate_strategy = DebateStrategy(
            rounds=max(1, debate_rounds),
            strength_step=max(0.0, min(0.5, debate_strength_step)),
            round_decay=max(0.0, min(1.0, debate_round_decay)),
            max_adjustment=max(0.0, min(1.0, debate_max_adjustment)),
            max_points_per_round=max(1, max_points_per_round),
            verified_only=debate_verified_only,
        )
        self._debate_rounds = self._debate_strategy.rounds
        self._debate_rule_score_threshold = max(0.0, min(1.0, debate_rule_score_threshold))
        self._debate_llm_uncertainty_threshold = max(0.0, min(1.0, debate_llm_uncertainty_threshold))
        self._debate_llm_adjudication = bool(debate_llm_adjudication)
        self._debate_llm_batch_size = max(1, int(debate_llm_batch_size))
        self._debate_llm_max_tokens = max(32, int(debate_llm_max_tokens))
        self._debate_llm_temperature = max(0.0, min(1.0, float(debate_llm_temperature)))
        self._debate_llm_client = None
        if self._debate_llm_adjudication and os.getenv("ZHIPUAI_API_KEY", "").strip():
            try:
                self._debate_llm_client = get_client()
            except Exception:
                self._debate_llm_client = None
        self._debate_verdict_cache: dict[str, str] = {}
        self._debate_llm_batch_calls = 0
        self._debate_llm_claim_evaluations = 0
        self._debate_llm_cache_hits = 0
        self._min_confidence = self._validation_strategy.min_confidence
        self._progress_callback = progress_callback
        self._on_agent_start = on_agent_start

        # 定量数据验证组件
        self._enable_quantitative_validation = enable_quantitative_validation
        self._quantitative_extractor = QuantitativeExtractor() if enable_quantitative_validation else None
        self._quantitative_validator = QuantitativeValidator(
            tolerance_threshold=quantitative_tolerance_threshold
        ) if enable_quantitative_validation else None

        self._progress = PhaseProgress(current_phase=Phase.COLLECTION)

    def execute(
        self,
        target: str,
        competitors: list[str] | None = None,
        focus_areas: list[str] | None = None,
        search_tool: Any = None,
    ) -> PhaseProgress:
        """执行完整的四阶段流程。

        Args:
            target: 目标产品/公司
            competitors: 竞品列表
            focus_areas: 重点关注领域
            search_tool: 搜索工具

        Returns:
            最终进度状态
        """
        start_time = time.time()
        self._debate_verdict_cache = {}
        self._debate_llm_batch_calls = 0
        self._debate_llm_claim_evaluations = 0
        self._debate_llm_cache_hits = 0

        context = {
            "target": target,
            "competitors": competitors or [],
            "focus_areas": focus_areas or [],
        }

        try:
            # Phase 1: Information Collection
            collection_result = self._execute_collection_phase(context, search_tool)
            self._progress.completed_phases.append(Phase.COLLECTION)
            self._progress.signals_per_phase[Phase.COLLECTION] = collection_result.signal_count
            self._progress.agent_results[Phase.COLLECTION] = collection_result.agent_results
            self._progress.phase_errors[Phase.COLLECTION] = collection_result.errors
            self._progress.phase_metadata[Phase.COLLECTION] = collection_result.metadata

            # Phase 2: Cross Validation
            validation_result = self._execute_validation_phase(context)
            self._progress.completed_phases.append(Phase.VALIDATION)
            self._progress.signals_per_phase[Phase.VALIDATION] = validation_result.signal_count
            self._progress.agent_results[Phase.VALIDATION] = validation_result.agent_results
            self._progress.phase_errors[Phase.VALIDATION] = validation_result.errors
            self._progress.phase_metadata[Phase.VALIDATION] = validation_result.metadata

            # Phase 3: Adversarial Debate
            debate_result = self._execute_debate_phase(
                context,
                search_tool=search_tool,
            )
            self._progress.completed_phases.append(Phase.DEBATE)
            self._progress.signals_per_phase[Phase.DEBATE] = debate_result.signal_count
            self._progress.agent_results[Phase.DEBATE] = debate_result.agent_results
            self._progress.phase_errors[Phase.DEBATE] = debate_result.errors
            self._progress.phase_metadata[Phase.DEBATE] = debate_result.metadata

            # Phase 4: Report Synthesis
            synthesis_result = self._execute_synthesis_phase(
                context,
                search_tool=search_tool,
            )
            self._progress.completed_phases.append(Phase.SYNTHESIS)
            self._progress.signals_per_phase[Phase.SYNTHESIS] = synthesis_result.signal_count
            self._progress.agent_results[Phase.SYNTHESIS] = synthesis_result.agent_results
            self._progress.phase_errors[Phase.SYNTHESIS] = synthesis_result.errors
            self._progress.phase_metadata[Phase.SYNTHESIS] = synthesis_result.metadata

            self._progress.total_duration = time.time() - start_time
            self._progress.current_phase = Phase.SYNTHESIS

            return self._progress

        except Exception as e:
            self._progress.total_duration = time.time() - start_time
            # 记录错误但不抛出异常
            self._progress.agent_results[self._progress.current_phase] = [
                AgentResult(
                    agent_type="executor",
                    agent_name="PhaseExecutor",
                    discoveries=[],
                    handoffs_created=0,
                    metadata={"error": str(e)},
                )
            ]
            self._progress.phase_errors[self._progress.current_phase] = [str(e)]
            self._progress.phase_metadata[self._progress.current_phase] = {
                "error": str(e),
                "error_type": self._classify_error(e)[0],
            }
            return self._progress

    def _notify_agent_start(self, agent: Any) -> None:
        """通知外部 Agent 启动事件。"""
        if not self._on_agent_start:
            return
        try:
            self._on_agent_start(getattr(agent, "name", "unknown"))
        except Exception:
            pass

    @staticmethod
    def _classify_error(error: Exception | str) -> tuple[str, bool, str]:
        """Classify runtime errors for downstream observability."""
        if isinstance(error, (NameError, AttributeError, TypeError)):
            return (
                ErrorType.INTERNAL_FAILURE.value,
                True,
                "Inspect code regression and stack trace.",
            )

        text = str(error).lower()
        if "is not defined" in text or "nameerror" in text or "attributeerror" in text or "typeerror" in text:
            return (
                ErrorType.INTERNAL_FAILURE.value,
                True,
                "Inspect code regression and stack trace.",
            )
        if "timeout" in text or "timed out" in text:
            return (
                ErrorType.UPSTREAM_TIMEOUT.value,
                True,
                "Try increasing timeout or reducing request fan-out.",
            )
        if "rate limit" in text or "429" in text:
            return (
                ErrorType.UPSTREAM_RATE_LIMIT.value,
                True,
                "Retry with backoff or lower request concurrency.",
            )
        if "parse" in text or "json" in text:
            return (
                ErrorType.PARSE_FAILURE.value,
                True,
                "Validate parser assumptions and fallback path.",
            )
        if "empty" in text and "output" in text:
            return (
                ErrorType.EMPTY_OUTPUT.value,
                True,
                "Strengthen prompt constraints and fallback handling.",
            )
        return (
            ErrorType.SEARCH_FAILURE.value,
            True,
            "Inspect upstream provider availability and error logs.",
        )

    def _build_error_item(
        self,
        *,
        phase: Phase,
        error: Exception | str,
        agent_type: str | None = None,
        claim_id: str | None = None,
        evidence_signal_ids: list[str] | None = None,
        verdict: str | None = None,
    ) -> dict[str, Any]:
        """Build structured error payload while preserving compatibility."""
        error_type, recoverable, hint = self._classify_error(error)
        payload: dict[str, Any] = {
            "phase": phase.value,
            "error": str(error),
            "error_type": error_type,
            "recoverable": recoverable,
            "hint": hint,
        }
        if agent_type:
            payload["agent_type"] = agent_type
        if claim_id:
            payload["claim_id"] = claim_id
        if evidence_signal_ids:
            payload["evidence_signal_ids"] = list(evidence_signal_ids)
        if verdict:
            payload["verdict"] = verdict
        return payload

    @staticmethod
    def _execute_agent_with_async_support(agent: Any, context: dict[str, Any]) -> Any:
        """在 ThreadPoolExecutor 中执行 Agent。

        始终走同步路径。在 ThreadPoolExecutor 线程中调用 asyncio.run() 会创建
        临时事件循环，导致模块级 asyncio.Semaphore 跨循环使用而报错：
        "Semaphore is bound to a different event loop"。
        同步 execute() 的功能与 execute_async() 完全一致，不影响结果质量。
        """
        return agent.execute(**context)

    def _execute_collection_phase(
        self,
        context: dict[str, Any],
        search_tool: Any,
    ) -> PhaseResult:
        """执行信息收集阶段（Phase 1）。

        并发执行 Scout、Experience、Technical、Market Agent。
        每个 Agent 创建带有初始置信度和强度的信号。

        Args:
            context: 执行上下文
            search_tool: 搜索工具

        Returns:
            阶段结果
        """
        start_time = time.time()
        self._progress.current_phase = Phase.COLLECTION
        self._progress.phase_start_time = start_time

        if self._progress_callback:
            self._progress_callback(self._progress)

        # 创建基础 Agent
        agents = [
            ScoutAgent(environment=self._environment, search_tool=search_tool),
            ExperienceAgent(environment=self._environment, search_tool=search_tool),
            TechnicalAgent(environment=self._environment, search_tool=search_tool),
            MarketAgent(environment=self._environment, search_tool=search_tool),
        ]

        agent_results = []
        errors = []
        max_workers = min(len(agents), max(1, get_config().scheduler.max_concurrent))
        submitted_tasks: list[tuple[Any, Any]] = []

        # 并发执行每个 Agent，保留固定回调触发顺序。
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for agent in agents:
                self._notify_agent_start(agent)
                submitted_tasks.append(
                    (
                        agent,
                        executor.submit(
                            self._execute_agent_with_async_support,
                            agent,
                            dict(context),
                        ),
                    )
                )

            for agent, future in submitted_tasks:
                try:
                    result = future.result()
                    agent_results.append(result)
                except Exception as e:
                    errors.append(
                        self._build_error_item(
                            phase=Phase.COLLECTION,
                            error=e,
                            agent_type=agent.agent_type.value,
                        )
                    )

        # 统计信号数量
        signal_count = self._environment.signal_count if SIGNALS_AVAILABLE else self._environment.discovery_count

        return PhaseResult(
            phase=Phase.COLLECTION,
            success=len(errors) == 0,
            duration=time.time() - start_time,
            signal_count=signal_count,
            agent_results=agent_results,
            errors=errors,
            metadata={
                "agents_executed": len(agents),
                "parallel_execution": True,
                "max_workers": max_workers,
            },
        )

    def _execute_validation_phase(
        self,
        context: dict[str, Any],
    ) -> PhaseResult:
        """执行交叉验证阶段（Phase 2）。

        按维度顺序验证：
        - 对于每个维度：Primary Agent -> Validator Agent -> 验证
        - 信号标记为 verified=True
        - 低置信度信号被过滤

        Args:
            context: 执行上下文

        Returns:
            阶段结果
        """
        start_time = time.time()
        self._progress.current_phase = Phase.VALIDATION
        self._progress.phase_start_time = start_time

        if self._progress_callback:
            self._progress_callback(self._progress)

        if not SIGNALS_AVAILABLE:
            # 如果 Signal 不可用，跳过验证阶段
            return PhaseResult(
                phase=Phase.VALIDATION,
                success=True,
                duration=time.time() - start_time,
                signal_count=0,
                metadata={"skipped": "Signal schema not available"},
            )

        agent_results = []
        errors: list[Any] = []
        verified_count = 0
        filtered_count = 0
        validation_summary: dict[str, dict[str, Any]] = {}
        quantitative_validation_summary: dict[str, Any] = {
            "metrics_validated": [],
            "quantitative_evidence": [],
            "total_signals_processed": 0,
            "signals_with_quantitative_data": 0,
        }
        total_weight = self._validation_strategy.confidence_weight + self._validation_strategy.strength_weight
        confidence_weight = (
            self._validation_strategy.confidence_weight / total_weight if total_weight > 0 else 0.5
        )
        strength_weight = (
            self._validation_strategy.strength_weight / total_weight if total_weight > 0 else 0.5
        )

        # 按维度验证
        for dimension_name, agent_type in self.DIMENSION_AGENTS.items():
            validator_agent = self.VALIDATOR_AGENTS.get(dimension_name, agent_type).value
            dimension_verified = 0
            dimension_filtered = 0

            try:
                # 获取该维度的信号
                dimension = Dimension[dimension_name.upper()]
                signals = self._environment.get_signals_by_dimension(
                    dimension=dimension,
                    min_confidence=0.0,  # 获取所有信号进行验证
                )
                dimension_signals = self._environment.get_signals_by_dimension(
                    dimension=dimension,
                    min_confidence=0.0,
                )

                if not signals:
                    validation_summary[dimension_name] = {
                        "candidate_count": 0,
                        "verified_count": 0,
                        "filtered_count": 0,
                        "validator": validator_agent,
                    }
                    continue

                candidates = sorted(
                    signals,
                    key=lambda signal: (
                        confidence_weight * signal.confidence + strength_weight * signal.strength
                    ),
                    reverse=True,
                )[: self._validation_strategy.max_signals_per_dimension]

                for signal in candidates:
                    try:
                        weighted_score = confidence_weight * signal.confidence + strength_weight * signal.strength
                        confidence_ok = signal.confidence >= self._validation_strategy.min_confidence
                        strength_ok = signal.strength >= self._validation_strategy.min_strength
                        score_ok = weighted_score >= self._validation_strategy.min_weighted_score

                        if not (confidence_ok and strength_ok and score_ok):
                            filtered_count += 1
                            dimension_filtered += 1
                            continue

                        new_strength = min(
                            1.0,
                            signal.strength + self._validation_strategy.verification_boost,
                        )

                        # 应用定量数据验证（Phase 1 P0 功能）
                        verified_signal, quant_summary = self._apply_quantitative_validation(
                            signal=signal,
                            all_signals=dimension_signals,
                        )

                        # 收集定量验证统计
                        quantitative_validation_summary["total_signals_processed"] += 1
                        if quant_summary.get("metrics_validated"):
                            quantitative_validation_summary["signals_with_quantitative_data"] += 1
                            quantitative_validation_summary["metrics_validated"].extend(
                                quant_summary.get("metrics_validated", [])
                            )
                            quantitative_validation_summary["quantitative_evidence"].extend(
                                quant_summary.get("quantitative_evidence", [])
                            )

                        # 如果定量验证提供了更新的信号，使用它；否则使用标准更新
                        if quant_summary:
                            final_signal = verified_signal
                        else:
                            # 无定量数据，使用标准验证流程
                            final_signal = signal.with_updated_strength(
                                new_strength,
                                verifier=f"validator:{validator_agent}",
                            )

                        self._environment._signals[final_signal.id] = final_signal
                        self._environment.apply_signal_event(
                            final_signal.id,
                            validation_delta=1.0,
                        )
                        verified_count += 1
                        dimension_verified += 1
                    except Exception as e:
                        errors.append(
                            self._build_error_item(
                                phase=Phase.VALIDATION,
                                error=e,
                                agent_type=f"validator_{dimension_name}",
                            )
                        )
                        continue

                validation_summary[dimension_name] = {
                    "candidate_count": len(candidates),
                    "verified_count": dimension_verified,
                    "filtered_count": dimension_filtered,
                    "validator": validator_agent,
                }

            except Exception as e:
                errors.append(
                    self._build_error_item(
                        phase=Phase.VALIDATION,
                        error=e,
                        agent_type=f"validator_{dimension_name}",
                    )
                )
                agent_results.append(
                    AgentResult(
                        agent_type=f"validator_{dimension_name}",
                        agent_name=f"Validator for {dimension_name}",
                        discoveries=[],
                        handoffs_created=0,
                        metadata={"error": str(e)},
                    )
                )

        return PhaseResult(
            phase=Phase.VALIDATION,
            success=True,
            duration=time.time() - start_time,
            signal_count=verified_count,
            agent_results=agent_results,
            errors=errors,
            metadata={
                "verified_count": verified_count,
                "filtered_count": filtered_count,
                "quantitative_validation_enabled": self._enable_quantitative_validation,
                "quantitative_validation": quantitative_validation_summary,
                "strategy": {
                    "min_confidence": self._validation_strategy.min_confidence,
                    "min_strength": self._validation_strategy.min_strength,
                    "min_weighted_score": self._validation_strategy.min_weighted_score,
                    "max_signals_per_dimension": self._validation_strategy.max_signals_per_dimension,
                },
                "dimension_summary": validation_summary,
            },
        )

    def _execute_debate_phase(
        self,
        context: dict[str, Any],
        search_tool: Any = None,
    ) -> PhaseResult:
        """执行对抗辩论阶段（Phase 3）。

        Red Team 攻击信号（找弱点）
        Blue Team 辩护信号（找优势）
        多轮辩论（默认 3 轮）
        信号强度根据辩论结果更新

        Args:
            context: 执行上下文

        Returns:
            阶段结果
        """
        start_time = time.time()
        self._progress.current_phase = Phase.DEBATE
        self._progress.phase_start_time = start_time

        if self._progress_callback:
            self._progress_callback(self._progress)

        agent_results = []
        errors: list[Any] = []
        red_round_arguments: list[list[str]] = []
        blue_round_arguments: list[list[str]] = []
        transcript = DebateTranscript(transcript_id=f"debate-{uuid4()}")
        unresolved_claim_ids: list[str] = []

        # 创建红队
        try:
            red_agent = RedTeamAgent(environment=self._environment, search_tool=search_tool)
            self._notify_agent_start(red_agent)
            red_result = self._execute_agent_with_async_support(red_agent, dict(context))
            red_result.metadata = {
                **(red_result.metadata or {}),
                "debate_transcript_id": transcript.transcript_id,
            }
            agent_results.append(red_result)

            # 收集红队观点
            red_arguments = self._extract_debate_points(red_result)
            red_round_arguments.append(red_arguments)
            round_red_claims = self._build_claims_from_points(
                side="red",
                round_num=1,
                points=red_arguments,
                reply_to_claim_ids=[],
            )
            transcript.claims.extend(round_red_claims)

            # 蓝队接收红队观点
            blue_context = {
                **context,
                "red_team_arguments": red_arguments,
            }
            blue_agent = BlueTeamAgent(environment=self._environment, search_tool=search_tool)
            self._notify_agent_start(blue_agent)
            blue_result = self._execute_agent_with_async_support(blue_agent, dict(blue_context))
            blue_result.metadata = {
                **(blue_result.metadata or {}),
                "debate_transcript_id": transcript.transcript_id,
            }
            agent_results.append(blue_result)

            # 收集蓝队观点
            blue_arguments = self._extract_debate_points(blue_result)
            blue_round_arguments.append(blue_arguments)
            round_blue_claims = self._build_claims_from_points(
                side="blue",
                round_num=1,
                points=blue_arguments,
                reply_to_claim_ids=[claim.claim_id for claim in round_red_claims],
            )
            transcript.claims.extend(round_blue_claims)
            adjudication = self._adjudicate_claims(transcript.claims)
            unresolved_claim_ids = adjudication["unresolved_claim_ids"]

            # 多轮辩论
            for round_num in range(1, self._debate_rounds):
                # 红队反驳
                red_context = {
                    **context,
                    "blue_team_arguments": blue_arguments,
                    "round": round_num + 1,
                }
                self._notify_agent_start(red_agent)
                red_result = self._execute_agent_with_async_support(red_agent, dict(red_context))
                red_result.metadata = {
                    **(red_result.metadata or {}),
                    "debate_transcript_id": transcript.transcript_id,
                }
                agent_results.append(red_result)
                red_arguments = self._extract_debate_points(red_result)
                red_round_arguments.append(red_arguments)
                round_red_claims = self._build_claims_from_points(
                    side="red",
                    round_num=round_num + 1,
                    points=red_arguments,
                    reply_to_claim_ids=unresolved_claim_ids or [claim.claim_id for claim in round_blue_claims],
                )
                transcript.claims.extend(round_red_claims)

                # 蓝队再反驳
                blue_context = {
                    **context,
                    "red_team_arguments": red_arguments,
                    "round": round_num + 1,
                }
                self._notify_agent_start(blue_agent)
                blue_result = self._execute_agent_with_async_support(blue_agent, dict(blue_context))
                blue_result.metadata = {
                    **(blue_result.metadata or {}),
                    "debate_transcript_id": transcript.transcript_id,
                }
                agent_results.append(blue_result)
                blue_arguments = self._extract_debate_points(blue_result)
                blue_round_arguments.append(blue_arguments)
                round_blue_claims = self._build_claims_from_points(
                    side="blue",
                    round_num=round_num + 1,
                    points=blue_arguments,
                    reply_to_claim_ids=unresolved_claim_ids or [claim.claim_id for claim in round_red_claims],
                )
                transcript.claims.extend(round_blue_claims)

                adjudication = self._adjudicate_claims(transcript.claims)
                unresolved_claim_ids = adjudication["unresolved_claim_ids"]

            # 更新信号强度（基于辩论结果）
            adjustment_stats = {
                "adjusted_signals": 0,
                "total_delta": 0.0,
            }
            if SIGNALS_AVAILABLE:
                if transcript.claims:
                    adjustment_stats = self._update_signal_strengths_from_claims(transcript.claims)
                else:
                    adjustment_stats = self._update_signal_strengths_from_debate(
                        red_round_arguments,
                        blue_round_arguments,
                    )

        except Exception as e:
            errors.append(
                self._build_error_item(
                    phase=Phase.DEBATE,
                    error=e,
                )
            )

        signal_count = self._environment.signal_count if SIGNALS_AVAILABLE else 0

        return PhaseResult(
            phase=Phase.DEBATE,
            success=len(errors) == 0,
            duration=time.time() - start_time,
            signal_count=signal_count,
            agent_results=agent_results,
            errors=errors,
            metadata={
                "debate_rounds": self._debate_rounds,
                "red_points": sum(len(items) for items in red_round_arguments),
                "blue_points": sum(len(items) for items in blue_round_arguments),
                "debate_transcript_id": transcript.transcript_id,
                "claim_count": len(transcript.claims),
                "unresolved_claim_count": len(unresolved_claim_ids),
                "claims": [claim.to_dict() for claim in transcript.claims],
                "strategy": {
                    "strength_step": self._debate_strategy.strength_step,
                    "round_decay": self._debate_strategy.round_decay,
                    "max_adjustment": self._debate_strategy.max_adjustment,
                    "verified_only": self._debate_strategy.verified_only,
                    "rule_score_threshold": self._debate_rule_score_threshold,
                    "llm_uncertainty_threshold": self._debate_llm_uncertainty_threshold,
                    "llm_adjudication": self._debate_llm_adjudication,
                    "llm_batch_size": self._debate_llm_batch_size,
                    "llm_max_tokens": self._debate_llm_max_tokens,
                    "llm_temperature": self._debate_llm_temperature,
                    "llm_batch_calls": self._debate_llm_batch_calls,
                    "llm_claim_evaluations": self._debate_llm_claim_evaluations,
                    "llm_cache_hits": self._debate_llm_cache_hits,
                },
                "signal_adjustment": adjustment_stats if "adjustment_stats" in locals() else {
                    "adjusted_signals": 0,
                    "total_delta": 0.0,
                },
            },
        )

    def _execute_synthesis_phase(
        self,
        context: dict[str, Any],
        search_tool: Any = None,
    ) -> PhaseResult:
        """执行报告综合阶段（Phase 4）。

        Elite Agent 综合所有信息生成最终报告。

        Args:
            context: 执行上下文

        Returns:
            阶段结果
        """
        start_time = time.time()
        self._progress.current_phase = Phase.SYNTHESIS
        self._progress.phase_start_time = start_time

        if self._progress_callback:
            self._progress_callback(self._progress)

        try:
            elite_agent = EliteAgent(environment=self._environment, search_tool=search_tool)
            self._notify_agent_start(elite_agent)
            debate_metadata = self._progress.phase_metadata.get(Phase.DEBATE, {})
            synthesis_context = dict(context)
            if isinstance(debate_metadata, dict):
                claims = debate_metadata.get("claims")
                if isinstance(claims, list):
                    synthesis_context["debate_claims"] = claims
                transcript_id = debate_metadata.get("debate_transcript_id")
                if transcript_id:
                    synthesis_context["debate_transcript_id"] = transcript_id
            elite_result = self._execute_agent_with_async_support(elite_agent, synthesis_context)

            signal_count = self._environment.signal_count if SIGNALS_AVAILABLE else 0

            return PhaseResult(
                phase=Phase.SYNTHESIS,
                success=True,
                duration=time.time() - start_time,
                signal_count=signal_count,
                agent_results=[elite_result],
                metadata={
                    "report_generated": bool(elite_result.metadata.get("report")),
                },
            )

        except Exception as e:
            return PhaseResult(
                phase=Phase.SYNTHESIS,
                success=False,
                duration=time.time() - start_time,
                signal_count=0,
                errors=[
                    self._build_error_item(
                        phase=Phase.SYNTHESIS,
                        error=e,
                        agent_type="elite",
                    )
                ],
            )

    def _extract_debate_points(self, result: AgentResult) -> list[str]:
        """从 Agent 结果中提取辩论观点。

        Args:
            result: Agent 执行结果

        Returns:
            观点列表
        """
        points = []

        for discovery in result.discoveries:
            if isinstance(discovery, dict):
                content = discovery.get("content") or discovery.get("evidence", "")
            else:
                content = str(discovery)

            if content:
                points.append(content)

        return points[: self._debate_strategy.max_points_per_round]

    def _build_claims_from_points(
        self,
        *,
        side: str,
        round_num: int,
        points: list[str],
        reply_to_claim_ids: list[str],
    ) -> list[DebateClaim]:
        claims: list[DebateClaim] = []
        for idx, point in enumerate(points):
            claim_text = str(point).strip()
            if not claim_text:
                continue
            evidence_signal_ids, dimensions = self._match_evidence_signals(claim_text, limit=3)
            confidence = min(
                1.0,
                0.35 + 0.15 * len(evidence_signal_ids) + 0.05 * len(dimensions),
            )
            claims.append(
                DebateClaim(
                    claim_id=f"{side}-{round_num}-{idx}-{uuid4().hex[:8]}",
                    side=side,
                    round=round_num,
                    text=claim_text,
                    evidence_signal_ids=evidence_signal_ids,
                    reply_to_claim_ids=list(reply_to_claim_ids),
                    target_dimensions=dimensions or ["multiple"],
                    confidence=confidence,
                )
            )
        return claims

    def _match_evidence_signals(
        self,
        claim_text: str,
        *,
        limit: int = 3,
    ) -> tuple[list[str], list[str]]:
        if not SIGNALS_AVAILABLE:
            return [], []

        all_signals = [
            signal for signal in self._environment.all_signals
            if self._environment._is_signal_visible(signal)
        ]
        if not all_signals:
            return [], []

        scored: list[tuple[Any, float]] = []
        for signal in all_signals:
            relevance = self._calculate_argument_relevance(
                str(signal.evidence),
                [claim_text],
            )
            if relevance > 0:
                scored.append((signal, relevance))

        if not scored:
            fallback = sorted(all_signals, key=lambda signal: signal.strength, reverse=True)[:limit]
            return (
                [signal.id for signal in fallback],
                sorted({signal.dimension.value for signal in fallback}),
            )

        scored.sort(key=lambda item: item[1], reverse=True)
        selected = [signal for signal, _ in scored[:limit]]
        return (
            [signal.id for signal in selected],
            sorted({signal.dimension.value for signal in selected}),
        )

    def _adjudicate_claims(self, claims: list[DebateClaim]) -> dict[str, Any]:
        claim_by_id = {claim.claim_id: claim for claim in claims}
        unresolved_claim_ids: list[str] = []
        pending_verdicts: dict[str, str] = {}
        uncertain_claims: list[DebateClaim] = []

        for claim in claims:
            rule_score = self._rule_score_claim(claim, claim_by_id)
            claim.rule_score = round(rule_score, 6)

            if rule_score >= self._debate_rule_score_threshold:
                pending_verdicts[claim.claim_id] = DebateVerdict.SUPPORTED.value
                continue
            if rule_score <= -self._debate_rule_score_threshold:
                pending_verdicts[claim.claim_id] = DebateVerdict.REFUTED.value
                continue
            if abs(rule_score) <= self._debate_llm_uncertainty_threshold:
                uncertain_claims.append(claim)
                continue
            pending_verdicts[claim.claim_id] = DebateVerdict.PARTIAL.value

        if uncertain_claims:
            pending_verdicts.update(
                self._llm_adjudicate_claims_batch(
                    uncertain_claims,
                    claim_by_id,
                )
            )
        logger.info(
            "phase_executor.adjudication run_id=%s phase=debate claims=%s uncertain=%s llm_batch_calls=%s llm_claim_evals=%s llm_cache_hits=%s",
            self._environment.current_run_id,
            len(claims),
            len(uncertain_claims),
            self._debate_llm_batch_calls,
            self._debate_llm_claim_evaluations,
            self._debate_llm_cache_hits,
        )

        valid_verdicts = {item.value for item in DebateVerdict}
        for claim in claims:
            verdict = pending_verdicts.get(claim.claim_id, DebateVerdict.UNCERTAIN.value)
            if verdict not in valid_verdicts:
                verdict = DebateVerdict.UNCERTAIN.value
            claim.verdict = verdict
            if verdict in {DebateVerdict.PARTIAL.value, DebateVerdict.UNCERTAIN.value}:
                unresolved_claim_ids.append(claim.claim_id)

        return {"unresolved_claim_ids": unresolved_claim_ids}

    def _rule_score_claim(
        self,
        claim: DebateClaim,
        claim_by_id: dict[str, DebateClaim],
    ) -> float:
        evidence_quality = 0.0
        if claim.evidence_signal_ids and SIGNALS_AVAILABLE:
            scores: list[float] = []
            for signal_id in claim.evidence_signal_ids:
                signal = self._environment.get_signal(signal_id)
                if signal is None:
                    continue
                scores.append((float(signal.confidence) + float(signal.strength)) / 2.0)
            if scores:
                evidence_quality = sum(scores) / len(scores)

        overlap_scores: list[float] = []
        contradiction_penalty = 0.0
        for reply_id in claim.reply_to_claim_ids:
            reply_claim = claim_by_id.get(reply_id)
            if reply_claim is None:
                continue
            overlap = self._calculate_argument_relevance(
                signal_text=claim.text,
                arguments=[reply_claim.text],
            )
            overlap_scores.append(overlap)
            if reply_claim.side != claim.side and overlap < 0.1:
                contradiction_penalty += 0.2

        semantic_overlap = (sum(overlap_scores) / len(overlap_scores)) if overlap_scores else 0.0
        consistency = 1.0 if claim.evidence_signal_ids else 0.0

        return (
            0.45 * evidence_quality
            + 0.25 * semantic_overlap
            + 0.20 * consistency
            - 0.10 * contradiction_penalty
        )

    def _llm_adjudicate_claim(
        self,
        claim: DebateClaim,
        claim_by_id: dict[str, DebateClaim],
    ) -> str:
        return self._llm_adjudicate_claims_batch([claim], claim_by_id).get(
            claim.claim_id,
            DebateVerdict.UNCERTAIN.value,
        )

    def _claim_cache_key(
        self,
        claim: DebateClaim,
        claim_by_id: dict[str, DebateClaim],
    ) -> str:
        reply_claims = [
            claim_by_id[reply_id]
            for reply_id in claim.reply_to_claim_ids
            if reply_id in claim_by_id
        ]
        payload = {
            "claim_id": claim.claim_id,
            "side": claim.side,
            "text": claim.text,
            "evidence_signal_ids": list(claim.evidence_signal_ids),
            "reply_to_claim_ids": list(claim.reply_to_claim_ids),
            "reply_texts": [reply.text for reply in reply_claims[:3]],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _llm_adjudicate_claims_batch(
        self,
        claims: list[DebateClaim],
        claim_by_id: dict[str, DebateClaim],
    ) -> dict[str, str]:
        if not self._debate_llm_adjudication or self._debate_llm_client is None:
            return {claim.claim_id: DebateVerdict.UNCERTAIN.value for claim in claims}

        valid_verdicts = {item.value for item in DebateVerdict}
        verdicts: dict[str, str] = {}
        pending: list[tuple[DebateClaim, str]] = []
        for claim in claims:
            cache_key = self._claim_cache_key(claim, claim_by_id)
            cached = self._debate_verdict_cache.get(cache_key)
            if cached in valid_verdicts:
                verdicts[claim.claim_id] = cached
                self._debate_llm_cache_hits += 1
                continue
            pending.append((claim, cache_key))

        for idx in range(0, len(pending), self._debate_llm_batch_size):
            batch = pending[idx: idx + self._debate_llm_batch_size]
            if not batch:
                continue

            prompt_lines = [
                "You are an adjudicator for a red-blue debate.",
                "For each claim, return one verdict label: SUPPORTED / PARTIAL / REFUTED / UNCERTAIN.",
                'Output strict JSON only in this shape: {"results":[{"claim_id":"...","verdict":"..."}]}',
                "",
            ]
            claim_ids = [claim.claim_id for claim, _ in batch]
            for claim, _ in batch:
                evidence_snippets: list[str] = []
                for signal_id in claim.evidence_signal_ids[:3]:
                    signal = self._environment.get_signal(signal_id)
                    if signal is None:
                        continue
                    evidence_snippets.append(f"- ({signal_id}) {str(signal.evidence)[:180]}")
                reply_snippets: list[str] = []
                for reply_id in claim.reply_to_claim_ids[:3]:
                    reply_claim = claim_by_id.get(reply_id)
                    if reply_claim is None:
                        continue
                    reply_snippets.append(f"- ({reply_id}) {reply_claim.text[:180]}")

                prompt_lines.extend([
                    f"claim_id: {claim.claim_id}",
                    f"side: {claim.side}",
                    f"text: {claim.text}",
                    f"evidence: {chr(10).join(evidence_snippets) if evidence_snippets else '- none'}",
                    f"replies: {chr(10).join(reply_snippets) if reply_snippets else '- none'}",
                    "",
                ])

            parsed: dict[str, str] = {}
            try:
                self._debate_llm_batch_calls += 1
                self._debate_llm_claim_evaluations += len(batch)
                logger.info(
                    "phase_executor.llm_batch run_id=%s phase=debate batch_count=%s claim_count=%s max_tokens=%s temperature=%s",
                    self._environment.current_run_id,
                    self._debate_llm_batch_calls,
                    len(batch),
                    self._debate_llm_max_tokens,
                    self._debate_llm_temperature,
                )
                response = self._debate_llm_client.chat(
                    messages=[Message(role="user", content="\n".join(prompt_lines))],
                    system_prompt=(
                        "Return strict JSON only. No prose, no markdown, no extra fields."
                    ),
                    temperature=self._debate_llm_temperature,
                    max_tokens=self._debate_llm_max_tokens,
                    thinking_mode=False,
                )
                parsed = self._parse_llm_batch_verdicts(
                    content=str(response.content),
                    expected_claim_ids=set(claim_ids),
                )
                if not parsed:
                    logger.warning(
                        "phase_executor llm_adjudication_invalid_payload batch_size=%s content_preview=%s",
                        len(batch),
                        str(response.content)[:160],
                    )
            except Exception as exc:
                logger.warning("phase_executor llm_adjudication_failed batch_size=%s error=%s", len(batch), exc)

            for claim, cache_key in batch:
                verdict = parsed.get(claim.claim_id, DebateVerdict.UNCERTAIN.value)
                if verdict not in valid_verdicts:
                    verdict = DebateVerdict.UNCERTAIN.value
                verdicts[claim.claim_id] = verdict
                self._debate_verdict_cache[cache_key] = verdict

        return verdicts

    def _parse_llm_batch_verdicts(
        self,
        *,
        content: str,
        expected_claim_ids: set[str],
    ) -> dict[str, str]:
        valid_verdicts = {item.value for item in DebateVerdict}
        candidates: list[str] = []
        stripped = content.strip()
        if stripped:
            candidates.append(stripped)

        code_block_match = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", content, re.DOTALL)
        if code_block_match:
            candidates.append(code_block_match.group(1).strip())

        object_match = re.search(r"(\{.*\})", content, re.DOTALL)
        if object_match:
            candidates.append(object_match.group(1).strip())

        array_match = re.search(r"(\[.*\])", content, re.DOTALL)
        if array_match:
            candidates.append(array_match.group(1).strip())

        verdicts: dict[str, str] = {}
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except Exception:
                continue

            items: list[dict[str, Any]] = []
            if isinstance(data, dict):
                raw_items = data.get("results") or data.get("verdicts") or []
                if isinstance(raw_items, list):
                    items = [item for item in raw_items if isinstance(item, dict)]
            elif isinstance(data, list):
                items = [item for item in data if isinstance(item, dict)]

            for item in items:
                claim_id = str(item.get("claim_id") or "").strip()
                verdict = str(item.get("verdict") or "").strip().upper()
                if claim_id in expected_claim_ids and verdict in valid_verdicts:
                    verdicts[claim_id] = verdict

            if verdicts:
                return verdicts

        return {}

    def _update_signal_strengths_from_claims(self, claims: list[DebateClaim]) -> dict[str, Any]:
        if not SIGNALS_AVAILABLE:
            return {"adjusted_signals": 0, "total_delta": 0.0}

        verdict_weight = {
            DebateVerdict.SUPPORTED.value: 1.0,
            DebateVerdict.PARTIAL.value: 0.3,
            DebateVerdict.REFUTED.value: -1.0,
            DebateVerdict.UNCERTAIN.value: 0.0,
        }
        adjusted_signals = 0
        total_delta = 0.0
        touched: set[str] = set()

        for claim in claims:
            if not claim.evidence_signal_ids:
                continue
            side_sign = -1.0 if claim.side == "red" else 1.0
            verdict_sign = verdict_weight.get(claim.verdict, 0.0)
            if abs(verdict_sign) < 1e-9:
                continue
            round_decay = self._debate_strategy.round_decay ** max(0, claim.round - 1)

            for signal_id in claim.evidence_signal_ids:
                signal = self._environment.get_signal(signal_id)
                if signal is None:
                    continue
                if self._debate_strategy.verified_only and not signal.verified:
                    continue

                relevance = self._calculate_argument_relevance(
                    signal_text=signal.evidence,
                    arguments=[claim.text],
                )
                relevance = max(0.1, relevance)
                raw_delta = (
                    self._debate_strategy.strength_step
                    * side_sign
                    * verdict_sign
                    * relevance
                    * round_decay
                )
                raw_delta = max(
                    -self._debate_strategy.max_adjustment,
                    min(self._debate_strategy.max_adjustment, raw_delta),
                )
                if abs(raw_delta) < 1e-9:
                    continue

                new_strength = max(0.0, min(1.0, signal.strength + raw_delta))
                delta = new_strength - signal.strength
                if abs(delta) < 1e-9:
                    continue

                updated_signal = signal.with_updated_strength(
                    new_strength,
                    verifier="debate_claim",
                    debate_point=f"{claim.claim_id}:{claim.verdict}",
                )
                self._environment._signals[updated_signal.id] = updated_signal
                self._environment.apply_signal_event(
                    updated_signal.id,
                    debate_delta=delta,
                )
                touched.add(updated_signal.id)
                total_delta += delta

                for reply_id in claim.reply_to_claim_ids:
                    reply_claim = next((item for item in claims if item.claim_id == reply_id), None)
                    if reply_claim is None:
                        continue
                    for related_signal_id in reply_claim.evidence_signal_ids[:2]:
                        if related_signal_id == updated_signal.id:
                            continue
                        self._environment.register_debate_relation(
                            updated_signal.id,
                            related_signal_id,
                            support=claim.side == "blue",
                            weight=min(1.0, max(0.1, relevance)),
                        )

        adjusted_signals = len(touched)
        return {
            "adjusted_signals": adjusted_signals,
            "total_delta": round(total_delta, 6),
        }

    def _normalize_round_arguments(
        self,
        arguments: list[str] | list[list[str]],
    ) -> list[list[str]]:
        """统一辩论参数结构。"""
        if not arguments:
            return []
        if isinstance(arguments[0], list):
            return [list(items) for items in arguments if items]
        return [list(arguments)]

    def _tokenize(self, text: str) -> set[str]:
        """将文本切分为关键词。"""
        return {
            token
            for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text.lower())
            if len(token) >= 2
        }

    def _calculate_argument_relevance(
        self,
        signal_text: str,
        arguments: list[str],
    ) -> float:
        """计算信号与一组辩论观点的相关性。"""
        signal_tokens = self._tokenize(signal_text)
        if not signal_tokens:
            return 0.0

        relevance = 0.0
        for argument in arguments:
            argument_tokens = self._tokenize(argument)
            if not argument_tokens:
                continue
            overlap = signal_tokens & argument_tokens
            if overlap:
                relevance += len(overlap) / len(signal_tokens)

        return relevance

    def _apply_quantitative_validation(
        self,
        signal: "Signal",
        all_signals: list["Signal"],
    ) -> tuple["Signal", dict[str, Any]]:
        """应用定量数据验证并调整置信度。

        Args:
            signal: 待验证的信号
            all_signals: 所有信号列表（用于跨来源验证）

        Returns:
            (更新后的信号, 定量验证元数据)
        """
        if not self._enable_quantitative_validation or not self._quantitative_extractor:
            return signal, {}

        # 1. 从证据文本中提取数字
        extracted_numbers = self._quantitative_extractor.extract_numbers(str(signal.evidence))
        if not extracted_numbers:
            return signal, {}

        # 2. 按指标分组提取的数字
        metric_groups: dict[str, list[ExtractedNumber]] = {}
        for num in extracted_numbers:
            metric_key = num.context or "unknown"
            if metric_key not in metric_groups:
                metric_groups[metric_key] = []
            metric_groups[metric_key].append(num)

        # 3. 对每个指标进行跨来源验证
        validation_summary = {
            "metrics_validated": [],
            "quantitative_evidence": [],
        }

        total_confidence_adjustment = 0.0

        for metric_name, numbers in metric_groups.items():
            if len(numbers) == 0:
                continue

            # 收集相同指标的来源
            sources: list[str] = []
            for other_signal in all_signals:
                if other_signal.id == signal.id:
                    continue
                # 检查其他信号是否包含相同指标
                other_numbers = self._quantitative_extractor.extract_numbers(str(other_signal.evidence))
                for other_num in other_numbers:
                    if other_num.context == metric_name:
                        if other_signal.source not in sources:
                            sources.append(other_signal.source)
                        break

            # 执行交叉验证
            validation_result = self._quantitative_validator.cross_validate(numbers, sources)

            # 构建定量证据
            for num in numbers:
                evidence = {
                    "metric_name": metric_name,
                    "value": str(num.value),
                    "unit": num.unit,
                    "confidence": num.confidence,
                    "original_text": num.text,
                }
                validation_summary["quantitative_evidence"].append(evidence)

            validation_summary["metrics_validated"].append({
                "metric_name": metric_name,
                "status": validation_result.status.value,
                "consensus_value": validation_result.consensus_value,
                "confidence_adjustment": validation_result.confidence_adjustment,
            })

            total_confidence_adjustment += validation_result.confidence_adjustment

        # 4. 应用置信度调整（限制在 [-0.2, 0.2] 范围内）
        adjusted_confidence = max(0.0, min(1.0, signal.confidence + total_confidence_adjustment))

        # 5. 创建更新后的信号
        updated_metadata = dict(signal.metadata or {})
        updated_metadata["quantitative_validation"] = validation_summary

        updated_signal = Signal(
            id=signal.id,
            signal_type=signal.signal_type,
            dimension=signal.dimension,
            evidence=signal.evidence,
            confidence=adjusted_confidence,
            strength=signal.strength,
            sentiment=signal.sentiment,
            tags=list(signal.tags),
            source=signal.source,
            timestamp=signal.timestamp,
            references=list(signal.references),
            author_agent=signal.author_agent,
            verified=signal.verified or total_confidence_adjustment >= 0,
            debate_points=list(signal.debate_points),
            actionability=signal.actionability,
            metadata=updated_metadata,
        )

        return updated_signal, validation_summary

    def _update_signal_strengths_from_debate(
        self,
        red_arguments: list[str] | list[list[str]],
        blue_arguments: list[str] | list[list[str]],
    ) -> dict[str, Any]:
        """根据辩论结果更新信号强度。

        基于辩论观点与信号文本的相关性进行强度调整。

        Args:
            red_arguments: 红队观点
            blue_arguments: 蓝队观点

        Returns:
            调整统计信息
        """
        if not SIGNALS_AVAILABLE:
            return {"adjusted_signals": 0, "total_delta": 0.0}

        red_rounds = self._normalize_round_arguments(red_arguments)
        blue_rounds = self._normalize_round_arguments(blue_arguments)
        if not red_rounds and not blue_rounds:
            return {"adjusted_signals": 0, "total_delta": 0.0}

        synthetic_claims: list[DebateClaim] = []
        for round_idx, round_arguments in enumerate(red_rounds, start=1):
            synthetic_claims.extend(
                self._build_claims_from_points(
                    side="red",
                    round_num=round_idx,
                    points=round_arguments,
                    reply_to_claim_ids=[],
                )
            )
        for round_idx, round_arguments in enumerate(blue_rounds, start=1):
            synthetic_claims.extend(
                self._build_claims_from_points(
                    side="blue",
                    round_num=round_idx,
                    points=round_arguments,
                    reply_to_claim_ids=[],
                )
            )

        # 兼容旧接口：默认视为 claim 被采纳，再按 claim 级规则更新强度。
        for claim in synthetic_claims:
            claim.verdict = DebateVerdict.SUPPORTED.value

        return self._update_signal_strengths_from_claims(synthetic_claims)


def create_phase_executor(
    environment: StigmergyEnvironment | None = None,
    debate_rounds: int | None = None,
    min_confidence: float | None = None,
    min_strength: float | None = None,
    min_weighted_score: float | None = None,
    confidence_weight: float | None = None,
    strength_weight: float | None = None,
    max_signals_per_dimension: int | None = None,
    verification_boost: float | None = None,
    enable_quantitative_validation: bool | None = None,
    quantitative_tolerance_threshold: float | None = None,
    debate_strength_step: float | None = None,
    debate_round_decay: float | None = None,
    debate_max_adjustment: float | None = None,
    max_points_per_round: int | None = None,
    debate_verified_only: bool | None = None,
    debate_rule_score_threshold: float | None = None,
    debate_llm_uncertainty_threshold: float | None = None,
    debate_llm_adjudication: bool | None = None,
    debate_llm_batch_size: int | None = None,
    debate_llm_max_tokens: int | None = None,
    debate_llm_temperature: float | None = None,
    progress_callback: Callable[[PhaseProgress], None] | None = None,
    on_agent_start: Callable[[str], None] | None = None,
) -> PhaseExecutor:
    """创建阶段执行器。

    Args:
        environment: 共享环境
        debate_rounds: 辩论轮数
        min_confidence: 最低置信度
        progress_callback: 进度回调

    Returns:
        阶段执行器实例
    """
    config = get_config()
    phase_executor_config = getattr(config, "phase_executor", None)
    validation_config = getattr(phase_executor_config, "validation", None)
    debate_config = getattr(phase_executor_config, "debate", None)

    return PhaseExecutor(
        environment=environment,
        debate_rounds=debate_rounds if debate_rounds is not None else getattr(debate_config, "rounds", 3),
        min_confidence=min_confidence if min_confidence is not None else getattr(validation_config, "min_confidence", 0.3),
        min_strength=min_strength if min_strength is not None else getattr(validation_config, "min_strength", 0.0),
        min_weighted_score=(
            min_weighted_score
            if min_weighted_score is not None
            else getattr(validation_config, "min_weighted_score", 0.35)
        ),
        confidence_weight=(
            confidence_weight
            if confidence_weight is not None
            else getattr(validation_config, "confidence_weight", 0.7)
        ),
        strength_weight=(
            strength_weight
            if strength_weight is not None
            else getattr(validation_config, "strength_weight", 0.3)
        ),
        max_signals_per_dimension=(
            max_signals_per_dimension
            if max_signals_per_dimension is not None
            else getattr(validation_config, "max_signals_per_dimension", 20)
        ),
        verification_boost=(
            verification_boost
            if verification_boost is not None
            else getattr(validation_config, "verification_boost", 0.03)
        ),
        enable_quantitative_validation=(
            enable_quantitative_validation
            if enable_quantitative_validation is not None
            else getattr(validation_config, "enable_quantitative_validation", True)
        ),
        quantitative_tolerance_threshold=(
            quantitative_tolerance_threshold
            if quantitative_tolerance_threshold is not None
            else getattr(validation_config, "quantitative_tolerance_threshold", 0.2)
        ),
        debate_strength_step=(
            debate_strength_step
            if debate_strength_step is not None
            else getattr(debate_config, "strength_step", 0.05)
        ),
        debate_round_decay=(
            debate_round_decay
            if debate_round_decay is not None
            else getattr(debate_config, "round_decay", 0.85)
        ),
        debate_max_adjustment=(
            debate_max_adjustment
            if debate_max_adjustment is not None
            else getattr(debate_config, "max_adjustment", 0.2)
        ),
        max_points_per_round=(
            max_points_per_round
            if max_points_per_round is not None
            else getattr(debate_config, "max_points_per_round", 10)
        ),
        debate_verified_only=(
            debate_verified_only
            if debate_verified_only is not None
            else getattr(debate_config, "verified_only", True)
        ),
        debate_rule_score_threshold=(
            debate_rule_score_threshold
            if debate_rule_score_threshold is not None
            else getattr(debate_config, "rule_score_threshold", 0.35)
        ),
        debate_llm_uncertainty_threshold=(
            debate_llm_uncertainty_threshold
            if debate_llm_uncertainty_threshold is not None
            else getattr(debate_config, "llm_uncertainty_threshold", 0.15)
        ),
        debate_llm_adjudication=(
            debate_llm_adjudication
            if debate_llm_adjudication is not None
            else getattr(debate_config, "llm_adjudication", True)
        ),
        debate_llm_batch_size=(
            debate_llm_batch_size
            if debate_llm_batch_size is not None
            else getattr(debate_config, "llm_batch_size", 10)
        ),
        debate_llm_max_tokens=(
            debate_llm_max_tokens
            if debate_llm_max_tokens is not None
            else getattr(debate_config, "llm_max_tokens", 128)
        ),
        debate_llm_temperature=(
            debate_llm_temperature
            if debate_llm_temperature is not None
            else getattr(debate_config, "llm_temperature", 0.0)
        ),
        progress_callback=progress_callback,
        on_agent_start=on_agent_start,
    )
