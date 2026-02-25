"""Async analysis job manager for web API endpoints."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.coordinator import Coordinator
from src.environment import StigmergyEnvironment
from src.error_types import ErrorType
from src.reporting import get_html_generator
from src.utils.config import get_config

logger = logging.getLogger(__name__)


class AnalysisJobStatus(str, Enum):
    """后台分析任务状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass
class AnalysisJobState:
    """后台任务状态快照。"""

    job_id: str
    target: str
    competitors: list[str] | None
    focus_areas: list[str] | None
    status: AnalysisJobStatus = AnalysisJobStatus.QUEUED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    timeout_seconds: int | None = None
    progress: int = 0
    phase: str | None = None
    active_agent: str | None = None
    run_id: str | None = None
    duration: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    _finished_epoch: float | None = field(default=None, repr=False)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status.value,
            "target": self.target,
            "competitors": self.competitors,
            "focus_areas": self.focus_areas,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "timeout_seconds": self.timeout_seconds,
            "progress": self.progress,
            "phase": self.phase,
            "active_agent": self.active_agent,
            "run_id": self.run_id,
            "duration": self.duration,
        }
        if self.result is not None:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error
        return payload


def resolve_sync_timeout_seconds() -> int:
    """解析同步分析超时预算。"""
    config = get_config()
    web_timeout = getattr(config.web, "sync_timeout_seconds", None)
    if web_timeout is None:
        web_timeout = getattr(config.scheduler, "timeout", 300)
    try:
        return max(1, int(web_timeout))
    except (TypeError, ValueError):
        return 300


def build_timeout_error(
    *,
    target: str,
    timeout_seconds: int,
    run_id: str | None = None,
    hint_suffix: str = "",
) -> dict[str, Any]:
    """构建统一超时错误结构。"""
    hint = "Analysis timed out; reduce fan-out, or switch to async jobs endpoint."
    if hint_suffix:
        hint = f"{hint} {hint_suffix}".strip()
    return {
        "error_type": ErrorType.UPSTREAM_TIMEOUT.value,
        "message": f"Analysis for '{target}' timed out after {timeout_seconds} seconds",
        "hint": hint,
        "timeout_seconds": timeout_seconds,
        "run_id": run_id,
    }


class AnalysisJobManager:
    """进程内异步任务管理器。"""

    def __init__(self, max_workers: int = 2, ttl_seconds: int = 3600) -> None:
        self._max_workers = max(1, int(max_workers))
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._jobs: dict[str, AnalysisJobState] = {}
        self._jobs_lock = asyncio.Lock()
        self._worker_tasks: list[asyncio.Task[Any]] = []
        self._cleanup_task: asyncio.Task[Any] | None = None
        self._started = False

    async def start(self) -> None:
        """启动 worker 与清理任务。"""
        if self._started:
            return
        self._started = True
        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(idx), name=f"analysis-job-worker-{idx}")
            for idx in range(self._max_workers)
        ]
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(),
            name="analysis-job-cleaner",
        )
        logger.info(
            "analysis.job manager_started workers=%s ttl_seconds=%s",
            self._max_workers,
            self._ttl_seconds,
        )

    async def stop(self) -> None:
        """停止后台任务。"""
        if not self._started:
            return
        self._started = False

        for task in self._worker_tasks:
            task.cancel()
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()

        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        if self._cleanup_task is not None:
            await asyncio.gather(self._cleanup_task, return_exceptions=True)

        self._worker_tasks = []
        self._cleanup_task = None
        logger.info("analysis.job manager_stopped")

    async def create_job(
        self,
        *,
        target: str,
        competitors: list[str] | None,
        focus_areas: list[str] | None,
    ) -> AnalysisJobState:
        """创建分析任务并入队。"""
        job_id = uuid.uuid4().hex
        state = AnalysisJobState(
            job_id=job_id,
            target=target,
            competitors=competitors,
            focus_areas=focus_areas,
        )
        async with self._jobs_lock:
            self._jobs[job_id] = state

        await self._queue.put(job_id)
        logger.info(
            "analysis.job queued job_id=%s target=%s",
            job_id,
            target,
        )
        return state

    async def get_job(self, job_id: str) -> AnalysisJobState | None:
        """按 ID 查询任务。"""
        async with self._jobs_lock:
            return self._jobs.get(job_id)

    async def get_job_payload(self, job_id: str) -> dict[str, Any] | None:
        """按 ID 查询任务并序列化。"""
        state = await self.get_job(job_id)
        if state is None:
            return None
        return state.to_payload()

    async def _worker_loop(self, worker_index: int) -> None:
        """worker 主循环。"""
        while True:
            job_id = await self._queue.get()
            try:
                await self._process_job(job_id, worker_index=worker_index)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "analysis.job worker_error worker=%s job_id=%s",
                    worker_index,
                    job_id,
                )
            finally:
                self._queue.task_done()

    async def _process_job(self, job_id: str, *, worker_index: int) -> None:
        """执行单个任务。"""
        job_state = await self.get_job(job_id)
        if job_state is None:
            return

        timeout_seconds = resolve_sync_timeout_seconds()
        await self._mark_running(job_id, timeout_seconds=timeout_seconds)

        environment = StigmergyEnvironment(cache_path=get_config().cache.path)
        loop = asyncio.get_running_loop()
        phase_progress = {
            "信息收集": 30,
            "交叉验证": 20,
            "红蓝队对抗": 30,
            "报告综合": 20,
        }
        run_started = time.monotonic()

        def on_phase_start(phase_name: str) -> None:
            self._notify_progress_threadsafe(loop, job_id, phase=phase_name)

        def on_phase_complete(phase_name: str, delta: int) -> None:
            step = int(delta or phase_progress.get(phase_name, 0))
            self._notify_progress_threadsafe(
                loop,
                job_id,
                phase=phase_name,
                progress_delta=step,
            )

        def on_agent_start(agent_name: str) -> None:
            self._notify_progress_threadsafe(
                loop,
                job_id,
                active_agent=agent_name,
            )

        coordinator = Coordinator(
            environment=environment,
            on_phase_start=on_phase_start,
            on_phase_complete=on_phase_complete,
            on_agent_start=on_agent_start,
        )

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    coordinator.analyze,
                    job_state.target,
                    job_state.competitors,
                    job_state.focus_areas,
                ),
                timeout=timeout_seconds,
            )
            html_generator = get_html_generator()
            html_path, json_path = await asyncio.gather(
                asyncio.to_thread(html_generator.generate_html, result),
                asyncio.to_thread(html_generator.generate_json, result),
            )
            run_id = str(result.metadata.get("run_id") or "").strip() or environment.current_run_id
            payload = {
                "success": result.success,
                "target": result.target,
                "duration": result.duration,
                "total_discoveries": result.metadata.get("total_discoveries", 0),
                "html_report": f"/static/{Path(html_path).name}",
                "json_data": f"/static/{Path(json_path).name}",
            }
            await self._mark_succeeded(
                job_id,
                result_payload=payload,
                run_id=run_id,
                duration=time.monotonic() - run_started,
            )
            logger.info(
                "analysis.job success job_id=%s run_id=%s worker=%s duration=%.2fs timeout_budget=%ss",
                job_id,
                run_id,
                worker_index,
                time.monotonic() - run_started,
                timeout_seconds,
            )
        except asyncio.TimeoutError:
            run_id = environment.current_run_id
            error = build_timeout_error(
                target=job_state.target,
                timeout_seconds=timeout_seconds,
                run_id=run_id,
            )
            await self._mark_terminal_error(
                job_id,
                status=AnalysisJobStatus.TIMED_OUT,
                error=error,
                run_id=run_id,
                duration=time.monotonic() - run_started,
            )
            logger.warning(
                "analysis.job timeout job_id=%s run_id=%s worker=%s timeout_budget=%ss",
                job_id,
                run_id,
                worker_index,
                timeout_seconds,
            )
        except Exception as exc:
            run_id = environment.current_run_id
            error = {
                "error_type": "UNKNOWN",
                "message": str(exc),
                "hint": "Inspect server logs for traceback and upstream failures.",
                "run_id": run_id,
            }
            await self._mark_terminal_error(
                job_id,
                status=AnalysisJobStatus.FAILED,
                error=error,
                run_id=run_id,
                duration=time.monotonic() - run_started,
            )
            logger.exception(
                "analysis.job failed job_id=%s run_id=%s worker=%s error=%s",
                job_id,
                run_id,
                worker_index,
                exc,
            )

    def _notify_progress_threadsafe(
        self,
        loop: asyncio.AbstractEventLoop,
        job_id: str,
        *,
        phase: str | None = None,
        progress_delta: int = 0,
        active_agent: str | None = None,
    ) -> None:
        """从 worker 线程向主循环投递进度更新。"""

        def _schedule() -> None:
            asyncio.create_task(
                self._update_progress(
                    job_id,
                    phase=phase,
                    progress_delta=progress_delta,
                    active_agent=active_agent,
                )
            )

        loop.call_soon_threadsafe(_schedule)

    async def _mark_running(self, job_id: str, *, timeout_seconds: int) -> None:
        async with self._jobs_lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            state.status = AnalysisJobStatus.RUNNING
            state.started_at = datetime.now().isoformat()
            state.updated_at = state.started_at
            state.timeout_seconds = timeout_seconds
            state.progress = max(state.progress, 1)

    async def _mark_succeeded(
        self,
        job_id: str,
        *,
        result_payload: dict[str, Any],
        run_id: str | None,
        duration: float,
    ) -> None:
        async with self._jobs_lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            now_iso = datetime.now().isoformat()
            state.status = AnalysisJobStatus.SUCCEEDED
            state.updated_at = now_iso
            state.finished_at = now_iso
            state._finished_epoch = time.time()
            state.progress = 100
            state.phase = "completed"
            state.active_agent = None
            state.run_id = run_id
            state.duration = duration
            state.result = result_payload
            state.error = None

    async def _mark_terminal_error(
        self,
        job_id: str,
        *,
        status: AnalysisJobStatus,
        error: dict[str, Any],
        run_id: str | None,
        duration: float,
    ) -> None:
        async with self._jobs_lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            now_iso = datetime.now().isoformat()
            state.status = status
            state.updated_at = now_iso
            state.finished_at = now_iso
            state._finished_epoch = time.time()
            state.run_id = run_id
            state.duration = duration
            state.error = error
            state.active_agent = None

    async def _update_progress(
        self,
        job_id: str,
        *,
        phase: str | None = None,
        progress_delta: int = 0,
        active_agent: str | None = None,
    ) -> None:
        async with self._jobs_lock:
            state = self._jobs.get(job_id)
            if state is None or state.status != AnalysisJobStatus.RUNNING:
                return

            if phase:
                state.phase = phase
            if active_agent:
                state.active_agent = active_agent
            if progress_delta > 0:
                state.progress = min(95, max(0, state.progress + progress_delta))
            state.updated_at = datetime.now().isoformat()

    async def _cleanup_loop(self) -> None:
        """定期清理过期任务。"""
        interval = min(60, max(1, self._ttl_seconds // 2 or 1))
        while True:
            await asyncio.sleep(interval)
            await self._cleanup_expired_jobs()

    async def _cleanup_expired_jobs(self) -> None:
        now = time.time()
        expired_ids: list[str] = []
        async with self._jobs_lock:
            for job_id, state in self._jobs.items():
                if not self._is_terminal(state.status):
                    continue
                if state._finished_epoch is None:
                    continue
                if now - state._finished_epoch > self._ttl_seconds:
                    expired_ids.append(job_id)

            for job_id in expired_ids:
                self._jobs.pop(job_id, None)

        if expired_ids:
            logger.info("analysis.job cleaned expired_count=%s", len(expired_ids))

    @staticmethod
    def _is_terminal(status: AnalysisJobStatus) -> bool:
        return status in {
            AnalysisJobStatus.SUCCEEDED,
            AnalysisJobStatus.FAILED,
            AnalysisJobStatus.TIMED_OUT,
        }


_job_manager: AnalysisJobManager | None = None


def get_job_manager() -> AnalysisJobManager:
    """获取全局任务管理器实例。"""
    global _job_manager
    if _job_manager is None:
        config = get_config()
        _job_manager = AnalysisJobManager(
            max_workers=getattr(config.web, "async_job_workers", 2),
            ttl_seconds=getattr(config.web, "async_job_ttl_seconds", 3600),
        )
    return _job_manager


def reset_job_manager() -> None:
    """重置全局任务管理器实例。"""
    global _job_manager
    _job_manager = None
