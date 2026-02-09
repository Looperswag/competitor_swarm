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
from src.agents.scout import ScoutAgent
from src.agents.experience import ExperienceAgent
from src.agents.technical import TechnicalAgent
from src.agents.market import MarketAgent
from src.agents.red_team import RedTeamAgent
from src.agents.blue_team import BlueTeamAgent
from src.agents.elite import EliteAgent
from src.environment import StigmergyEnvironment, get_environment
from src.scheduler import SimpleScheduler, AgentTask, get_scheduler
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

    # Agent 类型映射
    AGENT_CLASSES = {
        AgentType.SCOUT: ScoutAgent,
        AgentType.EXPERIENCE: ExperienceAgent,
        AgentType.TECHNICAL: TechnicalAgent,
        AgentType.MARKET: MarketAgent,
        AgentType.RED_TEAM: RedTeamAgent,
        AgentType.BLUE_TEAM: BlueTeamAgent,
        AgentType.ELITE: EliteAgent,
    }

    def __init__(
        self,
        environment: StigmergyEnvironment | None = None,
        scheduler: SimpleScheduler | None = None,
        search_tool: Any = None,
        on_phase_start: "Callable[[str], None] | None" = None,
        on_phase_complete: "Callable[[str, int], None] | None" = None,
        on_agent_start: "Callable[[str], None] | None" = None,
    ) -> None:
        """初始化编排器。

        Args:
            environment: 共享环境
            scheduler: 调度器
            search_tool: 搜索工具（可选）
            on_phase_start: 阶段开始回调，参数为阶段名称
            on_phase_complete: 阶段完成回调，参数为阶段名称和进度增量
            on_agent_start: Agent 开始回调，参数为 Agent 名称
        """
        self._environment = environment or get_environment()
        self._on_phase_start = on_phase_start
        self._on_phase_complete = on_phase_complete
        self._on_agent_start = on_agent_start

        # 初始化调度器（带进度回调）
        if scheduler:
            self._scheduler = scheduler
        else:
            self._scheduler = SimpleScheduler(
                on_task_start=lambda agent_name: self._on_agent_start and self._on_agent_start(agent_name),
            )

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
        start_time = time.time()

        # 清空环境
        self._environment.clear()

        # 构建上下文
        context = {
            "target": target,
            "competitors": competitors or [],
            "focus_areas": focus_areas or [],
        }

        try:
            # 第一阶段：基础分析（并发执行）
            basic_results, basic_errors = self._run_basic_analysis(context)

            # 第二阶段：红蓝队对抗
            debate_results, debate_errors = self._run_debate(context)

            # 第三阶段：精英 Agent 综合
            elite_result, elite_errors = self._run_elite_synthesis(context)

            duration = time.time() - start_time

            # 合并结果（保留所有结果，避免覆盖）
            all_results: dict[str, list[AgentResult]] = {}
            for source in (basic_results, debate_results):
                for agent_type, results in source.items():
                    all_results.setdefault(agent_type, []).extend(results)
            all_results["elite"] = [elite_result]

            # 回填：如果结果缺失但环境已有数据，补全用于报告展示
            all_results = self._backfill_results_from_environment(all_results)

            all_errors = basic_errors + debate_errors + elite_errors

            # 统计总发现数量（优先使用环境统计，兼容 signals）
            total_discoveries = self._calculate_total_discoveries(all_results)
            any_discoveries = any(self._has_discoveries(r) for r in all_results.values())
            success = self._compute_success(any_discoveries, all_errors)
            agent_status = self._summarize_agent_status(all_results, all_errors)

            partial_success = bool(all_errors) and any_discoveries

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
                },
            )

        except Exception as e:
            duration = time.time() - start_time

            return CoordinatorResult(
                target=target,
                success=False,
                duration=duration,
                errors=[{"error": str(e)}],
            )

    def _run_basic_analysis(self, context: dict[str, Any]) -> tuple[dict[str, list[AgentResult]], list[dict[str, Any]]]:
        """运行基础分析阶段。

        Args:
            context: 执行上下文

        Returns:
            (Agent 结果映射, 错误列表)
        """
        # 触发阶段开始回调
        if self._on_phase_start:
            self._on_phase_start("基础分析")

        # 创建基础 Agent 任务
        basic_agents = [
            AgentType.SCOUT,
            AgentType.EXPERIENCE,
            AgentType.TECHNICAL,
            AgentType.MARKET,
        ]

        tasks = self._create_agent_tasks(basic_agents, context)

        # 并发执行
        result = self._scheduler.run_tasks_sync(tasks)

        # 触发阶段完成回调（基础分析占 40%）
        if self._on_phase_complete:
            self._on_phase_complete("基础分析", 40)

        # 收集结果
        results: dict[str, list[AgentResult]] = {}
        errors: list[dict[str, Any]] = []
        failed_by_agent: dict[str, list[str]] = {}
        agent_names: dict[str, str] = {}

        for task in result.tasks:
            agent_type = task.agent.agent_type.value if hasattr(task.agent, "agent_type") else "unknown"
            agent_name = getattr(task.agent, "name", agent_type)
            agent_names[agent_type] = agent_name

            if task.status.value == "completed" and task.result:
                results.setdefault(agent_type, []).append(task.result)
                continue

            if task.status.value == "failed":
                errors.append({
                    "task_id": task.id,
                    "agent_type": agent_type,
                    "error": task.error or "unknown error",
                })
                failed_by_agent.setdefault(agent_type, []).append(task.error or "unknown error")

        # 为失败且无结果的 Agent 写入占位结果，避免报告缺失
        for agent_type, error_list in failed_by_agent.items():
            if agent_type in results:
                continue
            results[agent_type] = [AgentResult(
                agent_type=agent_type,
                agent_name=agent_names.get(agent_type, agent_type),
                discoveries=[],
                handoffs_created=0,
                metadata={"error": "; ".join(error_list)},
            )]

        return results, errors

    def _run_debate(self, context: dict[str, Any]) -> tuple[dict[str, list[AgentResult]], list[dict[str, Any]]]:
        """运行红蓝队对抗阶段。

        Args:
            context: 执行上下文

        Returns:
            (Agent 结果映射, 错误列表)
        """
        # 触发阶段开始回调
        if self._on_phase_start:
            self._on_phase_start("红蓝队对抗")

        results: dict[str, list[AgentResult]] = {}
        errors: list[dict[str, Any]] = []

        # 创建红队任务
        red_team_task = self._create_agent_task(AgentType.RED_TEAM, context)
        red_result = self._scheduler.run_tasks_sync([red_team_task])

        red_arguments = ""
        if red_result.tasks and red_result.tasks[0].result:
            results["red_team"] = [red_result.tasks[0].result]
            red_arguments = self._collect_red_arguments(red_result.tasks[0].result)
        else:
            if red_result.tasks and red_result.tasks[0].error:
                errors.append({
                    "task_id": red_result.tasks[0].id,
                    "agent_type": "red_team",
                    "error": red_result.tasks[0].error,
                })
                results["red_team"] = [AgentResult(
                    agent_type="red_team",
                    agent_name="红队专家",
                    discoveries=[],
                    handoffs_created=0,
                    metadata={"error": red_result.tasks[0].error},
                )]

        # 创建蓝队任务（传入红队观点）
        blue_context = {**context, "red_team_arguments": red_arguments} if red_arguments else context
        blue_team_task = self._create_agent_task(AgentType.BLUE_TEAM, blue_context)
        blue_result = self._scheduler.run_tasks_sync([blue_team_task])

        if blue_result.tasks and blue_result.tasks[0].result:
            results["blue_team"] = [blue_result.tasks[0].result]
        else:
            if blue_result.tasks and blue_result.tasks[0].error:
                errors.append({
                    "task_id": blue_result.tasks[0].id,
                    "agent_type": "blue_team",
                    "error": blue_result.tasks[0].error,
                })
                results["blue_team"] = [AgentResult(
                    agent_type="blue_team",
                    agent_name="蓝队专家",
                    discoveries=[],
                    handoffs_created=0,
                    metadata={"error": blue_result.tasks[0].error},
                )]

        # 触发阶段完成回调（红蓝队对抗占 40%）
        if self._on_phase_complete:
            self._on_phase_complete("红蓝队对抗", 40)

        return results, errors

    def _run_elite_synthesis(self, context: dict[str, Any]) -> tuple[AgentResult, list[dict[str, Any]]]:
        """运行精英 Agent 综合阶段。

        Args:
            context: 执行上下文

        Returns:
            (精英 Agent 结果, 错误列表)
        """
        # 触发阶段开始回调
        if self._on_phase_start:
            self._on_phase_start("精英综合分析")

        task = self._create_agent_task(AgentType.ELITE, context)
        result = self._scheduler.run_tasks_sync([task])

        # 触发阶段完成回调（精英综合分析占 20%）
        if self._on_phase_complete:
            self._on_phase_complete("精英综合分析", 20)

        if result.tasks and result.tasks[0].result:
            return result.tasks[0].result, []

        # 返回空结果（包含 metadata 避免报告生成出错）
        errors = []
        if result.tasks and result.tasks[0].error:
            errors.append({
                "task_id": result.tasks[0].id,
                "agent_type": "elite",
                "error": result.tasks[0].error,
            })

        return AgentResult(
            agent_type="elite",
            agent_name="综合分析专家",
            discoveries=[],
            handoffs_created=0,
            metadata={"error": result.tasks[0].error if result.tasks and result.tasks[0].error else "unknown error"},
        ), errors

    def _create_agent_tasks(
        self,
        agent_types: list[AgentType],
        context: dict[str, Any],
    ) -> list[Any]:
        """创建 Agent 任务列表。

        Args:
            agent_types: Agent 类型列表
            context: 执行上下文

        Returns:
            AgentTask 列表
        """
        return [
            self._create_agent_task(agent_type, context)
            for agent_type in agent_types
        ]

    def _create_agent_task(
        self,
        agent_type: AgentType,
        context: dict[str, Any],
    ) -> Any:
        """创建单个 Agent 任务。

        Args:
            agent_type: Agent 类型
            context: 执行上下文

        Returns:
            AgentTask 对象
        """
        agent_class = self.AGENT_CLASSES.get(agent_type)
        if not agent_class:
            raise ValueError(f"Unknown agent type: {agent_type}")

        # 传递搜索工具给 Agent
        agent = agent_class(search_tool=self._search_tool)

        return AgentTask(
            id=str(uuid.uuid4()),
            agent=agent,
            context=context,
        )

    def _collect_red_arguments(self, red_result: AgentResult) -> str:
        """收集红队观点。

        Args:
            red_result: 红队结果

        Returns:
            红队观点摘要
        """
        arguments = []

        for discovery in red_result.discoveries:
            if isinstance(discovery, dict):
                content = discovery.get("content", "")
            else:
                content = str(discovery)
            arguments.append(content)

        return "\n".join(arguments[:5])  # 最多 5 条

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
