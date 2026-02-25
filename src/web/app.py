"""FastAPI Web 应用。

提供 REST API 和 WebSocket 服务。
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.coordinator import Coordinator, reset_coordinator
from src.environment import StigmergyEnvironment
from src.reporting import get_html_generator
from src.scheduler import get_recurring_scheduler, reset_recurring_scheduler, RecurringJob
from src.utils.config import get_config
from src.web.jobs import (
    AnalysisJobStatus,
    build_timeout_error,
    get_job_manager,
    reset_job_manager,
    resolve_sync_timeout_seconds,
)

logger = logging.getLogger(__name__)


# WebSocket 连接管理器
class ConnectionManager:
    """WebSocket 连接管理器。"""

    def __init__(self) -> None:
        """初始化连接管理器。"""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """接受新连接。"""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """移除连接。"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """广播消息给所有连接。"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

    async def send_personal(self, message: dict[str, Any], websocket: WebSocket) -> None:
        """发送消息给特定连接。"""
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)


manager = ConnectionManager()


def _suppress_future_exception(future: Any) -> None:
    """吞掉后台发送任务异常，避免噪音日志。"""
    try:
        future.result()
    except Exception:
        pass


def _schedule_ws_message(
    loop: asyncio.AbstractEventLoop,
    websocket: WebSocket,
    payload: dict[str, Any],
) -> None:
    """线程安全地投递 WebSocket 消息。"""
    message = {
        **payload,
        "timestamp": datetime.now().isoformat(),
    }
    future = asyncio.run_coroutine_threadsafe(
        manager.send_personal(message, websocket),
        loop,
    )
    future.add_done_callback(_suppress_future_exception)


def _build_ws_progress_callbacks(
    loop: asyncio.AbstractEventLoop,
    websocket: WebSocket,
) -> tuple[
    Callable[[str], None],
    Callable[[str, int], None],
    Callable[[str], None],
]:
    """构建供 Coordinator 使用的同步回调。"""

    def on_phase_start(phase_name: str) -> None:
        _schedule_ws_message(
            loop,
            websocket,
            {
                "type": "phase_started",
                "phase": phase_name,
            },
        )

    def on_phase_complete(phase_name: str, progress: int) -> None:
        _schedule_ws_message(
            loop,
            websocket,
            {
                "type": "phase_completed",
                "phase": phase_name,
                "progress": progress,
            },
        )

    def on_agent_start(agent_name: str) -> None:
        _schedule_ws_message(
            loop,
            websocket,
            {
                "type": "agent_started",
                "agent": agent_name,
            },
        )

    return on_phase_start, on_phase_complete, on_agent_start


# 请求/响应模型
class AnalyzeRequest(BaseModel):
    """分析请求模型。"""

    target: str
    competitors: list[str] | None = None
    focus_areas: list[str] | None = None


class AnalyzeErrorResponse(BaseModel):
    """分析错误响应。"""

    success: bool
    error: dict[str, Any]


class AnalyzeJobCreateResponse(BaseModel):
    """异步任务创建响应。"""

    job_id: str
    status: str
    created_at: str
    status_url: str
    target: str


class AnalyzeJobStatusResponse(BaseModel):
    """异步任务状态响应。"""

    job_id: str
    status: str
    target: str
    competitors: list[str] | None = None
    focus_areas: list[str] | None = None
    created_at: str
    updated_at: str
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


# 定时任务请求/响应模型
class ScheduledJobCreateRequest(BaseModel):
    """创建定时任务请求。"""

    target: str
    competitors: list[str] | None = None
    focus_areas: list[str] | None = None
    interval_hours: int = 24
    alert_webhook: str | None = None
    alert_threshold: float = 0.2


class ScheduledJobResponse(BaseModel):
    """定时任务响应。"""

    id: str
    target: str
    competitors: list[str] | None = None
    focus_areas: list[str] | None = None
    interval_hours: int = 24
    alert_webhook: str | None = None
    alert_threshold: float = 0.2
    enabled: bool = True
    last_run: str | None = None
    next_run: str | None = None
    created_at: str = ""
    run_count: int = 0


# 应用生命周期
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时执行
    static_dir = Path(__file__).parent.parent.parent / "output"
    static_dir.mkdir(parents=True, exist_ok=True)
    job_manager = get_job_manager()
    await job_manager.start()

    # 启动定时任务调度器（如果配置启用）
    config = get_config()
    if config.recurring_jobs.enabled:
        recurring_scheduler = get_recurring_scheduler()
        await recurring_scheduler.start()

    yield

    # 关闭时执行
    await job_manager.stop()
    reset_job_manager()
    reset_coordinator()

    # 停止定时任务调度器
    if config.recurring_jobs.enabled:
        recurring_scheduler = get_recurring_scheduler()
        await recurring_scheduler.stop()
        reset_recurring_scheduler()


# 创建 FastAPI 应用
app = FastAPI(
    title="CompetitorSwarm API",
    description="竞品分析可视化系统 API",
    version="0.2.0",
    lifespan=lifespan,
)

# 挂载静态文件
static_dir = Path(__file__).parent.parent.parent / "output"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _build_coordinator(
    *,
    on_phase_start: "Callable[[str], None] | None" = None,
    on_phase_complete: "Callable[[str, int], None] | None" = None,
    on_agent_start: "Callable[[str], None] | None" = None,
) -> Coordinator:
    """构建隔离环境的 Coordinator，避免全局状态串扰。"""
    kwargs = {
        "on_phase_start": on_phase_start,
        "on_phase_complete": on_phase_complete,
        "on_agent_start": on_agent_start,
    }
    try:
        return Coordinator(
            environment=StigmergyEnvironment(cache_path=get_config().cache.path),
            **kwargs,
        )
    except TypeError:
        # 测试桩或兼容实现可能不接受 environment 参数，降级为旧构造方式。
        return Coordinator(**kwargs)


def _result_to_api_payload(result: Any) -> dict[str, Any]:
    """将 CoordinatorResult 转为 API payload。"""
    html_generator = get_html_generator()
    html_path = html_generator.generate_html(result)
    json_path = html_generator.generate_json(result)
    return {
        "success": result.success,
        "target": result.target,
        "duration": result.duration,
        "total_discoveries": result.metadata.get("total_discoveries", 0),
        "html_report": f"/static/{Path(html_path).name}",
        "json_data": f"/static/{Path(json_path).name}",
    }


def _build_sync_timeout_response(target: str, timeout_seconds: int, run_id: str | None = None) -> dict[str, Any]:
    """构建同步接口超时响应。"""
    return {
        "success": False,
        "error": build_timeout_error(
            target=target,
            timeout_seconds=timeout_seconds,
            run_id=run_id,
            hint_suffix="Consider using /api/analyze/jobs for long-running analysis.",
        ),
    }


# 根路径 - 重定向到首页
@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    """返回首页 HTML。"""
    return get_dashboard_html()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    """返回仪表盘页面。"""
    return get_dashboard_html()


@app.get("/report/{filename}")
async def get_report(filename: str) -> FileResponse:
    """获取报告文件。"""
    file_path = static_dir / filename
    if file_path.exists():
        return FileResponse(file_path)
    return FileResponse(static_dir / "404.html")


@app.post("/api/analyze")
async def api_analyze(request: AnalyzeRequest) -> dict[str, Any]:
    """执行竞品分析（API 方式）。

    Args:
        request: 分析请求

    Returns:
        分析结果
    """
    coordinator = _build_coordinator()
    timeout_seconds = resolve_sync_timeout_seconds()
    run_started = datetime.now().isoformat()

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                coordinator.analyze,
                request.target,
                request.competitors,
                request.focus_areas,
            ),
            timeout=timeout_seconds,
        )
        return _result_to_api_payload(result)
    except asyncio.TimeoutError:
        run_id = getattr(coordinator, "_environment", None)
        run_id = getattr(run_id, "current_run_id", None)
        logger.warning(
            "analysis.sync timeout target=%s run_id=%s timeout_budget=%ss started_at=%s",
            request.target,
            run_id,
            timeout_seconds,
            run_started,
        )
        return JSONResponse(
            status_code=504,
            content=_build_sync_timeout_response(
                target=request.target,
                timeout_seconds=timeout_seconds,
                run_id=run_id,
            ),
        )
    except Exception as exc:
        logger.exception("analysis.sync failed target=%s error=%s", request.target, exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "error_type": "UNKNOWN",
                    "message": str(exc),
                    "hint": "Inspect server logs for traceback and upstream failures.",
                    "run_id": None,
                },
            },
        )


@app.post("/api/analyze/jobs", status_code=202, response_model=AnalyzeJobCreateResponse)
async def api_analyze_jobs(request: AnalyzeRequest) -> dict[str, Any]:
    """创建异步分析任务。"""
    job_manager = get_job_manager()
    state = await job_manager.create_job(
        target=request.target,
        competitors=request.competitors,
        focus_areas=request.focus_areas,
    )
    return {
        "job_id": state.job_id,
        "status": state.status.value,
        "created_at": state.created_at,
        "status_url": f"/api/analyze/jobs/{state.job_id}",
        "target": state.target,
    }


@app.get("/api/analyze/jobs/{job_id}", response_model=AnalyzeJobStatusResponse)
async def api_analyze_job_status(job_id: str) -> dict[str, Any]:
    """查询异步分析任务状态。"""
    job_manager = get_job_manager()
    payload = await job_manager.get_job_payload(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return payload


# ============================================================================
# 定时任务 API 端点 (Phase 2: Scheduled Tracking)
# ============================================================================


@app.get("/api/scheduled-jobs", response_model=list[ScheduledJobResponse])
async def api_list_scheduled_jobs() -> list[dict[str, Any]]:
    """列出所有定时任务。"""
    scheduler = get_recurring_scheduler()
    jobs = scheduler.list_jobs()
    return [job.to_dict() for job in jobs]


@app.post("/api/scheduled-jobs", status_code=201, response_model=ScheduledJobResponse)
async def api_create_scheduled_job(request: ScheduledJobCreateRequest) -> dict[str, Any]:
    """创建定时分析任务。

    Args:
        request: 定时任务创建请求

    Returns:
        创建的定时任务
    """
    config = get_config()
    if not config.recurring_jobs.enabled:
        raise HTTPException(
            status_code=503,
            detail="Scheduled jobs are not enabled. Set recurring_jobs.enabled=true in config.yaml",
        )

    scheduler = get_recurring_scheduler()
    job = scheduler.schedule_job(
        target=request.target,
        competitors=request.competitors,
        focus_areas=request.focus_areas,
        interval_hours=request.interval_hours,
        alert_webhook=request.alert_webhook,
        alert_threshold=request.alert_threshold,
    )
    return job.to_dict()


@app.get("/api/scheduled-jobs/{job_id}", response_model=ScheduledJobResponse)
async def api_get_scheduled_job(job_id: str) -> dict[str, Any]:
    """获取定时任务详情。

    Args:
        job_id: 任务 ID

    Returns:
        定时任务详情
    """
    scheduler = get_recurring_scheduler()
    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Scheduled job not found: {job_id}")
    return job.to_dict()


@app.delete("/api/scheduled-jobs/{job_id}")
async def api_cancel_scheduled_job(job_id: str) -> dict[str, Any]:
    """取消定时任务。

    Args:
        job_id: 任务 ID

    Returns:
        取消结果
    """
    scheduler = get_recurring_scheduler()
    success = scheduler.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Scheduled job not found: {job_id}")
    return {"success": True, "message": f"Job {job_id} cancelled"}


@app.post("/api/scheduled-jobs/{job_id}/run", status_code=202)
async def api_run_scheduled_job_now(job_id: str) -> dict[str, Any]:
    """立即执行定时任务（触发一次性分析）。

    Args:
        job_id: 任务 ID

    Returns:
        执行状态
    """
    scheduler = get_recurring_scheduler()
    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Scheduled job not found: {job_id}")

    # 创建异步分析任务
    job_manager = get_job_manager()
    state = await job_manager.create_job(
        target=job.target,
        competitors=job.competitors if job.competitors else None,
        focus_areas=job.focus_areas if job.focus_areas else None,
    )

    return {
        "success": True,
        "message": f"Triggered immediate run for job {job_id}",
        "analysis_job_id": state.job_id,
        "status_url": f"/api/analyze/jobs/{state.job_id}",
    }


@app.websocket("/ws/analysis")
async def websocket_analysis(websocket: WebSocket) -> None:
    """WebSocket 分析端点。

    支持实时推送分析进度。
    """
    await manager.connect(websocket)
    loop = asyncio.get_running_loop()

    try:
        # 发送连接确认
        await manager.send_personal({
            "type": "connected",
            "message": "WebSocket 连接已建立",
            "timestamp": datetime.now().isoformat(),
        }, websocket)

        while True:
            # 接收消息
            data = await websocket.receive_json()

            if data.get("action") == "analyze":
                target = data.get("target")
                competitors = data.get("competitors")
                focus_areas = data.get("focus_areas")

                # 发送分析开始通知
                await manager.send_personal({
                    "type": "analysis_started",
                    "target": target,
                    "timestamp": datetime.now().isoformat(),
                }, websocket)

                on_phase_start, on_phase_complete, on_agent_start = _build_ws_progress_callbacks(
                    loop=loop,
                    websocket=websocket,
                )
                coordinator = _build_coordinator(
                    on_phase_start=on_phase_start,
                    on_phase_complete=on_phase_complete,
                    on_agent_start=on_agent_start,
                )
                timeout_seconds = resolve_sync_timeout_seconds()
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            coordinator.analyze,
                            target,
                            competitors,
                            focus_areas,
                        ),
                        timeout=timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    run_id = getattr(coordinator, "_environment", None)
                    run_id = getattr(run_id, "current_run_id", None)
                    await manager.send_personal({
                        "type": "error",
                        **build_timeout_error(
                            target=target or "",
                            timeout_seconds=timeout_seconds,
                            run_id=run_id,
                            hint_suffix="Use /api/analyze/jobs for resilient background execution.",
                        ),
                        "timestamp": datetime.now().isoformat(),
                    }, websocket)
                    continue

                # 发送完成通知
                html_generator = get_html_generator()
                html_path = html_generator.generate_html(result)

                await manager.send_personal({
                    "type": "analysis_completed",
                    "target": result.target,
                    "duration": result.duration,
                    "total_discoveries": result.metadata.get("total_discoveries", 0),
                    "html_report": f"/static/{Path(html_path).name}",
                    "timestamp": datetime.now().isoformat(),
                }, websocket)

            elif data.get("action") == "ping":
                await manager.send_personal({
                    "type": "pong",
                    "timestamp": datetime.now().isoformat(),
                }, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        await manager.send_personal({
            "type": "error",
            "error_type": "UNKNOWN",
            "message": str(e),
            "hint": "Inspect server logs for traceback and upstream failures.",
            "timestamp": datetime.now().isoformat(),
        }, websocket)
        manager.disconnect(websocket)


def get_dashboard_html() -> str:
    """获取仪表盘 HTML 页面。"""
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CompetitorSwarm - 竞品分析系统</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

        body {
            font-family: 'Inter', sans-serif;
        }

        .gradient-bg {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }

        .card-hover {
            transition: all 0.3s ease;
        }

        .card-hover:hover {
            transform: translateY(-4px);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .animate-pulse-slow {
            animation: pulse 2s ease-in-out infinite;
        }
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <!-- 导航栏 -->
    <nav class="gradient-bg text-white shadow-lg">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex items-center justify-between h-16">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 bg-white/20 rounded-lg flex items-center justify-center">
                        <span class="text-2xl">🎯</span>
                    </div>
                    <div>
                        <h1 class="text-xl font-bold">CompetitorSwarm</h1>
                        <p class="text-xs text-white/70">竞品分析可视化系统</p>
                    </div>
                </div>
                <div class="flex items-center gap-4">
                    <a href="/api/docs" target="_blank" class="text-white/80 hover:text-white text-sm">
                        API 文档
                    </a>
                </div>
            </div>
        </div>
    </nav>

    <!-- 主内容 -->
    <main class="max-w-4xl mx-auto px-4 py-12">
        <!-- 欢迎卡片 -->
        <div class="bg-white rounded-2xl shadow-xl p-8 mb-8">
            <h2 class="text-3xl font-bold text-gray-900 mb-4">
                开始竞品分析
            </h2>
            <p class="text-gray-600 mb-8">
                使用多 Agent 协作进行深度竞品分析，生成可视化报告。
            </p>

            <!-- 分析表单 -->
            <form id="analyze-form" class="space-y-6">
                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        分析目标 *
                    </label>
                    <input type="text" id="target-input" required
                           class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                           placeholder="例如：Notion、飞书、Slack...">
                </div>

                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        竞品（可选）
                    </label>
                    <input type="text" id="competitors-input"
                           class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                           placeholder="用逗号分隔，例如：Wolai, 语雀">
                </div>

                <div>
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        重点关注领域（可选）
                    </label>
                    <input type="text" id="focus-input"
                           class="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                           placeholder="用逗号分隔，例如：协作功能, 定价">
                </div>

                <button type="submit" id="submit-btn"
                        class="w-full gradient-bg text-white font-semibold py-4 px-6 rounded-lg hover:opacity-90 transition disabled:opacity-50 disabled:cursor-not-allowed">
                    开始分析
                </button>
            </form>

            <!-- 进度显示 -->
            <div id="progress-container" class="hidden mt-8">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-sm font-medium text-gray-700" id="progress-label">准备中...</span>
                    <span class="text-sm text-gray-500" id="progress-percent">0%</span>
                </div>
                <div class="w-full bg-gray-200 rounded-full h-3">
                    <div id="progress-bar" class="gradient-bg h-3 rounded-full transition-all duration-500" style="width: 0%"></div>
                </div>
                <p class="text-sm text-gray-500 mt-2" id="progress-status"></p>
            </div>
        </div>

        <!-- 功能卡片 -->
        <div class="grid md:grid-cols-3 gap-6 mb-8">
            <div class="bg-white rounded-xl p-6 card-hover shadow-md">
                <div class="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center mb-4">
                    <span class="text-2xl">🔍</span>
                </div>
                <h3 class="font-semibold text-gray-900 mb-2">多维分析</h3>
                <p class="text-sm text-gray-600">侦察、体验、技术、市场、红蓝队六大维度全面分析</p>
            </div>

            <div class="bg-white rounded-xl p-6 card-hover shadow-md">
                <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mb-4">
                    <span class="text-2xl">📊</span>
                </div>
                <h3 class="font-semibold text-gray-900 mb-2">可视化报告</h3>
                <p class="text-sm text-gray-600">生成交互式 HTML 报告，支持深色模式和图表展示</p>
            </div>

            <div class="bg-white rounded-xl p-6 card-hover shadow-md">
                <div class="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center mb-4">
                    <span class="text-2xl">⚔️</span>
                </div>
                <h3 class="font-semibold text-gray-900 mb-2">红蓝队对抗</h3>
                <p class="text-sm text-gray-600">批判性分析与辩护性回应，揭示产品全貌</p>
            </div>
        </div>

        <!-- 最近报告 -->
        <div id="recent-reports" class="bg-white rounded-2xl shadow-xl p-8">
            <h3 class="text-xl font-bold text-gray-900 mb-4">最近报告</h3>
            <p class="text-gray-500 text-sm">暂无报告，开始第一次分析吧！</p>
        </div>
    </main>

    <!-- 页脚 -->
    <footer class="text-center py-8 text-gray-500 text-sm">
        <p>由 CompetitorSwarm 竞品分析系统生成</p>
    </footer>

    <script>
        const form = document.getElementById('analyze-form');
        const submitBtn = document.getElementById('submit-btn');
        const progressContainer = document.getElementById('progress-container');
        const progressBar = document.getElementById('progress-bar');
        const progressLabel = document.getElementById('progress-label');
        const progressPercent = document.getElementById('progress-percent');
        const progressStatus = document.getElementById('progress-status');
        const phaseProgressMap = {
            '信息收集': 30,
            '交叉验证': 20,
            '红蓝队对抗': 30,
            '报告综合': 20,
        };
        const ANALYSIS_TIMEOUT_MS = 30 * 60 * 1000;

        function setProgress(value, label, status) {
            const safe = Math.max(0, Math.min(100, value));
            progressBar.style.width = safe + '%';
            progressPercent.textContent = safe + '%';
            if (label) {
                progressLabel.textContent = label;
            }
            if (typeof status === 'string') {
                progressStatus.textContent = status;
            }
        }

        function analyzeViaWebSocket(payload) {
            return new Promise((resolve, reject) => {
                const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
                const ws = new WebSocket(`${protocol}://${window.location.host}/ws/analysis`);

                let finished = false;
                let accumulatedProgress = 0;
                const timeoutId = setTimeout(() => {
                    if (finished) return;
                    finished = true;
                    try { ws.close(); } catch (e) {}
                    reject(new Error('WebSocket analysis timed out'));
                }, ANALYSIS_TIMEOUT_MS);

                function cleanup() {
                    clearTimeout(timeoutId);
                    try { ws.close(); } catch (e) {}
                }

                ws.onopen = () => {
                    setProgress(1, '连接分析服务...', '准备中');
                };

                ws.onerror = () => {
                    if (finished) return;
                    finished = true;
                    cleanup();
                    reject(new Error('WebSocket connection failed'));
                };

                ws.onclose = (event) => {
                    if (finished) return;
                    finished = true;
                    cleanup();
                    const code = Number(event && event.code ? event.code : 0);
                    reject(new Error(`WebSocket closed before completion (code=${code})`));
                };

                ws.onmessage = (event) => {
                    if (finished) return;
                    let message = {};
                    try {
                        message = JSON.parse(event.data);
                    } catch (error) {
                        return;
                    }

                    if (message.type === 'connected') {
                        ws.send(JSON.stringify({
                            action: 'analyze',
                            target: payload.target,
                            competitors: payload.competitors,
                            focus_areas: payload.focus_areas,
                        }));
                        setProgress(2, '分析启动...', '已连接');
                        return;
                    }

                    if (message.type === 'analysis_started') {
                        setProgress(4, '分析启动...', `目标: ${message.target || payload.target}`);
                        return;
                    }

                    if (message.type === 'phase_started') {
                        const phase = message.phase || '未知阶段';
                        progressLabel.textContent = `阶段进行中：${phase}`;
                        progressStatus.textContent = `当前阶段: ${phase}`;
                        return;
                    }

                    if (message.type === 'agent_started') {
                        const agent = message.agent || 'unknown';
                        progressStatus.textContent = `当前 Agent: ${agent}`;
                        return;
                    }

                    if (message.type === 'phase_completed') {
                        const phase = message.phase || '';
                        const delta = Number(message.progress || phaseProgressMap[phase] || 0);
                        accumulatedProgress = Math.min(95, accumulatedProgress + delta);
                        setProgress(accumulatedProgress, `阶段完成：${phase}`, progressStatus.textContent);
                        return;
                    }

                    if (message.type === 'analysis_completed') {
                        finished = true;
                        setProgress(100, '分析完成', '正在跳转报告...');
                        cleanup();
                        setTimeout(() => {
                            window.location.href = message.html_report;
                        }, 300);
                        resolve(message);
                        return;
                    }

                    if (message.type === 'error') {
                        finished = true;
                        cleanup();
                        reject(new Error(message.message || 'WebSocket analysis failed'));
                    }
                };
            });
        }

        async function analyzeViaLegacyHttp(payload) {
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok || !result.success) {
                const errorMessage = result?.error?.message || JSON.stringify(result);
                throw new Error(errorMessage || 'Legacy HTTP analyze failed');
            }
            return result;
        }

        async function pollAnalyzeJob(jobId, startedAt) {
            while (true) {
                const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
                if (Date.now() - startedAt > ANALYSIS_TIMEOUT_MS) {
                    throw new Error('Async job polling timed out');
                }

                const response = await fetch(`/api/analyze/jobs/${jobId}`);
                if (!response.ok) {
                    throw new Error(`Job polling failed (status=${response.status})`);
                }
                const state = await response.json();
                const status = state.status || 'unknown';
                const phase = state.phase || '等待中';
                const progress = Number(state.progress || 0);

                if (status === 'queued') {
                    setProgress(
                        Math.max(5, progress),
                        '任务已创建，等待执行...',
                        `job=${jobId.slice(0, 8)}，排队中（${elapsedSeconds}s）`
                    );
                } else if (status === 'running') {
                    setProgress(
                        Math.max(8, progress),
                        `后台执行中：${phase}`,
                        `job=${jobId.slice(0, 8)}，Agent=${state.active_agent || 'n/a'}（${elapsedSeconds}s）`
                    );
                } else if (status === 'succeeded') {
                    const result = state.result || {};
                    if (!result.html_report) {
                        throw new Error('Job succeeded but report link missing');
                    }
                    setProgress(100, '分析完成', '正在跳转报告...');
                    setTimeout(() => {
                        window.location.href = result.html_report;
                    }, 300);
                    return result;
                } else if (status === 'timed_out' || status === 'failed') {
                    const message = state?.error?.message || `Analysis job ${status}`;
                    throw new Error(message);
                }

                await new Promise((resolve) => setTimeout(resolve, 2000));
            }
        }

        async function analyzeViaHttp(payload) {
            const startedAt = Date.now();
            setProgress(5, 'HTTP 模式分析中...', 'WebSocket 不可用，已切换到异步任务模式');

            try {
                const createResponse = await fetch('/api/analyze/jobs', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(payload),
                });

                if (createResponse.ok) {
                    const createResult = await createResponse.json();
                    return await pollAnalyzeJob(createResult.job_id, startedAt);
                }

                // 兼容兜底：如果异步任务 API 不可用，回退到旧同步接口。
                setProgress(8, '切换兼容模式...', '异步任务接口不可用，回退到同步接口');
                const legacyResult = await analyzeViaLegacyHttp(payload);
                setProgress(100, '分析完成', '正在跳转报告...');
                setTimeout(() => {
                    window.location.href = legacyResult.html_report;
                }, 300);
                return legacyResult;
            } catch (error) {
                // 二次兜底：任务模式异常时仍尝试同步接口，保证历史行为可用。
                if (String(error?.message || '').includes('Job polling failed')) {
                    const legacyResult = await analyzeViaLegacyHttp(payload);
                    setProgress(100, '分析完成', '正在跳转报告...');
                    setTimeout(() => {
                        window.location.href = legacyResult.html_report;
                    }, 300);
                    return legacyResult;
                }
                throw error;
            }
        }

        form.addEventListener('submit', async (e) => {
            e.preventDefault();

            const target = document.getElementById('target-input').value.trim();
            if (!target) {
                alert('请输入分析目标');
                return;
            }

            const competitors = document.getElementById('competitors-input').value
                .split(',')
                .map(s => s.trim())
                .filter(s => s);

            const focusAreas = document.getElementById('focus-input').value
                .split(',')
                .map(s => s.trim())
                .filter(s => s);

            // 显示进度
            progressContainer.classList.remove('hidden');
            submitBtn.disabled = true;
            submitBtn.textContent = '分析中...';
            setProgress(0, '准备开始分析...', '初始化');

            const payload = {
                target,
                competitors: competitors.length > 0 ? competitors : null,
                focus_areas: focusAreas.length > 0 ? focusAreas : null,
            };

            try {
                try {
                    await analyzeViaWebSocket(payload);
                } catch (wsError) {
                    await analyzeViaHttp(payload);
                }
            } catch (error) {
                alert('请求失败：' + error.message);
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = '开始分析';
            }
        });

        // 加载最近报告
        function loadRecentReports() {}
        loadRecentReports();
    </script>
</body>
</html>'''
