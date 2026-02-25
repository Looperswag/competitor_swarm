"""调度器模块。

实现并发任务调度和执行。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

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

                return

            except Exception as e:
                elapsed = time.time() - task_start_time
                last_error = f"{str(e)} (elapsed: {elapsed:.2f}s)"
                retryable_error = self._is_retryable_error(e)

                # 记录错误日志
                logger.error(
                    f"[Task {task.id}] {task.agent.agent_type.value} agent FAILED "
                    f"after {elapsed:.2f}s: {e}"
                    + (
                        ", retrying..."
                        if retryable_error and retry_count < self._max_retries
                        else ""
                    )
                )

                # 如果还有重试机会，等待后继续
                if retryable_error and retry_count < self._max_retries:
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

                return

            finally:
                task.completed_at = datetime.now().isoformat()

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        """判断异常是否可重试。"""
        retryable_types = (ConnectionError, TimeoutError, OSError)
        return isinstance(error, retryable_types)

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


# ============================================================================
# Recurring Scheduler for scheduled tracking (Phase 2 P1)
# ============================================================================

from datetime import datetime
from uuid import uuid4
import json


@dataclass
class RecurringJob:
    """定时任务定义。"""

    id: str
    target: str
    competitors: list[str] = field(default_factory=list)
    focus_areas: list[str] = field(default_factory=list)
    interval_hours: int = 24
    alert_webhook: str | None = None
    alert_threshold: float = 0.2
    enabled: bool = True
    last_run: str | None = None
    next_run: str | None = None
    created_at: str = ""
    run_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "id": self.id,
            "target": self.target,
            "competitors": list(self.competitors),
            "focus_areas": list(self.focus_areas),
            "interval_hours": self.interval_hours,
            "alert_webhook": self.alert_webhook,
            "alert_threshold": self.alert_threshold,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "created_at": self.created_at,
            "run_count": self.run_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecurringJob":
        """从字典创建。"""
        return cls(
            id=data.get("id", str(uuid4())),
            target=data.get("target", ""),
            competitors=data.get("competitors", []),
            focus_areas=data.get("focus_areas", []),
            interval_hours=data.get("interval_hours", 24),
            alert_webhook=data.get("alert_webhook"),
            alert_threshold=data.get("alert_threshold", 0.2),
            enabled=data.get("enabled", True),
            last_run=data.get("last_run"),
            next_run=data.get("next_run"),
            created_at=data.get("created_at", ""),
            run_count=data.get("run_count", 0),
        )


@dataclass
class DiffReport:
    """分析差异报告。"""

    target: str
    previous_timestamp: str
    current_timestamp: str
    change_score: float  # 0.0-1.0 变化程度

    # 变化内容
    added_conclusions: list[str] = field(default_factory=list)
    removed_conclusions: list[str] = field(default_factory=list)
    changed_conclusions: list[dict[str, Any]] = field(default_factory=list)

    added_evidence: list[str] = field(default_factory=list)
    removed_evidence: list[str] = field(default_factory=list)

    added_risks: list[str] = field(default_factory=list)
    removed_risks: list[str] = field(default_factory=list)

    # 定量指标变化
    metric_changes: list[dict[str, Any]] = field(default_factory=list)

    # 告警触发
    alerts_triggered: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "target": self.target,
            "previous_timestamp": self.previous_timestamp,
            "current_timestamp": self.current_timestamp,
            "change_score": self.change_score,
            "added_conclusions": list(self.added_conclusions),
            "removed_conclusions": list(self.removed_conclusions),
            "changed_conclusions": list(self.changed_conclusions),
            "added_evidence": list(self.added_evidence),
            "removed_evidence": list(self.removed_evidence),
            "added_risks": list(self.added_risks),
            "removed_risks": list(self.removed_risks),
            "metric_changes": list(self.metric_changes),
            "alerts_triggered": list(self.alerts_triggered),
        }


class RecurringScheduler:
    """定时任务调度器。

    管理定时分析任务，支持增量更新检测和告警。
    """

    def __init__(
        self,
        storage_path: str = "data/scheduled_jobs.json",
        max_concurrent: int = 2,
    ) -> None:
        """初始化调度器。

        Args:
            storage_path: 任务持久化存储路径
            max_concurrent: 最大并发执行数
        """
        self._jobs: dict[str, RecurringJob] = {}
        self._storage_path = storage_path
        self._max_concurrent = max_concurrent
        self._running = False
        self._task: asyncio.Task | None = None

        # 加载持久化任务
        self._load_jobs()

    def _load_jobs(self) -> None:
        """从存储加载任务。"""
        import os
        if os.path.exists(self._storage_path):
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for job_data in data.get("jobs", []):
                        job = RecurringJob.from_dict(job_data)
                        self._jobs[job.id] = job
                logger.info(f"Loaded {len(self._jobs)} recurring jobs from {self._storage_path}")
            except Exception as e:
                logger.warning(f"Failed to load jobs: {e}")

    def _save_jobs(self) -> None:
        """保存任务到存储。"""
        import os
        os.makedirs(os.path.dirname(self._storage_path) or ".", exist_ok=True)
        try:
            data = {
                "jobs": [job.to_dict() for job in self._jobs.values()],
                "updated_at": datetime.now().isoformat(),
            }
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save jobs: {e}")

    async def start(self) -> None:
        """启动调度器。"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("RecurringScheduler started")

    async def stop(self) -> None:
        """停止调度器。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("RecurringScheduler stopped")

    async def _scheduler_loop(self) -> None:
        """调度循环。"""
        while self._running:
            try:
                # 检查并执行到期的任务
                now = datetime.now()
                for job in list(self._jobs.values()):
                    if not job.enabled:
                        continue
                    if job.next_run is None:
                        continue

                    try:
                        next_run = datetime.fromisoformat(job.next_run)
                        if now >= next_run:
                            asyncio.create_task(self._run_job(job.id))
                    except (ValueError, TypeError):
                        continue

                # 每分钟检查一次
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(60)

    def schedule_job(
        self,
        target: str,
        competitors: list[str] | None = None,
        focus_areas: list[str] | None = None,
        interval_hours: int = 24,
        alert_webhook: str | None = None,
        alert_threshold: float = 0.2,
    ) -> RecurringJob:
        """创建定时任务。

        Args:
            target: 目标产品
            competitors: 竞品列表
            focus_areas: 关注领域
            interval_hours: 间隔小时数
            alert_webhook: 告警 webhook
            alert_threshold: 告警阈值

        Returns:
            创建的任务
        """
        from datetime import timedelta

        job = RecurringJob(
            id=str(uuid4()),
            target=target,
            competitors=competitors or [],
            focus_areas=focus_areas or [],
            interval_hours=interval_hours,
            alert_webhook=alert_webhook,
            alert_threshold=alert_threshold,
            enabled=True,
            created_at=datetime.now().isoformat(),
            next_run=(datetime.now() + timedelta(hours=interval_hours)).isoformat(),
        )

        self._jobs[job.id] = job
        self._save_jobs()

        logger.info(f"Created recurring job {job.id} for target '{target}'")
        return job

    def cancel_job(self, job_id: str) -> bool:
        """取消任务。

        Args:
            job_id: 任务 ID

        Returns:
            是否成功
        """
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save_jobs()
            logger.info(f"Cancelled recurring job {job_id}")
            return True
        return False

    def list_jobs(self) -> list[RecurringJob]:
        """列出所有任务。"""
        return list(self._jobs.values())

    def get_job(self, job_id: str) -> RecurringJob | None:
        """获取任务。"""
        return self._jobs.get(job_id)

    async def _run_job(self, job_id: str) -> None:
        """执行单次分析。

        Args:
            job_id: 任务 ID
        """
        job = self._jobs.get(job_id)
        if not job:
            return

        logger.info(f"Running recurring job {job_id} for target '{job.target}'")

        try:
            # TODO: 调用实际的 Coordinator 执行分析
            # 这里需要注入 Coordinator 或通过回调执行
            # 当前版本仅记录日志和更新时间戳

            job.last_run = datetime.now().isoformat()
            job.run_count += 1

            # 计算下次运行时间
            from datetime import timedelta
            job.next_run = (
                datetime.now() + timedelta(hours=job.interval_hours)
            ).isoformat()

            self._save_jobs()
            logger.info(f"Completed recurring job {job_id}, next run at {job.next_run}")

        except Exception as e:
            logger.error(f"Failed to run recurring job {job_id}: {e}")


# 全局定时调度器实例
_recurring_scheduler: RecurringScheduler | None = None


def get_recurring_scheduler() -> RecurringScheduler:
    """获取全局定时调度器实例。"""
    global _recurring_scheduler
    if _recurring_scheduler is None:
        config = get_config()
        _recurring_scheduler = RecurringScheduler(
            storage_path=config.recurring_jobs.storage_path,
            max_concurrent=config.recurring_jobs.max_concurrent,
        )
    return _recurring_scheduler


def reset_recurring_scheduler() -> None:
    """重置全局定时调度器。"""
    global _recurring_scheduler
    _recurring_scheduler = None
