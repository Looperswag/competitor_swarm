"""CLI 命令模块。

使用 Click 框架实现命令行接口。
"""

import sys
import threading

import click

from src.coordinator import Coordinator, reset_coordinator
from src.environment import get_environment, reset_environment
from src.reporter import get_reporter, reset_reporter
from src.llm import get_client, reset_client


class ProgressTracker:
    """进度跟踪器，用于在异步任务中更新进度。"""

    def __init__(self, total: int = 100, label: str = "分析进度") -> None:
        """初始化进度跟踪器。

        Args:
            total: 总进度值
            label: 进度条标签
        """
        self.total = total
        self.current = 0
        self.label = label
        self.lock = threading.Lock()
        self.current_agent: str | None = None

    def update(self, delta: int) -> None:
        """更新进度。

        Args:
            delta: 进度增量
        """
        with self.lock:
            self.current = min(self.total, self.current + delta)
            self._print_progress()

    def set(self, value: int) -> None:
        """设置进度值。

        Args:
            value: 新的进度值
        """
        with self.lock:
            self.current = min(self.total, max(0, value))
            self._print_progress()

    def set_agent(self, agent_name: str) -> None:
        """设置当前执行的 Agent。

        Args:
            agent_name: Agent 名称
        """
        with self.lock:
            self.current_agent = agent_name
            self._print_progress()

    def _print_progress(self) -> None:
        """打印进度信息。"""
        percent = int(self.current * 100 / self.total)
        filled = int(percent / 2)
        bar = "█" * filled + "-" * (50 - filled)

        agent_info = f" | {self.current_agent}" if self.current_agent else ""
        click.echo(f"\r{self.label} [{bar}] {percent:>3}%{agent_info}", err=True, nl=False)


@click.group()
@click.version_option(version="0.1.0")
def cli() -> None:
    """CompetitorSwarm - 竞品分析 Swarm 智能系统。

    使用多 Agent 协作进行深度竞品分析。
    """
    pass


@cli.command()
@click.argument("target")
@click.option("--competitor", "-c", multiple=True, help="竞品名称（可多次指定）")
@click.option("--focus", "-f", multiple=True, help="重点关注领域（可多次指定）")
@click.option("--output", "-o", type=click.Path(), help="输出文件路径")
@click.option("--format", "-F", type=click.Choice(["markdown", "html", "json", "all"]), default="markdown",
              help="报告格式")
@click.option("--save-cache", is_flag=True, help="保存分析缓存")
def analyze(
    target: str,
    competitor: tuple[str, ...],
    focus: tuple[str, ...],
    output: str | None,
    format: str,
    save_cache: bool,
) -> None:
    """执行竞品分析。

    TARGET: 要分析的产品或公司名称

    示例:

        \b
        # 基本分析
        python main.py analyze "Notion"

        \b
        # 对比分析
        python main.py analyze "Notion" -c "飞书文档" -c "Wolai"

        \b
        # 指定关注领域
        python main.py analyze "Notion" -f "协作功能" -f "定价"

        \b
        # 生成 HTML 可视化报告
        python main.py analyze "Notion" --format html

        \b
        # 生成所有格式
        python main.py analyze "Notion" --format all
    """
    # 验证 API Key
    try:
        client = get_client()
        click.echo("✓ API 连接成功", err=True)
    except Exception as e:
        click.echo(f"✗ API 连接失败: {e}", err=True)
        click.echo("\n请确保已设置 ZHIPUAI_API_KEY 环境变量", err=True)
        sys.exit(1)

    # 构建参数
    competitors = list(competitor) if competitor else None
    focus_areas = list(focus) if focus else None

    click.echo(f"\n🎯 分析目标: {target}", err=True)
    if competitors:
        click.echo(f"🔄 对比产品: {', '.join(competitors)}", err=True)
    if focus_areas:
        click.echo(f"🔍 关注领域: {', '.join(focus_areas)}", err=True)
    click.echo("", err=True)

    # 创建进度跟踪器
    progress = ProgressTracker(total=100, label="分析进度")

    # 创建带回调的编排器
    def on_phase_start(phase_name: str) -> None:
        """阶段开始回调。"""
        progress.set_agent(f"[{phase_name}]")

    def on_phase_complete(phase_name: str, delta: int) -> None:
        """阶段完成回调。"""
        progress.update(delta)

    def on_agent_start(agent_name: str) -> None:
        """Agent 开始回调。"""
        progress.set_agent(agent_name)

    # 创建新的编排器实例（带回调）
    reset_coordinator()
    coordinator = Coordinator(
        on_phase_start=on_phase_start,
        on_phase_complete=on_phase_complete,
        on_agent_start=on_agent_start,
    )

    # 执行分析
    result = coordinator.analyze(
        target=target,
        competitors=competitors,
        focus_areas=focus_areas,
    )

    # 完成进度
    progress.set(100)
    click.echo("", err=True)  # 换行

    # 处理结果
    if not result.success:
        click.echo(f"✗ 分析失败: {result.errors}", err=True)
        sys.exit(1)

    click.echo(f"✓ 分析完成 (耗时 {result.duration:.2f}s)", err=True)
    click.echo(f"📊 发现数量: {result.metadata.get('total_discoveries', 0)}", err=True)

    # 保存缓存
    if save_cache:
        environment = get_environment()
        cache_file = f"{target.replace(' ', '_')}_cache.json"
        environment.save(cache_file)
        click.echo(f"💾 缓存已保存: {cache_file}", err=True)

    # 生成报告
    reporter = get_reporter()
    generated_files = []

    if format in ["markdown", "all"]:
        md_path = reporter.save_report(result, filename=output)
        generated_files.append(("Markdown", md_path))

    if format in ["html", "all"]:
        html_path = reporter.save_html_report(result)
        generated_files.append(("HTML", html_path))

    if format in ["json", "all"]:
        json_path = reporter.save_json_report(result)
        generated_files.append(("JSON", json_path))

    # 输出生成的文件
    click.echo(f"\n📄 报告已生成:", err=True)
    for fmt, path in generated_files:
        click.echo(f"  - {fmt}: {path}", err=True)


@cli.group()
def cache() -> None:
    """缓存管理命令。"""
    pass


@cache.command()
def status() -> None:
    """查看缓存状态。"""
    environment = get_environment()

    click.echo("📦 缓存状态\n")

    click.echo(f"发现总数: {environment.discovery_count}")

    # 按类型统计
    from collections import Counter

    counter = Counter(d.agent_type for d in environment.all_discoveries)

    if counter:
        click.echo("\n按类型统计:")
        for agent_type, count in counter.most_common():
            click.echo(f"  - {agent_type}: {count}")

    # 热门发现
    hot = environment.get_hot_discoveries(limit=5)
    if hot:
        click.echo("\n热门发现:")
        for i, discovery in enumerate(hot, 1):
            preview = discovery.content[:50] + "..." if len(discovery.content) > 50 else discovery.content
            click.echo(f"  {i}. {preview}")


@cache.command()
@click.option("--force", is_flag=True, help="强制清除，不提示确认")
def clear(force: bool) -> None:
    """清除缓存。"""
    if not force:
        if not click.confirm("确定要清除所有缓存吗？"):
            click.echo("已取消")
            return

    environment = get_environment()
    environment.clear()

    click.echo("✓ 缓存已清除")


@cache.command()
@click.argument("filename")
def load(filename: str) -> None:
    """加载缓存文件。

    FILENAME: 缓存文件名（在 data/cache/ 目录下）
    """
    environment = get_environment()

    if environment.load(filename):
        click.echo(f"✓ 缓存已加载: {filename}")
        click.echo(f"  发现数量: {environment.discovery_count}")
    else:
        click.echo(f"✗ 加载失败: {filename}", err=True)
        sys.exit(1)


@cache.command()
@click.argument("filename")
def save(filename: str) -> None:
    """保存缓存到文件。

    FILENAME: 缓存文件名（将保存在 data/cache/ 目录下）
    """
    environment = get_environment()

    if environment.discovery_count == 0:
        click.echo("⚠ 当前没有缓存数据", err=True)
        return

    environment.save(filename)
    click.echo(f"✓ 缓存已保存: {filename}")
    click.echo(f"  发现数量: {environment.discovery_count}")


@cli.command()
@click.option("--clear", is_flag=True, help="清除所有状态后重置")
def reset(clear: bool) -> None:
    """重置系统状态。"""
    if clear:
        if not click.confirm("确定要重置所有状态吗？这将清除缓存和重置所有组件。"):
            click.echo("已取消")
            return

    reset_coordinator()
    reset_environment()
    reset_reporter()
    reset_client()

    click.echo("✓ 系统状态已重置")


@cli.command()
@click.option("--port", "-p", default=8000, help="端口号")
@click.option("--host", "-h", default="127.0.0.1", help="主机地址")
@click.option("--reload", is_flag=True, help="自动重载（开发模式）")
def serve(port: int, host: str, reload: bool) -> None:
    """启动 Web 服务器。

    提供可视化报告查看和实时分析功能。
    """
    try:
        import uvicorn
    except ImportError:
        click.echo("✗ 需要安装 uvicorn: pip install uvicorn[standard]", err=True)
        sys.exit(1)

    click.echo(f"🚀 启动 Web 服务器: http://{host}:{port}", err=True)
    click.echo("按 Ctrl+C 停止服务器", err=True)

    try:
        uvicorn.run(
            "src.web.app:app",
            host=host,
            port=port,
            reload=reload,
        )
    except KeyboardInterrupt:
        click.echo("\n\n👋 服务器已停止", err=True)


def main() -> None:
    """主入口函数。"""
    cli()


if __name__ == "__main__":
    main()
