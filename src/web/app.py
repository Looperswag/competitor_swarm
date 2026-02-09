"""FastAPI Web 应用。

提供 REST API 和 WebSocket 服务。
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.coordinator import Coordinator, get_coordinator, reset_coordinator
from src.reporting import get_html_generator


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


# 请求/响应模型
class AnalyzeRequest(BaseModel):
    """分析请求模型。"""

    target: str
    competitors: list[str] | None = None
    focus_areas: list[str] | None = None


# 应用生命周期
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时执行
    static_dir = Path(__file__).parent.parent.parent / "output"
    static_dir.mkdir(parents=True, exist_ok=True)

    yield

    # 关闭时执行
    reset_coordinator()


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
    coordinator = get_coordinator()

    result = coordinator.analyze(
        target=request.target,
        competitors=request.competitors,
        focus_areas=request.focus_areas,
    )

    # 生成 HTML 报告
    html_generator = get_html_generator()
    html_path = html_generator.generate_html(result)

    # 生成 JSON 数据
    json_path = html_generator.generate_json(result)

    return {
        "success": result.success,
        "target": result.target,
        "duration": result.duration,
        "total_discoveries": result.metadata.get("total_discoveries", 0),
        "html_report": f"/static/{Path(html_path).name}",
        "json_data": f"/static/{Path(json_path).name}",
    }


@app.websocket("/ws/analysis")
async def websocket_analysis(websocket: WebSocket) -> None:
    """WebSocket 分析端点。

    支持实时推送分析进度。
    """
    await manager.connect(websocket)

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

                # 创建进度回调
                async def on_phase_start(phase_name: str) -> None:
                    await manager.send_personal({
                        "type": "phase_started",
                        "phase": phase_name,
                        "timestamp": datetime.now().isoformat(),
                    }, websocket)

                async def on_phase_complete(phase_name: str, progress: int) -> None:
                    await manager.send_personal({
                        "type": "phase_completed",
                        "phase": phase_name,
                        "progress": progress,
                        "timestamp": datetime.now().isoformat(),
                    }, websocket)

                async def on_agent_start(agent_name: str) -> None:
                    await manager.send_personal({
                        "type": "agent_started",
                        "agent": agent_name,
                        "timestamp": datetime.now().isoformat(),
                    }, websocket)

                # 执行分析（在后台任务中）
                # 注意：这里简化处理，实际应该使用后台任务
                coordinator = Coordinator()

                result = coordinator.analyze(
                    target=target,
                    competitors=competitors,
                    focus_areas=focus_areas,
                )

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
            "message": str(e),
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

            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        target,
                        competitors: competitors.length > 0 ? competitors : null,
                        focus_areas: focusAreas.length > 0 ? focusAreas : null,
                    }),
                });

                const result = await response.json();

                if (result.success) {
                    // 模拟进度动画
                    let progress = 0;
                    const interval = setInterval(() => {
                        progress += 5;
                        if (progress >= 100) {
                            clearInterval(interval);
                            progress = 100;
                            // 完成后跳转到报告
                            setTimeout(() => {
                                window.location.href = result.html_report;
                            }, 500);
                        }
                        progressBar.style.width = progress + '%';
                        progressPercent.textContent = progress + '%';
                        progressLabel.textContent = '分析中...';
                    }, 100);
                } else {
                    alert('分析失败：' + JSON.stringify(result));
                }
            } catch (error) {
                alert('请求失败：' + error.message);
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = '开始分析';
            }
        });

        // 加载最近报告
        async function loadRecentReports() {
            try {
                const response = await fetch('/static/');
                // 这里简化处理，实际应该列出文件
            } catch (error) {
                console.error('加载报告失败:', error);
            }
        }

        loadRecentReports();
    </script>
</body>
</html>'''
