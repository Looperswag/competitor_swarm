"""Web API 行为测试。"""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.coordinator import CoordinatorResult
from src.web import app as web_app
from src.web.jobs import AnalysisJobStatus


def test_api_analyze_returns_structured_504_on_timeout(monkeypatch):
    """同步分析超时应返回结构化 504，而不是 500。"""

    class _SlowCoordinator:
        def __init__(self):
            self._environment = SimpleNamespace(current_run_id="run-timeout")

        def analyze(self, target, competitors=None, focus_areas=None):
            time.sleep(2)
            return CoordinatorResult(
                target=target,
                success=True,
                duration=2.0,
                agent_results={},
                metadata={"total_discoveries": 1},
            )

    monkeypatch.setattr(web_app, "_build_coordinator", lambda **kwargs: _SlowCoordinator())
    monkeypatch.setattr(web_app, "resolve_sync_timeout_seconds", lambda: 1)

    with TestClient(web_app.app, raise_server_exceptions=False) as client:
        response = client.post("/api/analyze", json={"target": "Notion"})

    assert response.status_code == 504
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["error_type"] == "UPSTREAM_TIMEOUT"
    assert payload["error"]["timeout_seconds"] == 1
    assert payload["error"]["run_id"] == "run-timeout"


def test_api_analyze_success_response_keeps_legacy_shape(monkeypatch):
    """同步分析成功时应保持既有响应字段。"""

    class _FastCoordinator:
        def __init__(self):
            self._environment = SimpleNamespace(current_run_id="run-ok")

        def analyze(self, target, competitors=None, focus_areas=None):
            return CoordinatorResult(
                target=target,
                success=True,
                duration=0.25,
                agent_results={},
                metadata={"total_discoveries": 7},
            )

    class _FakeHTMLGenerator:
        def generate_html(self, result):
            return "/tmp/report.html"

        def generate_json(self, result):
            return "/tmp/report.json"

    monkeypatch.setattr(web_app, "_build_coordinator", lambda **kwargs: _FastCoordinator())
    monkeypatch.setattr(web_app, "get_html_generator", lambda: _FakeHTMLGenerator())
    monkeypatch.setattr(web_app, "resolve_sync_timeout_seconds", lambda: 5)

    with TestClient(web_app.app) as client:
        response = client.post("/api/analyze", json={"target": "Notion"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["target"] == "Notion"
    assert payload["total_discoveries"] == 7
    assert payload["html_report"] == "/static/report.html"
    assert payload["json_data"] == "/static/report.json"


def test_async_job_endpoints_create_and_fetch(monkeypatch):
    """异步任务接口应返回 job_id 并可查询状态。"""

    class _FakeJobManager:
        async def start(self):
            return None

        async def stop(self):
            return None

        async def create_job(self, *, target, competitors, focus_areas):
            return SimpleNamespace(
                job_id="job-1",
                status=AnalysisJobStatus.QUEUED,
                created_at="2026-02-13T16:30:00",
                target=target,
            )

        async def get_job_payload(self, job_id):
            if job_id != "job-1":
                return None
            return {
                "job_id": "job-1",
                "status": "running",
                "target": "Notion",
                "competitors": ["Lark"],
                "focus_areas": ["pricing"],
                "created_at": "2026-02-13T16:30:00",
                "updated_at": "2026-02-13T16:30:01",
                "started_at": "2026-02-13T16:30:01",
                "finished_at": None,
                "timeout_seconds": 300,
                "progress": 40,
                "phase": "信息收集",
                "active_agent": "侦察专家",
                "run_id": "run-1",
                "duration": None,
                "result": None,
                "error": None,
            }

    fake_manager = _FakeJobManager()
    monkeypatch.setattr(web_app, "get_job_manager", lambda: fake_manager)

    with TestClient(web_app.app) as client:
        started = time.perf_counter()
        create_response = client.post(
            "/api/analyze/jobs",
            json={"target": "Notion", "competitors": ["Lark"], "focus_areas": ["pricing"]},
        )
        create_elapsed = time.perf_counter() - started
        status_response = client.get("/api/analyze/jobs/job-1")
        not_found_response = client.get("/api/analyze/jobs/not-exists")

    assert create_response.status_code == 202
    assert create_elapsed < 0.5
    create_payload = create_response.json()
    assert create_payload["job_id"] == "job-1"
    assert create_payload["status"] == "queued"
    assert create_payload["status_url"] == "/api/analyze/jobs/job-1"

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["status"] == "running"
    assert status_payload["phase"] == "信息收集"
    assert status_payload["progress"] == 40

    assert not_found_response.status_code == 404
