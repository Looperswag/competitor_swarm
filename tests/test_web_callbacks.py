"""WebSocket 进度回调辅助函数测试。"""

from src.web import app as web_app


def test_build_ws_progress_callbacks_emits_expected_payloads(monkeypatch):
    """回调构建器应发送预期的事件载荷。"""
    payloads = []

    monkeypatch.setattr(
        web_app,
        "_schedule_ws_message",
        lambda loop, websocket, payload: payloads.append(payload),
    )

    on_phase_start, on_phase_complete, on_agent_start = web_app._build_ws_progress_callbacks(
        loop=object(),
        websocket=object(),
    )

    on_phase_start("基础分析")
    on_phase_complete("基础分析", 40)
    on_agent_start("侦察专家")

    assert payloads == [
        {
            "type": "phase_started",
            "phase": "基础分析",
        },
        {
            "type": "phase_completed",
            "phase": "基础分析",
            "progress": 40,
        },
        {
            "type": "agent_started",
            "agent": "侦察专家",
        },
    ]


def test_schedule_ws_message_uses_threadsafe_sender(monkeypatch):
    """调度函数应通过 run_coroutine_threadsafe 发送并附带 timestamp。"""
    captured: dict[str, object] = {}

    class _FakeAwaitable:
        def __await__(self):
            if False:
                yield None
            return None

    class _FakeFuture:
        def add_done_callback(self, callback):
            callback(self)

        def result(self):
            return None

    def _fake_send_personal(message, websocket):
        captured["message"] = message
        captured["websocket"] = websocket
        return _FakeAwaitable()

    def _fake_run_coroutine_threadsafe(coro, loop):
        captured["loop"] = loop
        captured["coro"] = coro
        return _FakeFuture()

    monkeypatch.setattr(web_app.manager, "send_personal", _fake_send_personal)
    monkeypatch.setattr(web_app.asyncio, "run_coroutine_threadsafe", _fake_run_coroutine_threadsafe)

    websocket = object()
    loop = object()
    web_app._schedule_ws_message(
        loop=loop,
        websocket=websocket,
        payload={"type": "phase_started", "phase": "基础分析"},
    )

    assert captured["loop"] is loop
    assert captured["websocket"] is websocket
    assert captured["message"]["type"] == "phase_started"
    assert captured["message"]["phase"] == "基础分析"
    assert "timestamp" in captured["message"]
