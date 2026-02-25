"""后台异步任务管理器测试。"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from src.coordinator import CoordinatorResult
from src.web import jobs as jobs_module


@pytest.mark.asyncio
async def test_job_manager_status_transitions_to_succeeded(monkeypatch):
    """任务应经历 queued/running 并最终 succeeded。"""

    class _FakeCoordinator:
        def __init__(self, environment=None, on_phase_start=None, on_phase_complete=None, on_agent_start=None):
            self._on_phase_start = on_phase_start
            self._on_phase_complete = on_phase_complete
            self._on_agent_start = on_agent_start

        def analyze(self, target, competitors=None, focus_areas=None):
            if self._on_phase_start:
                self._on_phase_start("信息收集")
            if self._on_agent_start:
                self._on_agent_start("侦察专家")
            time.sleep(0.15)
            if self._on_phase_complete:
                self._on_phase_complete("信息收集", 30)
            return CoordinatorResult(
                target=target,
                success=True,
                duration=0.2,
                agent_results={},
                metadata={"total_discoveries": 9, "run_id": "run-ok"},
            )

    class _FakeHTMLGenerator:
        def generate_html(self, result):
            return "/tmp/job_ok.html"

        def generate_json(self, result):
            return "/tmp/job_ok.json"

    monkeypatch.setattr(jobs_module, "Coordinator", _FakeCoordinator)
    monkeypatch.setattr(jobs_module, "get_html_generator", lambda: _FakeHTMLGenerator())
    monkeypatch.setattr(jobs_module, "resolve_sync_timeout_seconds", lambda: 2)

    manager = jobs_module.AnalysisJobManager(max_workers=1, ttl_seconds=60)
    await manager.start()
    try:
        created = await manager.create_job(
            target="Notion",
            competitors=["Lark"],
            focus_areas=["pricing"],
        )
        seen_statuses = {created.status.value}

        deadline = time.time() + 5
        final_payload = None
        while time.time() < deadline:
            payload = await manager.get_job_payload(created.job_id)
            assert payload is not None
            seen_statuses.add(payload["status"])
            final_payload = payload
            if payload["status"] == "succeeded":
                break
            await asyncio.sleep(0.03)

        assert final_payload is not None
        assert {"queued", "running", "succeeded"}.issubset(seen_statuses)
        assert final_payload["result"]["html_report"] == "/static/job_ok.html"
        assert final_payload["result"]["json_data"] == "/static/job_ok.json"
        assert final_payload["run_id"] == "run-ok"
        assert final_payload["progress"] == 100
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_job_manager_marks_timeout_with_structured_error(monkeypatch):
    """任务超时应被标记为 timed_out 并带结构化 error。"""

    class _SlowCoordinator:
        def __init__(self, environment=None, on_phase_start=None, on_phase_complete=None, on_agent_start=None):
            self._environment = environment

        def analyze(self, target, competitors=None, focus_areas=None):
            time.sleep(2)
            return CoordinatorResult(
                target=target,
                success=True,
                duration=2.0,
                agent_results={},
                metadata={"total_discoveries": 1},
            )

    monkeypatch.setattr(jobs_module, "Coordinator", _SlowCoordinator)
    monkeypatch.setattr(jobs_module, "resolve_sync_timeout_seconds", lambda: 1)

    manager = jobs_module.AnalysisJobManager(max_workers=1, ttl_seconds=60)
    await manager.start()
    try:
        created = await manager.create_job(target="Notion", competitors=None, focus_areas=None)
        deadline = time.time() + 5
        final_payload = None
        while time.time() < deadline:
            payload = await manager.get_job_payload(created.job_id)
            assert payload is not None
            final_payload = payload
            if payload["status"] in {"timed_out", "failed", "succeeded"}:
                break
            await asyncio.sleep(0.05)

        assert final_payload is not None
        assert final_payload["status"] == "timed_out"
        assert final_payload["error"]["error_type"] == "UPSTREAM_TIMEOUT"
        assert final_payload["error"]["timeout_seconds"] == 1
    finally:
        await manager.stop()


@pytest.mark.asyncio
async def test_job_manager_cleanup_removes_expired_terminal_jobs():
    """TTL 清理应删除过期终态任务。"""
    manager = jobs_module.AnalysisJobManager(max_workers=1, ttl_seconds=1)
    state = jobs_module.AnalysisJobState(
        job_id="job-expired",
        target="Notion",
        competitors=None,
        focus_areas=None,
        status=jobs_module.AnalysisJobStatus.SUCCEEDED,
        finished_at="2026-02-13T10:00:00",
    )
    state._finished_epoch = time.time() - 5
    manager._jobs[state.job_id] = state

    await manager._cleanup_expired_jobs()

    assert state.job_id not in manager._jobs


@pytest.mark.asyncio
async def test_job_create_returns_quickly_under_500ms():
    """创建任务应快速返回，满足 API 入口快速应答预期。"""
    manager = jobs_module.AnalysisJobManager(max_workers=1, ttl_seconds=60)

    started = time.perf_counter()
    state = await manager.create_job(target="Notion", competitors=None, focus_areas=None)
    elapsed = time.perf_counter() - started

    assert state.status == jobs_module.AnalysisJobStatus.QUEUED
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_job_manager_parallel_jobs_do_not_mix_run_ids_or_reports(monkeypatch):
    """并发任务应保持 run_id 隔离，且报告路径不互相覆盖。"""

    class _FakeCoordinator:
        def __init__(self, environment=None, on_phase_start=None, on_phase_complete=None, on_agent_start=None):
            self._environment = environment

        def analyze(self, target, competitors=None, focus_areas=None):
            time.sleep(0.15)
            return CoordinatorResult(
                target=target,
                success=True,
                duration=0.2,
                agent_results={},
                metadata={"total_discoveries": 3, "run_id": f"run-{target.lower()}"},
            )

    class _FakeHTMLGenerator:
        def generate_html(self, result):
            return f"/tmp/{result.target.lower()}_report.html"

        def generate_json(self, result):
            return f"/tmp/{result.target.lower()}_report.json"

    monkeypatch.setattr(jobs_module, "Coordinator", _FakeCoordinator)
    monkeypatch.setattr(jobs_module, "get_html_generator", lambda: _FakeHTMLGenerator())
    monkeypatch.setattr(jobs_module, "resolve_sync_timeout_seconds", lambda: 5)

    manager = jobs_module.AnalysisJobManager(max_workers=2, ttl_seconds=60)
    await manager.start()
    try:
        job_a = await manager.create_job(target="Notion", competitors=None, focus_areas=None)
        job_b = await manager.create_job(target="Lark", competitors=None, focus_areas=None)

        deadline = time.time() + 5
        payload_a = None
        payload_b = None
        while time.time() < deadline:
            payload_a = await manager.get_job_payload(job_a.job_id)
            payload_b = await manager.get_job_payload(job_b.job_id)
            if (
                payload_a is not None
                and payload_b is not None
                and payload_a["status"] == "succeeded"
                and payload_b["status"] == "succeeded"
            ):
                break
            await asyncio.sleep(0.03)

        assert payload_a is not None
        assert payload_b is not None
        assert payload_a["status"] == "succeeded"
        assert payload_b["status"] == "succeeded"
        assert payload_a["run_id"] == "run-notion"
        assert payload_b["run_id"] == "run-lark"
        assert payload_a["result"]["html_report"] != payload_b["result"]["html_report"]
        assert payload_a["result"]["json_data"] != payload_b["result"]["json_data"]
    finally:
        await manager.stop()
