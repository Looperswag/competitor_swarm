"""四阶段执行引擎模块。

实现 Agent Swarm 框架的核心执行流程：
1. Information Collection - 信息收集阶段
2. Cross Validation - 交叉验证阶段
3. Adversarial Debate - 对抗辩论阶段
4. Report Synthesis - 报告综合阶段
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from src.agents.base import AgentType, AgentResult
from src.agents.scout import ScoutAgent
from src.agents.experience import ExperienceAgent
from src.agents.technical import TechnicalAgent
from src.agents.market import MarketAgent
from src.agents.red_team import RedTeamAgent
from src.agents.blue_team import BlueTeamAgent
from src.agents.elite import EliteAgent
from src.environment import StigmergyEnvironment, get_environment

# 尝试导入 Signal 结构
try:
    from src.schemas.signals import (
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

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "current_phase": self.current_phase.value,
            "completed_phases": [p.value for p in self.completed_phases],
            "phase_start_time": self.phase_start_time,
            "total_duration": self.total_duration,
            "signals_per_phase": {p.value: c for p, c in self.signals_per_phase.items()},
        }


@dataclass
class PhaseResult:
    """阶段执行结果。"""

    phase: Phase
    success: bool
    duration: float
    signal_count: int = 0
    agent_results: list[AgentResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
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
        progress_callback: Callable[[PhaseProgress], None] | None = None,
    ) -> None:
        """初始化阶段执行器。

        Args:
            environment: 共享环境
            debate_rounds: 辩论轮数
            min_confidence: 最低置信度阈值
            progress_callback: 进度回调函数
        """
        self._environment = environment or get_environment()
        self._debate_rounds = debate_rounds
        self._min_confidence = min_confidence
        self._progress_callback = progress_callback

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

            # Phase 2: Cross Validation
            validation_result = self._execute_validation_phase(context)
            self._progress.completed_phases.append(Phase.VALIDATION)
            self._progress.signals_per_phase[Phase.VALIDATION] = validation_result.signal_count
            self._progress.agent_results[Phase.VALIDATION] = validation_result.agent_results

            # Phase 3: Adversarial Debate
            debate_result = self._execute_debate_phase(context)
            self._progress.completed_phases.append(Phase.DEBATE)
            self._progress.signals_per_phase[Phase.DEBATE] = debate_result.signal_count
            self._progress.agent_results[Phase.DEBATE] = debate_result.agent_results

            # Phase 4: Report Synthesis
            synthesis_result = self._execute_synthesis_phase(context)
            self._progress.completed_phases.append(Phase.SYNTHESIS)
            self._progress.signals_per_phase[Phase.SYNTHESIS] = synthesis_result.signal_count
            self._progress.agent_results[Phase.SYNTHESIS] = synthesis_result.agent_results

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
            return self._progress

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
            ScoutAgent(search_tool=search_tool),
            ExperienceAgent(search_tool=search_tool),
            TechnicalAgent(search_tool=search_tool),
            MarketAgent(search_tool=search_tool),
        ]

        agent_results = []
        errors = []

        # 执行每个 Agent
        for agent in agents:
            try:
                result = agent.execute(**context)
                agent_results.append(result)
            except Exception as e:
                errors.append(f"{agent.agent_type.value}: {str(e)}")

        # 统计信号数量
        signal_count = self._environment.signal_count if SIGNALS_AVAILABLE else self._environment.discovery_count

        return PhaseResult(
            phase=Phase.COLLECTION,
            success=len(errors) == 0,
            duration=time.time() - start_time,
            signal_count=signal_count,
            agent_results=agent_results,
            errors=errors,
            metadata={"agents_executed": len(agents)},
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
        verified_count = 0
        filtered_count = 0

        # 按维度验证
        for dimension_name, agent_type in self.DIMENSION_AGENTS.items():
            try:
                # 获取该维度的信号
                dimension = Dimension[dimension_name.upper()]
                signals = self._environment.get_signals_by_dimension(
                    dimension=dimension,
                    min_confidence=0.0,  # 获取所有信号进行验证
                )

                if not signals:
                    continue

                # 验证每个信号
                for signal in signals:
                    # 过滤低置信度信号
                    if signal.confidence < self._min_confidence:
                        filtered_count += 1
                        continue

                    # 标记为已验证（简化版本，实际应该由验证 Agent 执行）
                    verified_signal = signal.with_updated_strength(
                        signal.strength,
                        verifier="validator",
                    )
                    self._environment._signals[verified_signal.id] = verified_signal
                    verified_count += 1

            except Exception as e:
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
            metadata={
                "verified_count": verified_count,
                "filtered_count": filtered_count,
            },
        )

    def _execute_debate_phase(
        self,
        context: dict[str, Any],
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
        errors = []

        # 创建红队
        try:
            red_agent = RedTeamAgent()
            red_result = red_agent.execute(**context)
            agent_results.append(red_result)

            # 收集红队观点
            red_arguments = self._extract_debate_points(red_result)

            # 蓝队接收红队观点
            blue_context = {
                **context,
                "red_team_arguments": red_arguments,
            }
            blue_agent = BlueTeamAgent()
            blue_result = blue_agent.execute(**blue_context)
            agent_results.append(blue_result)

            # 收集蓝队观点
            blue_arguments = self._extract_debate_points(blue_result)

            # 多轮辩论
            for round_num in range(1, self._debate_rounds):
                # 红队反驳
                red_context = {
                    **context,
                    "blue_team_arguments": blue_arguments,
                    "round": round_num + 1,
                }
                red_result = red_agent.execute(**red_context)
                agent_results.append(red_result)
                red_arguments = self._extract_debate_points(red_result)

                # 蓝队再反驳
                blue_context = {
                    **context,
                    "red_team_arguments": red_arguments,
                    "round": round_num + 1,
                }
                blue_result = blue_agent.execute(**blue_context)
                agent_results.append(blue_result)
                blue_arguments = self._extract_debate_points(blue_result)

            # 更新信号强度（基于辩论结果）
            if SIGNALS_AVAILABLE:
                self._update_signal_strengths_from_debate(red_arguments, blue_arguments)

        except Exception as e:
            errors.append(str(e))

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
                "red_points": len(red_arguments) if 'red_arguments' in locals() else 0,
                "blue_points": len(blue_arguments) if 'blue_arguments' in locals() else 0,
            },
        )

    def _execute_synthesis_phase(
        self,
        context: dict[str, Any],
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
            elite_agent = EliteAgent()
            elite_result = elite_agent.execute(**context)

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
                errors=[str(e)],
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
                content = discovery.get("content", "")
            else:
                content = str(discovery)

            if content:
                points.append(content)

        return points[:10]  # 最多返回 10 个观点

    def _update_signal_strengths_from_debate(
        self,
        red_arguments: list[str],
        blue_arguments: list[str],
    ) -> None:
        """根据辩论结果更新信号强度。

        简化版本：基于辩论观点数量调整强度

        Args:
            red_arguments: 红队观点
            blue_arguments: 蓝队观点
        """
        if not SIGNALS_AVAILABLE:
            return

        # 获取所有已验证信号
        all_signals = list(self._environment._signals.values())

        for signal in all_signals:
            if not signal.verified:
                continue

            # 简化的强度调整逻辑
            # 实际应该基于信号内容与辩论观点的相关性
            strength_adjustment = 0.0

            # 如果红队观点多，略微降低强度（表示有争议）
            if len(red_arguments) > len(blue_arguments):
                strength_adjustment = -0.05
            elif len(blue_arguments) > len(red_arguments):
                strength_adjustment = 0.05

            if strength_adjustment != 0.0:
                new_strength = max(0.0, min(1.0, signal.strength + strength_adjustment))
                updated_signal = signal.with_updated_strength(
                    new_strength,
                    verifier="debate",
                    debate_point=f"Strength adjusted from {signal.strength:.2f} to {new_strength:.2f}",
                )
                self._environment._signals[updated_signal.id] = updated_signal


def create_phase_executor(
    environment: StigmergyEnvironment | None = None,
    debate_rounds: int = 3,
    min_confidence: float = 0.3,
    progress_callback: Callable[[PhaseProgress], None] | None = None,
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
    return PhaseExecutor(
        environment=environment,
        debate_rounds=debate_rounds,
        min_confidence=min_confidence,
        progress_callback=progress_callback,
    )
