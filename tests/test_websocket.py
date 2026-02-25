"""WebSocket 端到端事件流测试。"""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.coordinator import CoordinatorResult
from src.web import app as web_app


def test_ws_analysis_streams_phase_and_agent_events(monkeypatch):
    """/ws/analysis 应推送分析开始、阶段/Agent 进度和完成事件。"""

    class _FakeCoordinator:
        def __init__(self, on_phase_start=None, on_phase_complete=None, on_agent_start=None):
            self._on_phase_start = on_phase_start
            self._on_phase_complete = on_phase_complete
            self._on_agent_start = on_agent_start

        def analyze(self, target, competitors=None, focus_areas=None):
            if self._on_phase_start:
                self._on_phase_start("基础分析")
            if self._on_agent_start:
                self._on_agent_start("侦察专家")
            if self._on_phase_complete:
                self._on_phase_complete("基础分析", 40)
            if self._on_phase_start:
                self._on_phase_start("红蓝队对抗")
            if self._on_phase_complete:
                self._on_phase_complete("红蓝队对抗", 40)
            if self._on_phase_start:
                self._on_phase_start("精英综合分析")
            if self._on_phase_complete:
                self._on_phase_complete("精英综合分析", 20)

            return CoordinatorResult(
                target=target,
                success=True,
                duration=0.12,
                agent_results={},
                metadata={"total_discoveries": 7},
            )

    class _FakeHTMLGenerator:
        def generate_html(self, result):
            return "/tmp/ws_report.html"

    monkeypatch.setattr(web_app, "Coordinator", _FakeCoordinator)
    monkeypatch.setattr(web_app, "get_html_generator", lambda: _FakeHTMLGenerator())

    required_event_types = {
        "analysis_started",
        "phase_started",
        "phase_completed",
        "agent_started",
        "analysis_completed",
    }

    with TestClient(web_app.app) as client:
        with client.websocket_connect("/ws/analysis") as websocket:
            connected = websocket.receive_json()
            assert connected["type"] == "connected"

            websocket.send_json(
                {
                    "action": "analyze",
                    "target": "Notion",
                    "competitors": ["Lark"],
                    "focus_areas": ["pricing"],
                }
            )

            received_event_types = set()
            for _ in range(20):
                message = websocket.receive_json()
                received_event_types.add(message.get("type"))
                if required_event_types.issubset(received_event_types):
                    break

            assert required_event_types.issubset(received_event_types)


def test_ws_analysis_timeout_emits_structured_error(monkeypatch):
    """/ws/analysis 超时时应推送结构化错误对象。"""

    class _SlowCoordinator:
        def __init__(self, environment=None, on_phase_start=None, on_phase_complete=None, on_agent_start=None):
            self._environment = SimpleNamespace(current_run_id="run-ws-timeout")

        def analyze(self, target, competitors=None, focus_areas=None):
            time.sleep(1.5)
            return CoordinatorResult(
                target=target,
                success=True,
                duration=1.5,
                agent_results={},
                metadata={"total_discoveries": 1},
            )

    monkeypatch.setattr(web_app, "Coordinator", _SlowCoordinator)
    monkeypatch.setattr(web_app, "resolve_sync_timeout_seconds", lambda: 1)

    with TestClient(web_app.app) as client:
        with client.websocket_connect("/ws/analysis") as websocket:
            connected = websocket.receive_json()
            assert connected["type"] == "connected"

            websocket.send_json({"action": "analyze", "target": "Notion"})

            error_message = None
            for _ in range(20):
                message = websocket.receive_json()
                if message.get("type") == "error":
                    error_message = message
                    break

            assert error_message is not None
            assert error_message["error_type"] == "UPSTREAM_TIMEOUT"
            assert "hint" in error_message
            assert "Use /api/analyze/jobs" in error_message["hint"]
            assert error_message["timeout_seconds"] == 1
            assert error_message["run_id"] == "run-ws-timeout"
