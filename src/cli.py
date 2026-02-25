"""CLI 命令模块。

使用 Click 框架实现命令行接口。
"""

import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from src.coordinator import Coordinator, CoordinatorResult, reset_coordinator
from src.environment import get_environment, reset_environment
from src.reporter import get_reporter, reset_reporter
from src.llm import get_client, reset_client
from src.reporting.pm_markdown_converter import PMMarkdownConverter
from src.utils.config import get_config


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


PHASE_LABELS = {
    "collection": "信息收集",
    "validation": "交叉验证",
    "debate": "红蓝队对抗",
    "synthesis": "报告综合",
}
PHASE_ORDER = ["collection", "validation", "debate", "synthesis"]


@click.group()
@click.version_option(version="0.1.0")
def cli() -> None:
    """CompetitorSwarm - 竞品分析 Swarm 智能系统。

    使用多 Agent 协作进行深度竞品分析。
    """
    pass


def _ensure_writable_dir(dir_path: Path) -> None:
    """确保目录存在且可写。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    probe_file = dir_path / ".codex_write_probe"
    probe_file.write_text("ok", encoding="utf-8")
    probe_file.unlink(missing_ok=True)


@cli.command(name="check-env")
def check_env() -> None:
    """检查运行环境和关键依赖状态。"""
    has_error = False
    click.echo("🔎 环境检查")

    # 1) API Key
    api_key = os.getenv("ZHIPUAI_API_KEY", "").strip()
    if api_key:
        click.echo("✓ ZHIPUAI_API_KEY 已设置")
    else:
        click.echo("✗ ZHIPUAI_API_KEY 未设置")
        has_error = True

    # 2) 配置文件
    config = None
    try:
        config = get_config()
        click.echo("✓ 配置文件加载成功")
    except Exception as e:
        click.echo(f"✗ 配置文件加载失败: {e}")
        has_error = True

    # 3) 目录可写
    if config is not None:
        for label, raw_path in [
            ("缓存目录", config.cache.path),
            ("输出目录", config.output.path),
        ]:
            try:
                _ensure_writable_dir(Path(raw_path))
                click.echo(f"✓ {label}可写: {raw_path}")
            except Exception as e:
                click.echo(f"✗ {label}不可写: {raw_path} ({e})")
                has_error = True

    # 4) LLM 客户端初始化
    try:
        get_client()
        click.echo("✓ LLM 客户端初始化成功")
    except Exception as e:
        click.echo(f"✗ LLM 客户端初始化失败: {e}")
        has_error = True

    # 5) 搜索服务健康检查
    if config is not None:
        try:
            from src.search import get_search_tool

            search_tool = get_search_tool(
                provider=config.search.provider,
                api_key=config.search.api_key or None,
            )
            if search_tool.check_health():
                click.echo(f"✓ 搜索服务可用: {config.search.provider}")
            else:
                click.echo(f"✗ 搜索服务不可用: {config.search.provider}")
                has_error = True
        except Exception as e:
            click.echo(f"✗ 搜索服务检查失败: {e}")
            has_error = True

    if has_error:
        click.echo("\n✗ 环境检查失败，请先修复上述问题")
        raise click.exceptions.Exit(1)

    click.echo("\n✓ 环境检查通过")


def _print_timed_event(message: str, icon: str = "ℹ️") -> None:
    """输出带时间戳的事件日志。"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    click.echo(f"[{timestamp}] {icon} {message}", err=True)


def _humanize_phase_name(phase_name: str | None) -> str:
    """将阶段 key 统一映射为中文名称。"""
    if not phase_name:
        return "未知阶段"
    normalized = str(phase_name).strip()
    if not normalized:
        return "未知阶段"
    return PHASE_LABELS.get(normalized, normalized)


def _format_error_lines(errors: list[Any], run_id: str | None = None) -> list[str]:
    """格式化错误信息，输出可读的失败原因。"""
    if not errors:
        lines = ["失败原因（按阶段）:"]
        if run_id:
            lines.append(f"Run ID: {run_id}")
        lines.append("- 暂无可用错误详情。")
        return lines

    lines: list[str] = ["失败原因（按阶段）:"]
    if run_id:
        lines.append(f"Run ID: {run_id}")

    for idx, raw_error in enumerate(errors, 1):
        phase_name = "未知阶段"
        agent_name = "unknown"
        error_message = ""
        error_type = "UNKNOWN"
        hint = ""

        if isinstance(raw_error, dict):
            phase_name = _humanize_phase_name(raw_error.get("phase"))
            agent_name = str(raw_error.get("agent_type") or raw_error.get("agent") or "unknown")
            error_message = str(raw_error.get("error") or raw_error.get("message") or "").strip()
            error_type = str(raw_error.get("error_type") or "UNKNOWN").strip() or "UNKNOWN"
            hint = str(raw_error.get("hint") or "").strip()
            if not error_message:
                error_message = str(raw_error).strip()
        else:
            error_message = str(raw_error).strip()

        if not error_message:
            error_message = "unknown error"

        detail = f"{idx}. {phase_name} / {agent_name} [{error_type}]: {error_message}"
        if hint:
            detail += f" | hint={hint}"
        lines.append(detail)

    return lines


def _summarize_error_types(raw_errors: list[Any]) -> str:
    """汇总阶段内错误类型计数。"""
    counts: dict[str, int] = {}
    for raw_error in raw_errors:
        if isinstance(raw_error, dict):
            error_type = str(raw_error.get("error_type") or "").strip()
            if error_type:
                counts[error_type] = counts.get(error_type, 0) + 1

    if not counts:
        return ""

    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{error_type}×{count}" for error_type, count in ordered)


def _print_phase_summary(metadata: dict[str, Any]) -> None:
    """输出阶段级可观测摘要。"""
    phase_progress = metadata.get("phase_progress", {})
    if not isinstance(phase_progress, dict):
        return

    completed = phase_progress.get("completed_phases", [])
    phase_errors = phase_progress.get("phase_errors", {})
    if not isinstance(completed, list):
        completed = []
    if not isinstance(phase_errors, dict):
        phase_errors = {}

    if not completed and not phase_errors:
        return

    click.echo("\n📈 阶段执行总览", err=True)
    completed_set = {str(item) for item in completed}

    for phase_key in PHASE_ORDER:
        phase_label = PHASE_LABELS[phase_key]
        raw_errors = phase_errors.get(phase_key, [])
        if not isinstance(raw_errors, list):
            raw_errors = [raw_errors]
        error_count = len(raw_errors)
        error_type_summary = _summarize_error_types(raw_errors)

        if error_count > 0:
            if error_type_summary:
                status = f"异常({error_count}: {error_type_summary})"
            else:
                status = f"异常({error_count})"
        elif phase_key in completed_set:
            status = "完成"
        else:
            status = "未执行"

        click.echo(f"- {phase_label}: {status}", err=True)


def _print_agent_summary(metadata: dict[str, Any]) -> None:
    """输出 Agent 级可观测摘要。"""
    agent_status = metadata.get("agent_status", {})
    if not isinstance(agent_status, dict) or not agent_status:
        return

    total_agents = int(agent_status.get("total_agents", 0) or 0)
    failed_agents = agent_status.get("failed_agents", [])
    successful_agents = agent_status.get("successful_agents", [])
    empty_agents = agent_status.get("empty_agents", [])

    if not isinstance(failed_agents, list):
        failed_agents = []
    if not isinstance(successful_agents, list):
        successful_agents = []
    if not isinstance(empty_agents, list):
        empty_agents = []

    click.echo("\n🧩 Agent 执行总览", err=True)
    click.echo(f"- 总数: {total_agents}", err=True)
    click.echo(f"- 成功: {', '.join(successful_agents) if successful_agents else '无'}", err=True)
    click.echo(f"- 失败: {', '.join(failed_agents) if failed_agents else '无'}", err=True)
    click.echo(f"- 空结果: {', '.join(empty_agents) if empty_agents else '无'}", err=True)


def _print_emergence_explain(result: CoordinatorResult, run_id: str | None = None) -> None:
    """输出涌现洞察追溯明细。"""
    elite_results = result.agent_results.get("elite", [])
    if not elite_results:
        click.echo("\n🔬 Emergence Explain: 无 elite 结果可追溯。", err=True)
        return

    elite_result = elite_results[0]
    metadata = elite_result.metadata if isinstance(elite_result.metadata, dict) else {}
    report_data = metadata.get("report", {}) if isinstance(metadata, dict) else {}
    traces = report_data.get("insight_trace", []) if isinstance(report_data, dict) else []
    if not traces and isinstance(metadata, dict):
        traces = metadata.get("insight_trace", [])

    if not isinstance(traces, list) or not traces:
        click.echo("\n🔬 Emergence Explain: 无可追溯 insight_trace。", err=True)
        return

    click.echo("\n🔬 Emergence Explain", err=True)
    if run_id:
        click.echo(f"Run ID: {run_id}", err=True)

    for idx, trace in enumerate(traces, start=1):
        if not isinstance(trace, dict):
            continue
        motif_type = str(trace.get("motif_type") or "unknown")
        trace_id = str(trace.get("trace_id") or f"trace-{idx}")
        score = trace.get("score")
        score_text = f"{float(score):.4f}" if isinstance(score, (int, float)) else "N/A"
        signal_ids = trace.get("signal_ids", [])
        claim_ids = trace.get("claim_ids", [])
        phase_trace = trace.get("phase_trace", [])

        signal_text = ", ".join(str(item) for item in signal_ids) if isinstance(signal_ids, list) and signal_ids else "无"
        claim_text = ", ".join(str(item) for item in claim_ids) if isinstance(claim_ids, list) and claim_ids else "无"
        phase_text = " -> ".join(str(item) for item in phase_trace) if isinstance(phase_trace, list) and phase_trace else "无"

        click.echo(f"{idx}. [{motif_type}] {trace_id} (score={score_text})", err=True)
        click.echo(f"   signals: {signal_text}", err=True)
        click.echo(f"   claims: {claim_text}", err=True)
        click.echo(f"   phases: {phase_text}", err=True)


@cli.command()
@click.argument("target")
@click.option("--competitor", "-c", multiple=True, help="竞品名称（可多次指定）")
@click.option("--focus", "-f", multiple=True, help="重点关注领域（可多次指定）")
@click.option("--output", "-o", type=click.Path(), help="输出文件路径")
@click.option("--format", "-F", type=click.Choice(["markdown", "html", "json", "all"]), default="markdown",
              help="报告格式")
@click.option("--save-cache", is_flag=True, help="保存分析缓存")
@click.option("--phase-validation-min-confidence", type=float, default=None, help="Phase2 验证最低置信度")
@click.option("--phase-validation-min-strength", type=float, default=None, help="Phase2 验证最低强度")
@click.option("--phase-validation-min-weighted-score", type=float, default=None, help="Phase2 验证最低加权分")
@click.option("--phase-debate-rounds", type=int, default=None, help="Phase3 红蓝辩论轮数")
@click.option("--phase-debate-strength-step", type=float, default=None, help="Phase3 信号强度调整步长")
@click.option("--phase-debate-round-decay", type=float, default=None, help="Phase3 多轮辩论衰减系数")
@click.option("--phase-debate-max-adjustment", type=float, default=None, help="Phase3 单信号最大调整幅度")
@click.option(
    "--phase-debate-scope",
    type=click.Choice(["verified", "all"]),
    default=None,
    help="Phase3 作用范围：verified=仅已验证信号，all=全部信号",
)
@click.option("--explain-emergence", is_flag=True, help="输出涌现洞察的结构化追溯链（调试）")
def analyze(
    target: str,
    competitor: tuple[str, ...],
    focus: tuple[str, ...],
    output: str | None,
    format: str,
    save_cache: bool,
    phase_validation_min_confidence: float | None,
    phase_validation_min_strength: float | None,
    phase_validation_min_weighted_score: float | None,
    phase_debate_rounds: int | None,
    phase_debate_strength_step: float | None,
    phase_debate_round_decay: float | None,
    phase_debate_max_adjustment: float | None,
    phase_debate_scope: str | None,
    explain_emergence: bool,
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

    phase_executor_overrides: dict[str, float | int | bool] = {}
    if phase_validation_min_confidence is not None:
        phase_executor_overrides["min_confidence"] = phase_validation_min_confidence
    if phase_validation_min_strength is not None:
        phase_executor_overrides["min_strength"] = phase_validation_min_strength
    if phase_validation_min_weighted_score is not None:
        phase_executor_overrides["min_weighted_score"] = phase_validation_min_weighted_score
    if phase_debate_rounds is not None:
        phase_executor_overrides["debate_rounds"] = phase_debate_rounds
    if phase_debate_strength_step is not None:
        phase_executor_overrides["debate_strength_step"] = phase_debate_strength_step
    if phase_debate_round_decay is not None:
        phase_executor_overrides["debate_round_decay"] = phase_debate_round_decay
    if phase_debate_max_adjustment is not None:
        phase_executor_overrides["debate_max_adjustment"] = phase_debate_max_adjustment
    if phase_debate_scope is not None:
        phase_executor_overrides["debate_verified_only"] = phase_debate_scope == "verified"

    if phase_executor_overrides:
        overrides_display = ", ".join(
            f"{key}={value}"
            for key, value in phase_executor_overrides.items()
        )
        click.echo(f"🧭 阶段策略覆盖: {overrides_display}", err=True)
        click.echo("", err=True)

    # 创建进度跟踪器
    progress = ProgressTracker(total=100, label="分析进度")

    # 创建带回调的编排器
    def on_phase_start(phase_name: str) -> None:
        """阶段开始回调。"""
        click.echo("", err=True)
        _print_timed_event(f"阶段开始: {phase_name}", icon="🚀")
        progress.set_agent(f"[{phase_name}]")

    def on_phase_complete(phase_name: str, delta: int) -> None:
        """阶段完成回调。"""
        click.echo("", err=True)
        _print_timed_event(f"阶段完成: {phase_name}", icon="✅")
        progress.update(delta)

    def on_agent_start(agent_name: str) -> None:
        """Agent 开始回调。"""
        click.echo("", err=True)
        _print_timed_event(f"Agent 启动: {agent_name}", icon="🔍")
        progress.set_agent(agent_name)

    # 创建新的编排器实例（带回调）
    reset_coordinator()
    coordinator = Coordinator(
        phase_executor_overrides=phase_executor_overrides or None,
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

    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    _print_phase_summary(metadata)
    _print_agent_summary(metadata)

    # 处理结果
    if not result.success:
        click.echo("✗ 分析失败", err=True)
        run_id = str(metadata.get("run_id") or "").strip() or None
        for line in _format_error_lines(result.errors, run_id=run_id):
            click.echo(line, err=True)
        sys.exit(1)

    click.echo(f"✓ 分析完成 (耗时 {result.duration:.2f}s)", err=True)
    click.echo(f"📊 发现数量: {metadata.get('total_discoveries', 0)}", err=True)

    if result.errors:
        click.echo("\n⚠ 本次分析存在部分异常", err=True)
        run_id = str(metadata.get("run_id") or "").strip() or None
        for line in _format_error_lines(result.errors, run_id=run_id):
            click.echo(line, err=True)

    if explain_emergence:
        run_id = str(metadata.get("run_id") or "").strip() or None
        _print_emergence_explain(result, run_id=run_id)

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


@cli.command(name="convert-report")
@click.option(
    "--input",
    "input_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="输入 JSON 报告文件路径",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="输出 Markdown 路径（默认在输入文件同目录生成 *_readable.md）",
)
@click.option("--delete-json", is_flag=True, help="转换完成后删除输入 JSON 文件")
@click.option(
    "--readable/--no-readable",
    default=True,
    show_default=True,
    help="是否生成 PM 可读版 Markdown",
)
def convert_report(
    input_path: Path,
    output_path: Path | None,
    delete_json: bool,
    readable: bool,
) -> None:
    """将 JSON 报告转换为 PM 可直接阅读的 Markdown 报告。"""
    converter = PMMarkdownConverter()
    markdown_path = converter.convert_file(
        input_path=input_path,
        output_path=output_path,
        readable=readable,
    )

    click.echo(f"✓ Markdown 报告已生成: {markdown_path}", err=True)
    click.echo(
        "  - 过滤宣传性荣誉信息: "
        f"{converter.stats.filtered_promotional_items} 条",
        err=True,
    )

    if delete_json:
        input_path.unlink(missing_ok=True)
        click.echo(f"✓ 已删除 JSON 文件: {input_path}", err=True)


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
