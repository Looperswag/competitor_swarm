"""编排器模块。

负责协调 Agent 的执行顺序和数据流。
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

from src.agents.base import AgentType, AgentResult
from src.core.phase_executor import Phase, PhaseProgress, create_phase_executor
from src.environment import StigmergyEnvironment, get_environment
from src.error_types import ErrorType
from src.utils.config import get_config
from src.search import get_search_tool


@dataclass
class CoordinatorResult:
    """编排器执行结果。"""

    target: str
    success: bool
    duration: float
    agent_results: dict[str, list[AgentResult]] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Coordinator:
    """编排器。

    协调所有 Agent 的执行。
    """

    UNKNOWN_ERROR_TYPE = "UNKNOWN"

    def __init__(
        self,
        environment: StigmergyEnvironment | None = None,
        scheduler: Any | None = None,
        search_tool: Any = None,
        phase_executor_overrides: dict[str, Any] | None = None,
        on_phase_start: "Callable[[str], None] | None" = None,
        on_phase_complete: "Callable[[str, int], None] | None" = None,
        on_agent_start: "Callable[[str], None] | None" = None,
    ) -> None:
        """初始化编排器。

        Args:
            environment: 共享环境
            scheduler: 兼容保留参数（当前主干不使用）
            search_tool: 搜索工具（可选）
            phase_executor_overrides: 四阶段执行引擎参数覆盖
            on_phase_start: 阶段开始回调，参数为阶段名称
            on_phase_complete: 阶段完成回调，参数为阶段名称和进度增量
            on_agent_start: Agent 开始回调，参数为 Agent 名称
        """
        self._environment = environment or get_environment()
        self._phase_executor_overrides = phase_executor_overrides or {}
        self._on_phase_start = on_phase_start
        self._on_phase_complete = on_phase_complete
        self._on_agent_start = on_agent_start
        self._scheduler = scheduler  # backward-compatible attribute, intentionally unused

        # 初始化搜索工具
        self._search_tool = search_tool
        if self._search_tool is None:
            try:
                config = get_config()
                if hasattr(config, "search") and config.search.api_key:
                    self._search_tool = get_search_tool(
                        provider=config.search.provider,
                        api_key=config.search.api_key,
                    )
                elif hasattr(config, "search"):
                    self._search_tool = get_search_tool(
                        provider=config.search.provider,
                    )
            except Exception as e:
                logger.warning(f"Failed to initialize search tool: {e}")
                self._search_tool = None

    def analyze(
        self,
        target: str,
        competitors: list[str] | None = None,
        focus_areas: list[str] | None = None,
    ) -> CoordinatorResult:
        """执行竞品分析。

        Args:
            target: 目标产品/公司名称
            competitors: 竞品列表
            focus_areas: 重点关注领域

        Returns:
            分析结果
        """
        # Phase 1 主干统一到 PhaseExecutor。每次分析开启独立 run 上下文。
        self._environment.begin_run(run_id=str(uuid.uuid4()), clear=True)
        return self._analyze_with_phase_executor(
            target=target,
            competitors=competitors,
            focus_areas=focus_areas,
        )

    def _analyze_with_phase_executor(
        self,
        target: str,
        competitors: list[str] | None = None,
        focus_areas: list[str] | None = None,
    ) -> CoordinatorResult:
        """使用四阶段执行引擎进行分析。"""
        start_time = time.time()
        started_phase_names: set[str] = set()
        completed_phase_names: set[str] = set()

        phase_deltas = {
            "信息收集": 30,
            "交叉验证": 20,
            "红蓝队对抗": 30,
            "报告综合": 20,
        }

        def emit_phase_start(name: str) -> None:
            if not self._on_phase_start or name in started_phase_names:
                return
            started_phase_names.add(name)
            self._on_phase_start(name)

        def emit_phase_complete(name: str) -> None:
            if not self._on_phase_complete or name in completed_phase_names:
                return
            completed_phase_names.add(name)
            self._on_phase_complete(name, phase_deltas[name])

        def on_progress(progress: PhaseProgress) -> None:
            if progress.current_phase == Phase.COLLECTION:
                emit_phase_start("信息收集")
            elif progress.current_phase == Phase.VALIDATION:
                emit_phase_complete("信息收集")
                emit_phase_start("交叉验证")
            elif progress.current_phase == Phase.DEBATE:
                emit_phase_complete("交叉验证")
                emit_phase_start("红蓝队对抗")
            elif progress.current_phase == Phase.SYNTHESIS:
                emit_phase_complete("红蓝队对抗")
                emit_phase_start("报告综合")

        phase_executor = create_phase_executor(
            environment=self._environment,
            progress_callback=on_progress,
            on_agent_start=self._on_agent_start,
            **self._phase_executor_overrides,
        )

        progress = phase_executor.execute(
            target=target,
            competitors=competitors,
            focus_areas=focus_areas,
            search_tool=self._search_tool,
        )

        # 兜底补齐阶段完成事件（避免异常中断导致进度条停滞）
        if Phase.COLLECTION in progress.completed_phases:
            emit_phase_complete("信息收集")
        if Phase.VALIDATION in progress.completed_phases:
            emit_phase_complete("交叉验证")
        if Phase.DEBATE in progress.completed_phases:
            emit_phase_complete("红蓝队对抗")
        if Phase.SYNTHESIS in progress.completed_phases:
            emit_phase_complete("报告综合")

        run_id = self._environment.current_run_id
        all_results = self._flatten_phase_agent_results(progress.agent_results)
        all_results = self._backfill_results_from_environment(all_results)
        all_errors = self._flatten_phase_errors(progress.phase_errors, run_id=run_id)
        self._log_phase_errors(all_errors)

        total_discoveries = self._calculate_total_discoveries(all_results)
        any_discoveries = any(self._has_discoveries(r) for r in all_results.values())
        success = self._compute_success(any_discoveries, all_errors)
        agent_status = self._summarize_agent_status(all_results, all_errors)
        partial_success = bool(all_errors) and any_discoveries

        duration = progress.total_duration or (time.time() - start_time)

        return CoordinatorResult(
            target=target,
            success=success,
            duration=duration,
            agent_results=all_results,
            errors=all_errors,
            metadata={
                "competitors": competitors,
                "focus_areas": focus_areas,
                "total_discoveries": total_discoveries,
                "total_discoveries_legacy": self._environment.discovery_count,
                "total_signals": getattr(self._environment, "signal_count", 0),
                "agent_status": agent_status,
                "partial_success": partial_success,
                "execution_mode": "phase_executor",
                "run_id": run_id,
                "completed_phases": [phase.value for phase in progress.completed_phases],
                "phase_progress": progress.to_dict(),
            },
        )

    def _flatten_phase_agent_results(
        self,
        phase_results: dict[Phase, list[AgentResult]],
    ) -> dict[str, list[AgentResult]]:
        """将阶段结果扁平化为按 Agent 分类的结果。"""
        flat_results: dict[str, list[AgentResult]] = {}

        for phase in (Phase.COLLECTION, Phase.VALIDATION, Phase.DEBATE, Phase.SYNTHESIS):
            for result in phase_results.get(phase, []):
                flat_results.setdefault(result.agent_type, []).append(result)

        for phase_key, results in phase_results.items():
            if phase_key in (Phase.COLLECTION, Phase.VALIDATION, Phase.DEBATE, Phase.SYNTHESIS):
                continue
            for result in results:
                flat_results.setdefault(result.agent_type, []).append(result)

        return flat_results

    def _flatten_phase_errors(
        self,
        phase_errors: dict[Phase, list[Any]],
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """将分阶段错误转为 Coordinator 兼容错误结构。"""
        errors: list[dict[str, Any]] = []

        for phase_key, phase_error_list in phase_errors.items():
            phase_name = phase_key.value if isinstance(phase_key, Phase) else str(phase_key)
            for raw_error in phase_error_list:
                errors.append(
                    self._normalize_phase_error(
                        phase_name=phase_name,
                        raw_error=raw_error,
                        run_id=run_id,
                    )
                )

        return errors

    def _normalize_phase_error(
        self,
        *,
        phase_name: str,
        raw_error: Any,
        run_id: str | None,
    ) -> dict[str, Any]:
        """标准化 phase 错误结构，保证可追溯字段齐全。"""
        error_item: dict[str, Any] = {
            "phase": phase_name,
            "agent_type": "unknown",
            "error": "unknown error",
        }

        source_error_type: str | None = None
        source_recoverable: bool | None = None
        source_hint: str | None = None
        source_retry_count: int | None = None
        source_claim_id: str | None = None
        source_evidence_signal_ids: list[str] | None = None
        source_verdict: str | None = None
        source_run_id: str | None = None

        if isinstance(raw_error, dict):
            error_item["agent_type"] = str(raw_error.get("agent_type") or raw_error.get("agent") or "unknown")
            error_item["error"] = str(
                raw_error.get("error") or raw_error.get("message") or str(raw_error)
            ).strip() or "unknown error"

            raw_error_type = raw_error.get("error_type")
            if raw_error_type is not None and str(raw_error_type).strip():
                source_error_type = str(raw_error_type).strip()

            if "recoverable" in raw_error:
                source_recoverable = bool(raw_error.get("recoverable"))

            raw_hint = raw_error.get("hint")
            if raw_hint is not None and str(raw_hint).strip():
                source_hint = str(raw_hint).strip()

            if "retry_count" in raw_error:
                try:
                    source_retry_count = max(0, int(raw_error.get("retry_count") or 0))
                except (TypeError, ValueError):
                    source_retry_count = 0
            raw_claim_id = raw_error.get("claim_id")
            if raw_claim_id is not None and str(raw_claim_id).strip():
                source_claim_id = str(raw_claim_id).strip()
            raw_evidence_signal_ids = raw_error.get("evidence_signal_ids")
            if isinstance(raw_evidence_signal_ids, list):
                source_evidence_signal_ids = [
                    str(signal_id).strip()
                    for signal_id in raw_evidence_signal_ids
                    if str(signal_id).strip()
                ]
            raw_verdict = raw_error.get("verdict")
            if raw_verdict is not None and str(raw_verdict).strip():
                source_verdict = str(raw_verdict).strip()
            raw_run_id = raw_error.get("run_id")
            if raw_run_id is not None and str(raw_run_id).strip():
                source_run_id = str(raw_run_id).strip()
        else:
            error_item["error"] = str(raw_error).strip() or "unknown error"

        if ":" in error_item["error"] and error_item.get("agent_type") in {"unknown", ""}:
            agent_hint, error_message = error_item["error"].split(":", 1)
            candidate_agent = agent_hint.strip()
            if candidate_agent in {agent.value for agent in AgentType} and error_message.strip():
                error_item["agent_type"] = candidate_agent
                error_item["error"] = error_message.strip()

        inferred_error_type, inferred_recoverable, inferred_hint = self._classify_error(error_item["error"])
        error_item["error_type"] = source_error_type or inferred_error_type
        error_item["recoverable"] = source_recoverable if source_recoverable is not None else inferred_recoverable
        error_item["hint"] = source_hint if source_hint is not None else inferred_hint
        if source_retry_count is not None:
            error_item["retry_count"] = source_retry_count
        if source_claim_id:
            error_item["claim_id"] = source_claim_id
        if source_evidence_signal_ids:
            error_item["evidence_signal_ids"] = source_evidence_signal_ids
        if source_verdict:
            error_item["verdict"] = source_verdict

        effective_run_id = run_id or source_run_id
        if effective_run_id:
            error_item["run_id"] = effective_run_id

        return error_item

    def _classify_error(self, error_text: str) -> tuple[str, bool, str]:
        """基于错误文本推断错误类型。"""
        normalized = str(error_text).lower()
        if "timeout" in normalized or "timed out" in normalized:
            return (
                ErrorType.UPSTREAM_TIMEOUT.value,
                True,
                "Try increasing timeout or reducing upstream fan-out.",
            )
        if "rate limit" in normalized or "429" in normalized:
            return (
                ErrorType.UPSTREAM_RATE_LIMIT.value,
                True,
                "Retry with exponential backoff.",
            )
        if "parse" in normalized or "json" in normalized:
            return (
                ErrorType.PARSE_FAILURE.value,
                True,
                "Inspect parser assumptions and fallback behavior.",
            )
        if "empty" in normalized and "output" in normalized:
            return (
                ErrorType.EMPTY_OUTPUT.value,
                True,
                "Strengthen prompt constraints and fallback generation.",
            )
        if "search" in normalized:
            return (
                ErrorType.SEARCH_FAILURE.value,
                True,
                "Check upstream search provider availability.",
            )
        return (
            self.UNKNOWN_ERROR_TYPE,
            True,
            "Inspect coordinator logs for raw error context.",
        )

    def _log_phase_errors(self, errors: list[dict[str, Any]]) -> None:
        """输出结构化错误日志，支持 run_id 全链路追踪。"""
        for error in errors:
            logger.warning(
                "analysis_error run_id=%s phase=%s agent_type=%s error_type=%s "
                "claim_id=%s verdict=%s error=%s hint=%s",
                error.get("run_id", ""),
                error.get("phase", ""),
                error.get("agent_type", "unknown"),
                error.get("error_type", self.UNKNOWN_ERROR_TYPE),
                error.get("claim_id", ""),
                error.get("verdict", ""),
                error.get("error", ""),
                error.get("hint", ""),
            )

    def _calculate_total_discoveries(self, results: dict[str, list[AgentResult]]) -> int:
        """计算总发现数（兼容 signals 与 legacy discoveries）。"""
        total_from_results = 0
        for agent_results in results.values():
            for agent_result in agent_results:
                discoveries = getattr(agent_result, "discoveries", None)
                if isinstance(discoveries, list):
                    total_from_results += len(discoveries)

        total_from_env = self._environment.discovery_count
        if getattr(self._environment, "signal_count", 0) > 0:
            total_from_env = max(total_from_env, self._environment.signal_count)

        return max(total_from_results, total_from_env)

    def _backfill_results_from_environment(
        self,
        results: dict[str, list[AgentResult]],
    ) -> dict[str, list[AgentResult]]:
        """用环境中的 signals/discoveries 回填缺失结果，避免报告空白。"""
        # signals 优先
        if getattr(self._environment, "signal_count", 0) > 0:
            try:
                by_agent: dict[str, list[dict[str, Any]]] = {}
                for signal in self._environment.all_signals:
                    author = getattr(signal, "author_agent", "") or "unknown"
                    by_agent.setdefault(author, []).append(signal.to_dict())

                for agent_type, signals in by_agent.items():
                    if not self._has_discoveries(results.get(agent_type, [])):
                        results[agent_type] = [
                            AgentResult(
                                agent_type=agent_type,
                                agent_name=agent_type,
                                discoveries=signals,
                                handoffs_created=0,
                                metadata={"backfilled": True, "source": "signals"},
                            )
                        ]
            except Exception:
                pass

        # legacy discoveries 回填
        if self._environment.discovery_count > 0:
            try:
                by_agent: dict[str, list[Any]] = {}
                for discovery in self._environment.all_discoveries:
                    by_agent.setdefault(discovery.agent_type, []).append(discovery)

                for agent_type, discoveries in by_agent.items():
                    if not self._has_discoveries(results.get(agent_type, [])):
                        results[agent_type] = [
                            AgentResult(
                                agent_type=agent_type,
                                agent_name=agent_type,
                                discoveries=[d.to_dict() for d in discoveries],
                                handoffs_created=0,
                                metadata={"backfilled": True, "source": "discoveries"},
                            )
                        ]
            except Exception:
                pass

        return results

    def _has_discoveries(self, agent_results: list[AgentResult] | None) -> bool:
        if not agent_results:
            return False
        for result in agent_results:
            discoveries = getattr(result, "discoveries", None)
            if isinstance(discoveries, list) and len(discoveries) > 0:
                return True
        return False

    def _compute_success(
        self,
        any_discoveries: bool,
        errors: list[dict[str, Any]],
    ) -> bool:
        """基于结果判断是否成功（允许部分成功输出报告）。"""
        # 若无任何发现，视为失败（避免空报告被标记成功）
        return any_discoveries

    def _summarize_agent_status(
        self,
        results: dict[str, list[AgentResult]],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """汇总各 Agent 的执行状态。"""
        failed_agents = {err.get("agent_type") for err in errors if err.get("agent_type")}
        all_agents = set(results.keys()) | failed_agents

        summary = {
            "total_agents": len(all_agents),
            "failed_agents": sorted(a for a in failed_agents if a),
            "empty_agents": [],
            "successful_agents": [],
        }

        for agent in all_agents:
            agent_results = results.get(agent, [])
            if self._has_discoveries(agent_results):
                summary["successful_agents"].append(agent)
            else:
                summary["empty_agents"].append(agent)

        summary["successful_agents"] = sorted(summary["successful_agents"])
        summary["empty_agents"] = sorted(summary["empty_agents"])
        return summary


# 全局编排器实例（延迟加载）
_coordinator: Coordinator | None = None


def get_coordinator() -> Coordinator:
    """获取全局编排器实例。

    Returns:
        编排器
    """
    global _coordinator
    if _coordinator is None:
        _coordinator = Coordinator()
    return _coordinator


def reset_coordinator() -> None:
    """重置全局编排器。"""
    global _coordinator
    _coordinator = None
