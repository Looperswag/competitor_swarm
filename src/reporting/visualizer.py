"""HTML 可视化报告生成器模块。

生成交互式、现代化的 HTML 报告。
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.coordinator import CoordinatorResult
from src.reporting.formatters import Formatters


class HTMLReportGenerator:
    """HTML 报告生成器。

    生成包含内嵌 CSS 和 JavaScript 的独立 HTML 文件，
    支持深色/浅色模式切换、数据可视化图表、响应式设计。
    """

    # Agent 类型显示配置
    AGENT_CONFIG = {
        "scout": {"icon": "🔍", "name": "侦察分析", "color": "#6366f1"},
        "experience": {"icon": "🎨", "name": "体验分析", "color": "#ec4899"},
        "technical": {"icon": "🔬", "name": "技术分析", "color": "#14b8a6"},
        "market": {"icon": "📊", "name": "市场分析", "color": "#f59e0b"},
        "red_team": {"icon": "⚔️", "name": "红队批判", "color": "#ef4444"},
        "blue_team": {"icon": "🛡️", "name": "蓝队辩护", "color": "#3b82f6"},
        "elite": {"icon": "👑", "name": "综合分析", "color": "#8b5cf6"},
    }

    def __init__(self, output_path: str | None = None) -> None:
        """初始化 HTML 报告生成器。

        Args:
            output_path: 输出目录路径
        """
        self._output_path = Path(output_path or "output")
        self._output_path.mkdir(parents=True, exist_ok=True)
        self._formatters = Formatters()

    def generate_html(
        self,
        result: CoordinatorResult,
        filename: str | None = None,
    ) -> str:
        """生成 HTML 报告。

        Args:
            result: 编排器结果
            filename: 输出文件名

        Returns:
            生成的 HTML 文件路径
        """
        # 准备数据
        report_data = self._prepare_report_data(result)

        # 生成 HTML
        html_content = self._generate_html_content(report_data)

        # 保存文件
        if filename is None:
            target_safe = result.target.replace("/", "-").replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analysis_{target_safe}_{timestamp}.html"

        file_path = self._output_path / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return str(file_path)

    def _prepare_report_data(self, result: CoordinatorResult) -> dict[str, Any]:
        """准备报告数据。

        改进数据验证和容错处理：
        - 统一发现数据格式
        - 添加默认值
        - 实现数据降级策略

        Args:
            result: 编排器结果

        Returns:
            格式化的报告数据
        """
        # 收集各 Agent 的发现
        agent_discoveries = {}
        agent_stats = {}
        total_discovery_count = 0

        for agent_type, agent_results in result.agent_results.items():
            if agent_type == "elite":
                continue

            discoveries = []
            for agent_result in agent_results:
                # 统一发现格式：可能是字典或 Discovery 对象
                raw_discoveries = agent_result.discoveries
                if isinstance(raw_discoveries, list):
                    for item in raw_discoveries:
                        content = self._extract_content(item)
                        if content and len(content.strip()) >= 8:  # 过滤过短内容
                            discoveries.append({
                                "content": content,
                                "agent_type": agent_type,
                            })
                            total_discovery_count += 1

            agent_discoveries[agent_type] = discoveries
            agent_stats[agent_type] = {
                "count": len(discoveries),
                "name": self.AGENT_CONFIG.get(agent_type, {}).get("name", agent_type),
                "icon": self.AGENT_CONFIG.get(agent_type, {}).get("icon", "📋"),
                "color": self.AGENT_CONFIG.get(agent_type, {}).get("color", "#6b7280"),
            }

        # 提取精英 Agent 的报告数据（带容错）
        elite_results = result.agent_results.get("elite", [])
        insights = []
        recommendations = []
        summary = ""

        if elite_results:
            elite_result = elite_results[0]
            metadata = elite_result.metadata or {}

            # 尝试多个路径获取数据
            report_data = metadata.get("report", {})
            if not isinstance(report_data, dict):
                report_data = {}

            summary = report_data.get("summary", "") or metadata.get("summary", "")

            # 获取洞察（多路径兼容）
            insights = report_data.get("insights", []) or metadata.get("emergent_insights", [])
            # 标准化洞察格式
            insights = self._normalize_insights(insights)

            # 获取建议
            recommendations = report_data.get("recommendations", []) or metadata.get("strategic_recommendations", [])
            # 标准化建议格式
            recommendations = self._normalize_recommendations(recommendations)

        # 计算红蓝队观点（带容错）
        red_points = []
        blue_points = []

        if "red_team" in result.agent_results:
            for agent_result in result.agent_results["red_team"]:
                for discovery in agent_result.discoveries:
                    content = self._extract_content(discovery)
                    if content and len(content.strip()) >= 8:
                        red_points.append(content)

        if "blue_team" in result.agent_results:
            for agent_result in result.agent_results["blue_team"]:
                for discovery in agent_result.discoveries:
                    content = self._extract_content(discovery)
                    if content and len(content.strip()) >= 8:
                        blue_points.append(content)

        # 计算总发现数
        metadata_total = result.metadata.get("total_discoveries", 0)
        total_discoveries = max(metadata_total, total_discovery_count)

        return {
            "target": result.target or "未知目标",
            "success": result.success,
            "duration": result.duration or 0,
            "timestamp": datetime.now().isoformat(),
            "competitors": result.metadata.get("competitors", []),
            "total_discoveries": total_discoveries,
            "agent_discoveries": agent_discoveries,
            "agent_stats": agent_stats,
            "summary": summary or "暂无摘要",
            "insights": insights,
            "recommendations": recommendations,
            "red_points": red_points,
            "blue_points": blue_points,
        }

    def _normalize_insights(self, insights: list[Any]) -> list[dict[str, Any]]:
        """标准化洞察格式。

        Args:
            insights: 原始洞察列表

        Returns:
            标准化的洞察列表
        """
        normalized = []

        for item in insights:
            if not isinstance(item, dict):
                continue

            content = (
                item.get("content") or
                item.get("description") or
                item.get("text") or
                ""
            )

            if content:
                normalized.append({
                    "content": str(content)[:500],
                    "description": str(content)[:500],
                    "dimensions": item.get("dimensions", ["multiple"]),
                    "evidence": item.get("evidence", []),
                    "strategic_value": item.get("strategic_value") or item.get("priority") or "medium",
                })

        return normalized

    def _normalize_recommendations(self, recommendations: list[Any]) -> list[dict[str, Any]]:
        """标准化建议格式。

        Args:
            recommendations: 原始建议列表

        Returns:
            标准化的建议列表
        """
        normalized = []

        for item in recommendations:
            if not isinstance(item, dict):
                # 可能是字符串
                if isinstance(item, str) and len(item) >= 20:
                    normalized.append({
                        "description": item[:200],
                        "content": item[:200],
                        "priority": "medium",
                        "impact": "待评估",
                        "difficulty": "medium",
                    })
                continue

            description = (
                item.get("description") or
                item.get("content") or
                item.get("title") or
                ""
            )

            if description:
                normalized.append({
                    "description": str(description)[:200],
                    "content": str(description)[:200],
                    "title": item.get("title", ""),
                    "priority": item.get("priority", "medium"),
                    "impact": item.get("impact") or item.get("expected_effect", "待评估"),
                    "difficulty": item.get("difficulty", "medium"),
                })

        return normalized

    def _extract_content(self, discovery: Any) -> str:
        """从发现对象中提取内容。

        Args:
            discovery: 发现对象

        Returns:
            内容字符串
        """
        if isinstance(discovery, dict):
            return discovery.get("content") or discovery.get("evidence", "")
        elif hasattr(discovery, "content"):
            return discovery.content
        return str(discovery)

    def _generate_html_content(self, data: dict[str, Any]) -> str:
        """生成完整的 HTML 内容。

        Args:
            data: 报告数据

        Returns:
            HTML 内容字符串
        """
        # 注入数据到 JavaScript
        data_json = json.dumps(data, ensure_ascii=False, indent=2)

        # 读取模板并替换数据
        template = self._get_html_template()

        return template.replace("{{REPORT_DATA}}", data_json)

    def _get_html_template(self) -> str:
        """获取 HTML 模板。

        Returns:
            HTML 模板字符串
        """
        return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>竞品分析报告</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

        :root {
            --bg-primary: #ffffff;
            --bg-secondary: #f8fafc;
            --bg-card: #ffffff;
            --text-primary: #0f172a;
            --text-secondary: #475569;
            --border: #e2e8f0;
            --accent: #6366f1;
            --accent-hover: #4f46e5;
        }

        .dark {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #1e293b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --border: #334155;
            --accent: #818cf8;
            --accent-hover: #6366f1;
        }

        * {
            transition: background-color 0.3s ease, color 0.3s ease, border-color 0.3s ease;
        }

        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-secondary);
            color: var(--text-primary);
        }

        code, pre {
            font-family: 'JetBrains Mono', monospace;
        }

        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .insight-card {
            border-left: 4px solid var(--accent);
        }

        .insight-card.high {
            border-left-color: #ef4444;
        }

        .insight-card.medium {
            border-left-color: #f59e0b;
        }

        .insight-card.low {
            border-left-color: #22c55e;
        }

        .priority-high {
            color: #ef4444;
        }

        .priority-medium {
            color: #f59e0b;
        }

        .priority-low {
            color: #22c55e;
        }

        .difficulty-high {
            background-color: #fef2f2;
            color: #991b1b;
        }

        .difficulty-medium {
            background-color: #fef3c7;
            color: #92400e;
        }

        .difficulty-low {
            background-color: #f0fdf4;
            color: #166534;
        }

        .dark .difficulty-high {
            background-color: #7f1d1d;
            color: #fecaca;
        }

        .dark .difficulty-medium {
            background-color: #78350f;
            color: #fde68a;
        }

        .dark .difficulty-low {
            background-color: #14532d;
            color: #bbf7d0;
        }

        /* 动画 */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .animate-fade-in {
            animation: fadeIn 0.5s ease forwards;
        }

        .stagger-1 { animation-delay: 0.1s; }
        .stagger-2 { animation-delay: 0.2s; }
        .stagger-3 { animation-delay: 0.3s; }
        .stagger-4 { animation-delay: 0.4s; }
        .stagger-5 { animation-delay: 0.5s; }

        /* 侧边栏 */
        .sidebar {
            position: fixed;
            left: 0;
            top: 0;
            bottom: 0;
            width: 260px;
            padding: 1.5rem;
            background: var(--bg-card);
            border-right: 1px solid var(--border);
            overflow-y: auto;
            z-index: 50;
        }

        .main-content {
            margin-left: 260px;
            padding: 2rem;
            max-width: 1200px;
        }

        @media (max-width: 768px) {
            .sidebar {
                transform: translateX(-100%);
            }

            .main-content {
                margin-left: 0;
                padding: 1rem;
            }
        }

        /* 自定义滚动条 */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: var(--bg-secondary);
        }

        ::-webkit-scrollbar-thumb {
            background: var(--border);
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-secondary);
        }

        /* 折叠面板 */
        .collapse-content {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.3s ease;
        }

        .collapse-content.expanded {
            max-height: 2000px;
        }

        /* 搜索高亮 */
        .highlight {
            background-color: #fef08a;
            padding: 2px 4px;
            border-radius: 2px;
        }

        .dark .highlight {
            background-color: #854d0e;
            color: #fef9c3;
        }
    </style>
</head>
<body class="antialiased">
    <!-- 侧边导航栏 -->
    <nav class="sidebar hidden md:block">
        <div class="mb-8">
            <h1 class="text-xl font-bold" style="color: var(--accent);">CompetitorSwarm</h1>
            <p class="text-sm mt-1" style="color: var(--text-secondary);">竞品分析可视化报告</p>
        </div>

        <nav class="space-y-2">
            <a href="#overview" class="nav-link block px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition">
                📊 概览
            </a>
            <a href="#dimensions" class="nav-link block px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition">
                🎯 维度分析
            </a>
            <a href="#insights" class="nav-link block px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition">
                💡 综合洞察
            </a>
            <a href="#recommendations" class="nav-link block px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition">
                📋 可执行建议
            </a>
            <a href="#debate" class="nav-link block px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition">
                ⚔️ 红蓝队对抗
            </a>
            <a href="#discoveries" class="nav-link block px-3 py-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition">
                🔍 详细发现
            </a>
        </nav>

        <div class="absolute bottom-6 left-6 right-6">
            <button id="theme-toggle" class="w-full px-4 py-2 rounded-lg border flex items-center justify-center gap-2 hover:bg-gray-100 dark:hover:bg-gray-800 transition">
                <span id="theme-icon">🌙</span>
                <span id="theme-text">深色模式</span>
            </button>
        </div>
    </nav>

    <!-- 主内容区 -->
    <main class="main-content">
        <!-- 移动端导航 -->
        <div class="md:hidden mb-4">
            <button id="mobile-menu-btn" class="px-4 py-2 rounded-lg border">
                ☰ 导航
            </button>
        </div>

        <!-- 概览卡片 -->
        <section id="overview" class="mb-8">
            <h2 class="text-2xl font-bold mb-4">📊 分析概览</h2>

            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <div class="card p-4 animate-fade-in">
                    <p class="text-sm" style="color: var(--text-secondary);">分析目标</p>
                    <p class="text-2xl font-bold mt-1" id="target-display"></p>
                </div>
                <div class="card p-4 animate-fade-in stagger-1">
                    <p class="text-sm" style="color: var(--text-secondary);">分析耗时</p>
                    <p class="text-2xl font-bold mt-1" id="duration-display"></p>
                </div>
                <div class="card p-4 animate-fade-in stagger-2">
                    <p class="text-sm" style="color: var(--text-secondary);">发现总数</p>
                    <p class="text-2xl font-bold mt-1" id="discoveries-display"></p>
                </div>
                <div class="card p-4 animate-fade-in stagger-3">
                    <p class="text-sm" style="color: var(--text-secondary);">分析状态</p>
                    <p class="text-2xl font-bold mt-1 text-green-500">✓ 成功</p>
                </div>
            </div>

            <!-- 维度雷达图 -->
            <div class="card p-6 mb-6">
                <h3 class="text-lg font-semibold mb-4">维度覆盖</h3>
                <div class="h-64">
                    <canvas id="radar-chart"></canvas>
                </div>
            </div>
        </section>

        <!-- 执行摘要 -->
        <section id="summary" class="mb-8">
            <div class="card p-6">
                <h3 class="text-lg font-semibold mb-4">📝 执行摘要</h3>
                <div id="summary-content" class="prose dark:prose-invert max-w-none"></div>
            </div>
        </section>

        <!-- 维度分析 -->
        <section id="dimensions" class="mb-8">
            <h2 class="text-2xl font-bold mb-4">🎯 维度分析</h2>
            <div id="dimensions-grid" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
        </section>

        <!-- 综合洞察 -->
        <section id="insights" class="mb-8">
            <h2 class="text-2xl font-bold mb-4">💡 综合洞察</h2>
            <div id="insights-container" class="space-y-4"></div>
        </section>

        <!-- 可执行建议 -->
        <section id="recommendations" class="mb-8">
            <h2 class="text-2xl font-bold mb-4">📋 可执行建议</h2>
            <div id="recommendations-container" class="space-y-4"></div>
        </section>

        <!-- 红蓝队对抗 -->
        <section id="debate" class="mb-8">
            <h2 class="text-2xl font-bold mb-4">⚔️ 红蓝队对抗</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="card p-6" style="border-left: 4px solid #ef4444;">
                    <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
                        <span>⚔️</span>
                        <span>红队观点</span>
                    </h3>
                    <div id="red-points-container" class="space-y-3"></div>
                </div>
                <div class="card p-6" style="border-left: 4px solid #3b82f6;">
                    <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
                        <span>🛡️</span>
                        <span>蓝队观点</span>
                    </h3>
                    <div id="blue-points-container" class="space-y-3"></div>
                </div>
            </div>
        </section>

        <!-- 详细发现 -->
        <section id="discoveries" class="mb-8">
            <h2 class="text-2xl font-bold mb-4">🔍 详细发现</h2>

            <!-- 筛选器 -->
            <div class="card p-4 mb-4">
                <div class="flex flex-wrap gap-2">
                    <button class="filter-btn active px-3 py-1 rounded-full text-sm border" data-filter="all">
                        全部
                    </button>
                    <button class="filter-btn px-3 py-1 rounded-full text-sm border" data-filter="scout">
                        🔍 侦察
                    </button>
                    <button class="filter-btn px-3 py-1 rounded-full text-sm border" data-filter="experience">
                        🎨 体验
                    </button>
                    <button class="filter-btn px-3 py-1 rounded-full text-sm border" data-filter="technical">
                        🔬 技术
                    </button>
                    <button class="filter-btn px-3 py-1 rounded-full text-sm border" data-filter="market">
                        📊 市场
                    </button>
                    <input type="text" id="search-input" placeholder="搜索关键词..."
                           class="ml-auto px-3 py-1 rounded-full text-sm border w-40">
                </div>
            </div>

            <div id="discoveries-container" class="space-y-3"></div>
        </section>

        <!-- 页脚 -->
        <footer class="text-center py-8 text-sm" style="color: var(--text-secondary);">
            <p>由 CompetitorSwarm 竞品分析系统生成</p>
            <p id="timestamp-display"></p>
        </footer>
    </main>

    <script>
        // 注入报告数据
        window.REPORT_DATA = {{REPORT_DATA}};

        // 初始化应用
        document.addEventListener('DOMContentLoaded', function() {
            initTheme();
            renderOverview();
            renderDimensions();
            renderInsights();
            renderRecommendations();
            renderDebate();
            renderDiscoveries();
            initFilters();
            initSmoothScroll();
        });

        // 主题切换
        function initTheme() {
            const themeToggle = document.getElementById('theme-toggle');
            const themeIcon = document.getElementById('theme-icon');
            const themeText = document.getElementById('theme-text');
            const html = document.documentElement;

            // 检查保存的主题
            const savedTheme = localStorage.getItem('theme') || 'light';
            if (savedTheme === 'dark') {
                html.classList.add('dark');
                themeIcon.textContent = '☀️';
                themeText.textContent = '浅色模式';
            }

            themeToggle.addEventListener('click', () => {
                html.classList.toggle('dark');
                const isDark = html.classList.contains('dark');
                themeIcon.textContent = isDark ? '☀️' : '🌙';
                themeText.textContent = isDark ? '浅色模式' : '深色模式';
                localStorage.setItem('theme', isDark ? 'dark' : 'light');
            });
        }

        // 渲染概览
        function renderOverview() {
            const data = window.REPORT_DATA;

            document.getElementById('target-display').textContent = data.target;
            if (data.target) {
                document.title = `竞品分析报告 - ${data.target}`;
            }

            const duration = data.duration < 60
                ? `${data.duration.toFixed(1)} 秒`
                : `${(data.duration / 60).toFixed(1)} 分钟`;
            document.getElementById('duration-display').textContent = duration;

            document.getElementById('discoveries-display').textContent = data.total_discoveries;

            document.getElementById('timestamp-display').textContent =
                `生成时间: ${new Date(data.timestamp).toLocaleString('zh-CN')}`;

            // 渲染摘要
            if (data.summary) {
                document.getElementById('summary-content').innerHTML = formatMarkdown(data.summary);
            }

            // 渲染雷达图
            renderRadarChart();
        }

        // 渲染雷达图
        function renderRadarChart() {
            const data = window.REPORT_DATA;
            const canvas = document.getElementById('radar-chart');
            if (!canvas || typeof Chart === 'undefined') {
                return;
            }
            const ctx = canvas.getContext('2d');

            const labels = [];
            const values = [];
            const colors = [];

            for (const [agentType, stats] of Object.entries(data.agent_stats)) {
                labels.push(stats.icon + ' ' + stats.name);
                values.push(stats.count);
                colors.push(stats.color);
            }

            if (labels.length === 0) {
                return;
            }

            new Chart(ctx, {
                type: 'radar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: '发现数量',
                        data: values,
                        backgroundColor: 'rgba(99, 102, 241, 0.2)',
                        borderColor: 'rgba(99, 102, 241, 1)',
                        borderWidth: 2,
                        pointBackgroundColor: colors,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        r: {
                            beginAtZero: true,
                            ticks: {
                                stepSize: 5
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        }
                    }
                }
            });
        }

        // 渲染维度分析
        function renderDimensions() {
            const data = window.REPORT_DATA;
            const container = document.getElementById('dimensions-grid');
            container.innerHTML = '';

            for (const [agentType, stats] of Object.entries(data.agent_stats)) {
                const card = document.createElement('div');
                card.className = 'card p-4 cursor-pointer hover:shadow-lg transition';
                card.style.borderTop = `4px solid ${stats.color}`;
                card.dataset.agent = agentType;

                card.innerHTML = `
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-lg">${stats.icon} ${stats.name}</span>
                        <span class="text-2xl font-bold" style="color: ${stats.color}">${stats.count}</span>
                    </div>
                    <p class="text-sm" style="color: var(--text-secondary);">条发现</p>
                `;

                container.appendChild(card);
            }

            if (container.children.length === 0) {
                container.innerHTML = '<p class="text-sm" style="color: var(--text-secondary);">暂无维度数据</p>';
            }
        }

        // 渲染洞察
        function renderInsights() {
            const data = window.REPORT_DATA;
            const container = document.getElementById('insights-container');
            container.innerHTML = '';

            if (!data.insights || data.insights.length === 0) {
                container.innerHTML = '<p class="text-sm" style="color: var(--text-secondary);">暂无综合洞察</p>';
                return;
            }

            data.insights.forEach((insight, index) => {
                const card = document.createElement('div');
                const strategicValue = insight.strategic_value || insight.priority || 'medium';

                card.className = `card insight-card p-4 ${strategicValue}`;

                const content = insight.content || insight.description || '';
                const valueLabels = {
                    high: '高战略价值',
                    medium: '中等战略价值',
                    low: '低战略价值'
                };

                card.innerHTML = `
                    <div class="flex items-start justify-between">
                        <div class="flex-1">
                            <h4 class="font-semibold mb-2">洞察 ${index + 1}</h4>
                            <div class="prose dark:prose-invert max-w-none text-sm">
                                ${formatMarkdown(content)}
                            </div>
                        </div>
                        <span class="ml-4 px-2 py-1 rounded text-xs priority-${strategicValue}">
                            ${valueLabels[strategicValue] || '中等战略价值'}
                        </span>
                    </div>
                `;

                container.appendChild(card);
            });
        }

        // 渲染建议
        function renderRecommendations() {
            const data = window.REPORT_DATA;
            const container = document.getElementById('recommendations-container');
            container.innerHTML = '';

            if (!data.recommendations || data.recommendations.length === 0) {
                container.innerHTML = '<p class="text-sm" style="color: var(--text-secondary);">暂无具体建议</p>';
                return;
            }

            data.recommendations.forEach((rec, index) => {
                const card = document.createElement('div');
                const priority = rec.priority || 'medium';
                const difficulty = rec.difficulty || 'medium';

                card.className = 'card p-4';

                const title = rec.title || rec.category || `建议 ${index + 1}`;
                const description = rec.description || rec.content || '';

                const priorityLabels = {
                    high: '高优先级',
                    medium: '中优先级',
                    low: '低优先级'
                };

                const difficultyLabels = {
                    high: '难度：高',
                    medium: '难度：中',
                    low: '难度：低'
                };

                card.innerHTML = `
                    <div class="flex items-start justify-between mb-2">
                        <h4 class="font-semibold">${title}</h4>
                        <div class="flex gap-2">
                            <span class="px-2 py-1 rounded text-xs priority-${priority}">
                                ${priorityLabels[priority]}
                            </span>
                            <span class="px-2 py-1 rounded text-xs difficulty-${difficulty}">
                                ${difficultyLabels[difficulty]}
                            </span>
                        </div>
                    </div>
                    <p class="text-sm" style="color: var(--text-secondary);">${description}</p>
                `;

                container.appendChild(card);
            });
        }

        // 渲染红蓝队对抗
        function renderDebate() {
            const data = window.REPORT_DATA;

            const redContainer = document.getElementById('red-points-container');
            const blueContainer = document.getElementById('blue-points-container');

            if (data.red_points && data.red_points.length > 0) {
                data.red_points.slice(0, 10).forEach(point => {
                    const item = document.createElement('div');
                    item.className = 'flex items-start gap-2';
                    item.innerHTML = `
                        <span class="text-red-500 mt-1">•</span>
                        <p class="text-sm">${escapeHtml(point)}</p>
                    `;
                    redContainer.appendChild(item);
                });
            } else {
                redContainer.innerHTML = '<p class="text-sm" style="color: var(--text-secondary);">暂无红队分析</p>';
            }

            if (data.blue_points && data.blue_points.length > 0) {
                data.blue_points.slice(0, 10).forEach(point => {
                    const item = document.createElement('div');
                    item.className = 'flex items-start gap-2';
                    item.innerHTML = `
                        <span class="text-blue-500 mt-1">•</span>
                        <p class="text-sm">${escapeHtml(point)}</p>
                    `;
                    blueContainer.appendChild(item);
                });
            } else {
                blueContainer.innerHTML = '<p class="text-sm" style="color: var(--text-secondary);">暂无蓝队分析</p>';
            }
        }

        // 渲染详细发现
        function renderDiscoveries() {
            const data = window.REPORT_DATA;
            const container = document.getElementById('discoveries-container');
            container.innerHTML = '';

            const agentConfig = {
                scout: { icon: '🔍', name: '侦察', color: '#6366f1' },
                experience: { icon: '🎨', name: '体验', color: '#ec4899' },
                technical: { icon: '🔬', name: '技术', color: '#14b8a6' },
                market: { icon: '📊', name: '市场', color: '#f59e0b' },
                red_team: { icon: '⚔️', name: '红队', color: '#ef4444' },
                blue_team: { icon: '🛡️', name: '蓝队', color: '#3b82f6' },
            };

            for (const [agentType, discoveries] of Object.entries(data.agent_discoveries)) {
                const config = agentConfig[agentType] || { icon: '📋', name: agentType, color: '#6b7280' };

                discoveries.forEach((discovery, index) => {
                    const content = typeof discovery === 'string'
                        ? discovery
                        : (discovery.content || discovery.evidence || '');

                    if (!content) return;

                    const card = document.createElement('div');
                    card.className = 'discovery-card card p-3 collapse-trigger';
                    card.dataset.agent = agentType;
                    card.dataset.content = content.toLowerCase();

                    card.innerHTML = `
                        <div class="flex items-center gap-2 cursor-pointer" onclick="toggleCollapse(this)">
                            <span class="collapse-icon text-gray-400">▶</span>
                            <span class="text-sm" style="color: ${config.color};">${config.icon}</span>
                            <span class="text-xs px-2 py-0.5 rounded-full" style="background: ${config.color}20; color: ${config.color};">
                                ${config.name}
                            </span>
                            <span class="text-sm truncate flex-1">${escapeHtml(content.substring(0, 80))}${content.length > 80 ? '...' : ''}</span>
                        </div>
                        <div class="collapse-content mt-2">
                            <p class="text-sm whitespace-pre-wrap">${escapeHtml(content)}</p>
                        </div>
                    `;

                    container.appendChild(card);
                });
            }

            if (container.children.length === 0) {
                container.innerHTML = '<p class="text-sm text-center" style="color: var(--text-secondary);">暂无发现数据</p>';
            }
        }

        // 折叠切换
        function toggleCollapse(trigger) {
            const content = trigger.nextElementSibling;
            const icon = trigger.querySelector('.collapse-icon');

            content.classList.toggle('expanded');
            icon.textContent = content.classList.contains('expanded') ? '▼' : '▶';
        }

        // 初始化筛选器
        function initFilters() {
            const filterBtns = document.querySelectorAll('.filter-btn');
            const searchInput = document.getElementById('search-input');
            const discoveries = document.querySelectorAll('.discovery-card');

            filterBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    filterBtns.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    applyFilters();
                });
            });

            searchInput.addEventListener('input', applyFilters);

            function applyFilters() {
                const activeFilter = document.querySelector('.filter-btn.active').dataset.filter;
                const searchTerm = searchInput.value.toLowerCase();

                discoveries.forEach(card => {
                    const agent = card.dataset.agent;
                    const content = card.dataset.content;

                    const matchesFilter = activeFilter === 'all' || agent === activeFilter;
                    const matchesSearch = !searchTerm || content.includes(searchTerm);

                    card.style.display = matchesFilter && matchesSearch ? 'block' : 'none';
                });
            }
        }

        // 平滑滚动
        function initSmoothScroll() {
            document.querySelectorAll('a[href^="#"]').forEach(anchor => {
                anchor.addEventListener('click', function(e) {
                    e.preventDefault();
                    const target = document.querySelector(this.getAttribute('href'));
                    if (target) {
                        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                });
            });
        }

        // 格式化 Markdown
        function formatMarkdown(text) {
            if (!text) return '';
            return text
                .replace(/^### (.+)$/gm, '<h4>$1</h4>')
                .replace(/^## (.+)$/gm, '<h3>$1</h3>')
                .replace(/^# (.+)$/gm, '<h2>$1</h2>')
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                .replace(/\n/g, '<br>');
        }

        // HTML 转义
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    </script>
</body>
</html>'''

    def generate_json(self, result: CoordinatorResult, filename: str | None = None) -> str:
        """生成 JSON 格式报告数据。

        Args:
            result: 编排器结果
            filename: 输出文件名

        Returns:
            生成的 JSON 文件路径
        """
        report_data = self._prepare_report_data(result)

        if filename is None:
            target_safe = result.target.replace("/", "-").replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analysis_{target_safe}_{timestamp}.json"

        file_path = self._output_path / filename

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        return str(file_path)


# 全局实例
_generator: HTMLReportGenerator | None = None


def get_html_generator() -> HTMLReportGenerator:
    """获取 HTML 报告生成器实例。

    Returns:
        HTML 报告生成器
    """
    global _generator
    if _generator is None:
        _generator = HTMLReportGenerator()
    return _generator


def reset_html_generator() -> None:
    """重置 HTML 报告生成器。"""
    global _generator
    _generator = None
