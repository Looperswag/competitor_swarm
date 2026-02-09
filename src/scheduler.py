"""调度器模块。

实现并发任务调度和执行。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.utils.config import get_config
from src.handoff import HandoffContext, HandoffPriority, HandoffStatus, get_handoff_manager

# 配置日志
logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentTask:
    """Agent 任务。"""

    id: str
    agent: Any  # BaseAgent 实例
    context: dict[str, Any]
    handoff_context: HandoffContext | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "id": self.id,
            "agent_type": self.agent.agent_type.value if hasattr(self.agent, "agent_type") else "unknown",
            "context": self.context,
            "handoff_context": {
                "reasoning": self.handoff_context.reasoning,
                "suggested_actions": self.handoff_context.suggested_actions,
            } if self.handoff_context else None,
            "status": self.status.value,
            "result": str(self.result)[:200] if self.result else None,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class SchedulerResult:
    """调度器执行结果。"""

    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    cancelled_tasks: int
    tasks: list[AgentTask]
    total_duration: float  # 秒


class SimpleScheduler:
    """简单调度器。

    使用 asyncio 实现并发任务执行。
    支持任务重试和超时保护。
    """

    def __init__(
        self,
        max_concurrent: int | None = None,
        timeout: int | None = None,
        max_retries: int = 1,
        retry_backoff: float = 2.0,
        on_task_start: "Callable[[str], None] | None" = None,
        on_task_complete: "Callable[[str, bool], None] | None" = None,
    ) -> None:
        """初始化调度器。

        Args:
            max_concurrent: 最大并发数，默认从配置读取
            timeout: 单个任务超时时间（秒），默认从配置读取
            max_retries: 最大重试次数，默认 1
            retry_backoff: 重试退避倍数，默认 2.0
            on_task_start: 任务开始回调，参数为任务 ID
            on_task_complete: 任务完成回调，参数为任务 ID 和是否成功
        """
        config = get_config()
        self._max_concurrent = max_concurrent or config.scheduler.max_concurrent
        self._timeout = timeout or config.scheduler.timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff

        self._handoff_manager = get_handoff_manager()
        self._on_task_start = on_task_start
        self._on_task_complete = on_task_complete

    def run_tasks_sync(self, tasks: list[AgentTask]) -> SchedulerResult:
        """同步执行任务。

        内部使用 asyncio.run() 包装异步方法。

        Args:
            tasks: 任务列表

        Returns:
            执行结果
        """
        return asyncio.run(self.run_tasks(tasks))

    async def run_tasks(self, tasks: list[AgentTask]) -> SchedulerResult:
        """并发执行任务。

        Args:
            tasks: 任务列表

        Returns:
            执行结果
        """
        import time
        start_time = time.time()

        # 创建信号量
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def run_with_limit(task: AgentTask) -> None:
            """在信号量限制下运行任务。"""
            async with semaphore:
                await self._run_single_task(task)

        # 并发执行所有任务
        await asyncio.gather(*[run_with_limit(t) for t in tasks], return_exceptions=True)

        # 处理高优先级 handoff
        handoff_tasks = await self._process_handoffs(tasks)
        if handoff_tasks:
            tasks.extend(handoff_tasks)

        duration = time.time() - start_time

        return SchedulerResult(
            total_tasks=len(tasks),
            completed_tasks=len([t for t in tasks if t.status == TaskStatus.COMPLETED]),
            failed_tasks=len([t for t in tasks if t.status == TaskStatus.FAILED]),
            cancelled_tasks=len([t for t in tasks if t.status == TaskStatus.CANCELLED]),
            tasks=tasks,
            total_duration=duration,
        )

    async def _run_single_task(self, task: AgentTask) -> None:
        """运行单个任务（带重试机制）。

        Args:
            task: 任务对象
        """
        from datetime import datetime

        retry_count = 0
        last_error = None

        while retry_count <= self._max_retries:
            task_start_time = time.time()
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now().isoformat()

            # 触发任务开始回调
            if self._on_task_start:
                try:
                    agent_name = getattr(task.agent, "name", task.agent.agent_type.value)
                    self._on_task_start(agent_name)
                except Exception:
                    pass  # 回调失败不影响主流程

            retry_info = f" (retry {retry_count}/{self._max_retries})" if retry_count > 0 else ""
            logger.info(f"[Task {task.id}] Starting {task.agent.agent_type.value} agent{retry_info}...")

            try:
                # 创建超时
                timeout_task = asyncio.create_task(
                    self._execute_agent(task)
                )
                result = await asyncio.wait_for(timeout_task, timeout=self._timeout)

                task.result = result
                task.status = TaskStatus.COMPLETED

                # 记录成功日志
                elapsed = time.time() - task_start_time
                logger.info(
                    f"[Task {task.id}] {task.agent.agent_type.value} agent completed in {elapsed:.2f}s"
                    + (f" after {retry_count} retries" if retry_count > 0 else "")
                )

                # 触发任务完成回调（成功）
                if self._on_task_complete:
                    try:
                        self._on_task_complete(task.id, True)
                    except Exception:
                        pass

                return  # 成功则退出

            except asyncio.TimeoutError:
                elapsed = time.time() - task_start_time
                last_error = f"Task timed out after {self._timeout} seconds (actual elapsed: {elapsed:.2f}s)"

                # 记录超时日志
                logger.warning(
                    f"[Task {task.id}] {task.agent.agent_type.value} agent TIMED OUT "
                    f"after {elapsed:.2f}s (limit: {self._timeout}s)"
                    + (f", retrying..." if retry_count < self._max_retries else "")
                )

                # 如果还有重试机会，等待后继续
                if retry_count < self._max_retries:
                    retry_count += 1
                    # 退避等待
                    backoff_time = min(30, 2 ** retry_count * self._retry_backoff)
                    logger.info(f"[Task {task.id}] Waiting {backoff_time:.1f}s before retry...")
                    await asyncio.sleep(backoff_time)
                    continue

                task.error = last_error
                task.status = TaskStatus.FAILED

                # 触发任务完成回调（失败）
                if self._on_task_complete:
                    try:
                        self._on_task_complete(task.id, False)
                    except Exception:
                        pass

            except Exception as e:
                elapsed = time.time() - task_start_time
                last_error = f"{str(e)} (elapsed: {elapsed:.2f}s)"

                # 记录错误日志
                logger.error(
                    f"[Task {task.id}] {task.agent.agent_type.value} agent FAILED "
                    f"after {elapsed:.2f}s: {e}"
                    + (f", retrying..." if retry_count < self._max_retries else "")
                )

                # 如果还有重试机会，等待后继续
                if retry_count < self._max_retries:
                    retry_count += 1
                    # 退避等待
                    backoff_time = min(30, 2 ** retry_count * self._retry_backoff)
                    logger.info(f"[Task {task.id}] Waiting {backoff_time:.1f}s before retry...")
                    await asyncio.sleep(backoff_time)
                    continue

                task.error = last_error
                task.status = TaskStatus.FAILED

                # 触发任务完成回调（失败）
                if self._on_task_complete:
                    try:
                        self._on_task_complete(task.id, False)
                    except Exception:
                        pass

            finally:
                task.completed_at = datetime.now().isoformat()

    async def _execute_agent(self, task: AgentTask) -> Any:
        """执行 Agent。

        Args:
            task: 任务对象

        Returns:
            Agent 执行结果
        """
        agent = task.agent

        # 合并上下文
        execute_context = {**task.context}

        # 添加 handoff 上下文
        if task.handoff_context:
            execute_context["_handoff"] = {
                "reasoning": task.handoff_context.reasoning,
                "suggested_actions": task.handoff_context.suggested_actions,
                "relevant_data": task.handoff_context.relevant_data,
            }

        # 执行 Agent（可能是同步或异步）
        if hasattr(agent, "execute_async"):
            result = await agent.execute_async(**execute_context)
        else:
            result = await asyncio.to_thread(agent.execute, **execute_context)

        return result

    async def _process_handoffs(self, tasks: list[AgentTask]) -> list[AgentTask]:
        """处理高优先级 handoff。

        Args:
            tasks: 原始任务列表
        """
        # 获取高优先级 handoff（只处理 PENDING 状态）
        high_priority_handoffs = self._handoff_manager.get_pending_handoffs(
            min_priority=HandoffPriority.HIGH
        )

        if not high_priority_handoffs:
            return []

        # 为每个 handoff 创建新任务
        new_tasks: list[AgentTask] = []

        for handoff in high_priority_handoffs:
            # 标记为处理中，防止重复处理
            self._handoff_manager.update_status(handoff.id, HandoffStatus.IN_PROGRESS)

            # 找到对应的 agent
            target_agent = None
            for task in tasks:
                if hasattr(task.agent, "agent_type"):
                    agent_type_value = task.agent.agent_type.value
                    if agent_type_value == handoff.to_agent:
                        target_agent = task.agent
                        break

            if target_agent:
                # 创建新任务
                new_task = AgentTask(
                    id=f"handoff-{handoff.id}",
                    agent=target_agent,
                    context={},
                    handoff_context=handoff.context,
                )
                new_tasks.append(new_task)

        # 执行新任务（使用并发执行而非递归调用 run_tasks）
        if new_tasks:
            semaphore = asyncio.Semaphore(self._max_concurrent)

            async def run_with_limit(task: AgentTask) -> None:
                """在信号量限制下运行任务。"""
                async with semaphore:
                    await self._run_single_task(task)

            # 并发执行 handoff 任务（不递归处理 handoff）
            await asyncio.gather(*[run_with_limit(t) for t in new_tasks], return_exceptions=True)

            # 标记 handoff 为已完成
            for new_task in new_tasks:
                handoff_id = new_task.id.replace("handoff-", "")
                self._handoff_manager.update_status(handoff_id, HandoffStatus.COMPLETED)

        return new_tasks

    def collect_results(self, tasks: list[AgentTask]) -> dict[str, list[Any]]:
        """收集任务结果。

        Args:
            tasks: 任务列表

        Returns:
            按 Agent 类型分组的结果
        """
        results: dict[str, list[Any]] = {}

        for task in tasks:
            if task.status == TaskStatus.COMPLETED and task.result is not None:
                agent_type = task.agent.agent_type.value if hasattr(task.agent, "agent_type") else "unknown"

                if agent_type not in results:
                    results[agent_type] = []

                results[agent_type].append(task.result)

        return results

    def get_errors(self, tasks: list[AgentTask]) -> list[dict[str, Any]]:
        """获取所有错误。

        Args:
            tasks: 任务列表

        Returns:
            错误信息列表
        """
        errors = []

        for task in tasks:
            if task.status == TaskStatus.FAILED:
                errors.append({
                    "task_id": task.id,
                    "agent_type": task.agent.agent_type.value if hasattr(task.agent, "agent_type") else "unknown",
                    "error": task.error,
                })

        return errors


# 全局调度器实例（延迟加载）
_scheduler: SimpleScheduler | None = None


def get_scheduler() -> SimpleScheduler:
    """获取全局调度器实例。

    Returns:
        调度器
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = SimpleScheduler()
    return _scheduler


def reset_scheduler() -> None:
    """重置全局调度器。"""
    global _scheduler
    _scheduler = None
