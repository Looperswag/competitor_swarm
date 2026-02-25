"""报告生成器模块。

负责生成结构化的 Markdown 报告。
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

from src.coordinator import CoordinatorResult
from src.utils.config import get_config
from src.reporting import CitationManager, SectionGenerator, Formatters, get_html_generator

if TYPE_CHECKING:
    from src.scheduler import DiffReport


@dataclass
class ReportSection:
    """报告章节。"""

    title: str
    content: str
    level: int = 2  # Markdown 标题级别


class Reporter:
    """报告生成器。

    将分析结果转换为 Markdown 报告。
    """

    def __init__(self, output_path: str | None = None) -> None:
        """初始化报告生成器。

        Args:
            output_path: 输出目录路径
        """
        config = get_config()
        self._output_path = Path(output_path or config.output.path)
        self._output_path.mkdir(parents=True, exist_ok=True)
        self._history_dir = self._output_path / ".history"
        self._history_dir.mkdir(parents=True, exist_ok=True)

        # 初始化辅助模块
        self._citation_manager = CitationManager()
        self._section_generator = SectionGenerator(self._citation_manager)
        self._formatters = Formatters()

    def generate_markdown(self, result: CoordinatorResult) -> str:
        """生成 Markdown 报告。

        章节顺序（v3.0 调整）：
        1. 元信息
        2. 执行摘要（前置，3分钟速读）
        3. 竞品定位画像（新增）
        4. 核心维度对比表（新增）
        5. SWOT分析（新增）
        6. 阶段策略摘要
        7. 各维度分析详情
        8. 红蓝对抗涌现结论（表格化）
        9. 战略定位矩阵
        10. 风险/机会矩阵
        11. 可执行建议
        12. 附录

        Args:
            result: 编排器结果

        Returns:
            Markdown 报告内容
        """
        sections: list[ReportSection] = []

        # 1. 标题和元信息
        sections.append(ReportSection("竞品分析报告", self._generate_title(result), level=1))
        sections.append(ReportSection("元信息", self._generate_metadata(result)))

        # 2. 执行摘要（前置，使用新的章节生成器）
        summary_section = self._section_generator.generate_executive_summary(result, result.target)
        sections.append(summary_section)

        # 3. 竞品定位画像（新增）
        sections.append(ReportSection("竞品定位画像", self._generate_positioning_section(result)))

        # 4. 核心维度对比表（新增）
        sections.append(ReportSection("核心维度对比表", self._generate_dimension_comparison_table(result)))

        # 5. SWOT分析（新增）
        sections.append(ReportSection("SWOT分析", self._generate_swot_section(result)))

        # 6. 阶段策略摘要
        sections.append(ReportSection("阶段策略摘要", self._generate_phase_strategy_section(result)))

        # 7. 各维度分析详情
        sections.extend(self._generate_dimension_sections(result))

        # 8. 红蓝对抗涌现结论（表格化）
        sections.append(ReportSection("红蓝对抗涌现结论", self._generate_debate_section(result)))

        # 9. 战略定位矩阵
        strategic_matrix_section = self._section_generator.generate_strategic_positioning_matrix(result)
        sections.append(strategic_matrix_section)

        # 10. 风险/机会矩阵
        risk_matrix_section = self._section_generator.generate_risk_opportunity_matrix(result)
        sections.append(risk_matrix_section)

        # 11. 可执行建议
        recommendations_section = self._section_generator.generate_recommendations_section(result)
        sections.append(recommendations_section)

        # 历史对比（移到附录区域）
        current_snapshot = self._safe_history_snapshot(result)
        current_run_id = str(current_snapshot.get("run_id") or "")
        previous_snapshot = self._load_previous_snapshot(
            target=result.target,
            current_run_id=current_run_id,
        )
        sections.append(
            self._section_generator.generate_history_diff_section(
                current_snapshot=current_snapshot,
                previous_snapshot=previous_snapshot,
            )
        )

        # 快速阅读（移到附录区域）
        sections.append(self._section_generator.generate_quick_read_section(result))

        # 12. 附录
        config = get_config()
        if hasattr(config.output, "include_appendix") and config.output.include_appendix:
            appendix_sections = self._section_generator.generate_appendix(result)
            sections.extend(appendix_sections)

        # 组装报告
        return self._assemble_markdown(sections)

    def save_report(self, result: CoordinatorResult, filename: str | None = None) -> str:
        """保存报告到文件。

        Args:
            result: 编排器结果
            filename: 文件名，默认基于目标名称生成

        Returns:
            保存的文件路径
        """
        if filename is None:
            target_safe = self._slugify_target(result.target)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analysis_{target_safe}_{timestamp}.md"

        report_content = self.generate_markdown(result)
        report_path = self._output_path / filename

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        self._persist_history_snapshot(result)
        return str(report_path)

    def save_html_report(self, result: CoordinatorResult, filename: str | None = None) -> str:
        """保存 HTML 可视化报告。

        Args:
            result: 编排器结果
            filename: 文件名，默认基于目标名称生成

        Returns:
            保存的 HTML 文件路径
        """
        html_generator = get_html_generator()
        saved_path = html_generator.generate_html(result, filename)
        self._persist_history_snapshot(result)
        return saved_path

    def save_json_report(self, result: CoordinatorResult, filename: str | None = None) -> str:
        """保存 JSON 格式报告数据。

        Args:
            result: 编排器结果
            filename: 文件名，默认基于目标名称生成

        Returns:
            保存的 JSON 文件路径
        """
        html_generator = get_html_generator()
        saved_path = html_generator.generate_json(result, filename)
        self._persist_history_snapshot(result)
        return saved_path

    def _generate_title(self, result: CoordinatorResult) -> str:
        """生成标题部分。

        Args:
            result: 编排器结果

        Returns:
            标题内容
        """
        target = result.target
        competitors = result.metadata.get("competitors", [])

        if competitors:
            return f"# {target} vs {', '.join(competitors[:3])}"
        return f"# {target} 竞品分析"

    def _generate_metadata(self, result: CoordinatorResult) -> str:
        """生成元信息。

        Args:
            result: 编排器结果

        Returns:
            元信息内容
        """
        lines = [
            f"- **分析目标**: {result.target}",
            f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **分析耗时**: {result.duration:.2f} 秒",
            f"- **状态**: {'✓ 成功' if result.success else '✗ 失败'}",
        ]

        if result.metadata.get("competitors"):
            lines.append(f"- **对比产品**: {', '.join(result.metadata['competitors'])}")

        if result.metadata.get("total_discoveries"):
            lines.append(f"- **发现数量**: {result.metadata['total_discoveries']} 条")

        return "\n".join(lines)

    def _generate_phase_strategy_section(self, result: CoordinatorResult) -> str:
        """生成四阶段策略执行摘要。"""
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        phase_progress = metadata.get("phase_progress", {})
        if not isinstance(phase_progress, dict):
            return "暂无阶段策略数据。"

        phase_metadata = phase_progress.get("phase_metadata", {})
        if not isinstance(phase_metadata, dict):
            return "暂无阶段策略数据。"

        validation_data = phase_metadata.get("validation", {})
        debate_data = phase_metadata.get("debate", {})

        content_lines: list[str] = []

        if isinstance(validation_data, dict) and validation_data:
            strategy = validation_data.get("strategy", {})
            content_lines.extend([
                "### Phase 2 交叉验证",
                f"- 验证通过: {validation_data.get('verified_count', 0)} 条",
                f"- 过滤淘汰: {validation_data.get('filtered_count', 0)} 条",
            ])
            if isinstance(strategy, dict) and strategy:
                content_lines.extend([
                    f"- 阈值配置: confidence ≥ {strategy.get('min_confidence', 'N/A')}, "
                    f"strength ≥ {strategy.get('min_strength', 'N/A')}, "
                    f"weighted_score ≥ {strategy.get('min_weighted_score', 'N/A')}",
                    f"- 维度上限: {strategy.get('max_signals_per_dimension', 'N/A')} 条/维度",
                ])

            dimension_summary = validation_data.get("dimension_summary", {})
            if isinstance(dimension_summary, dict) and dimension_summary:
                content_lines.append("- 维度明细:")
                for dimension in sorted(dimension_summary.keys()):
                    detail = dimension_summary.get(dimension, {})
                    if not isinstance(detail, dict):
                        continue
                    content_lines.append(
                        f"  - {dimension}: 候选 {detail.get('candidate_count', 0)} / "
                        f"通过 {detail.get('verified_count', 0)} / "
                        f"过滤 {detail.get('filtered_count', 0)}"
                    )

            content_lines.append("")

        if isinstance(debate_data, dict) and debate_data:
            strategy = debate_data.get("strategy", {})
            adjustment = debate_data.get("signal_adjustment", {})
            content_lines.extend([
                "### Phase 3 红蓝辩论",
                f"- 辩论轮数: {debate_data.get('debate_rounds', 0)}",
                f"- 红队观点数: {debate_data.get('red_points', 0)}",
                f"- 蓝队观点数: {debate_data.get('blue_points', 0)}",
            ])
            if isinstance(strategy, dict) and strategy:
                content_lines.extend([
                    f"- 调整策略: step={strategy.get('strength_step', 'N/A')}, "
                    f"decay={strategy.get('round_decay', 'N/A')}, "
                    f"max_adjustment={strategy.get('max_adjustment', 'N/A')}, "
                    f"verified_only={strategy.get('verified_only', 'N/A')}",
                ])
            if isinstance(adjustment, dict) and adjustment:
                content_lines.extend([
                    f"- 信号调整: {adjustment.get('adjusted_signals', 0)} 条, "
                    f"总变动 {adjustment.get('total_delta', 0.0)}",
                ])

        if not content_lines:
            return "暂无阶段策略数据。"

        return "\n".join(content_lines).rstrip()

    def _generate_summary(self, result: CoordinatorResult) -> str:
        """生成执行摘要。

        Args:
            result: 编排器结果

        Returns:
            摘要内容
        """
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            return "暂无综合分析结果。"

        elite_result = elite_results[0]
        report_data = elite_result.metadata.get("report", {})

        summary = report_data.get("summary", "暂无摘要。")

        return f"""{summary}

---

**分析维度覆盖**:
{self._format_coverage_summary(result)}
"""

    def _format_coverage_summary(self, result: CoordinatorResult) -> str:
        """格式化覆盖摘要。

        Args:
            result: 编排器结果

        Returns:
            覆盖摘要
        """
        agent_names = {
            "scout": "🔍 侦察",
            "experience": "🎨 体验",
            "technical": "🔬 技术",
            "market": "📊 市场",
            "red_team": "⚔️ 红队",
            "blue_team": "🛡️ 蓝队",
            "elite": "👑 综合",
        }

        lines = []
        for agent_type in result.agent_results:
            name = agent_names.get(agent_type, agent_type)
            count = len(result.agent_results[agent_type])
            lines.append(f"- {name}: {count} 个结果")

        return "\n".join(lines) if lines else "- 无分析结果"

    def _generate_dimension_sections(self, result: CoordinatorResult) -> list[ReportSection]:
        """生成各维度分析章节。

        Args:
            result: 编排器结果

        Returns:
            章节列表
        """
        sections = []
        dimension_names = {
            "scout": "侦察分析",
            "experience": "体验分析",
            "technical": "技术分析",
            "market": "市场分析",
        }

        for agent_type, name in dimension_names.items():
            if agent_type in result.agent_results:
                content = self._format_dimension_results(result.agent_results[agent_type])
                sections.append(ReportSection(name, content))

        return sections

    def _format_dimension_results(self, results: list[Any]) -> str:
        """格式化维度结果。

        Args:
            results: 结果列表

        Returns:
            格式化的内容
        """
        if not results:
            return "暂无结果。"

        all_discoveries = []
        error_messages = []

        for result in results:
            discoveries = result.discoveries if hasattr(result, "discoveries") else []
            metadata = result.metadata if hasattr(result, "metadata") else {}
            if isinstance(metadata, dict) and metadata.get("error"):
                error_messages.append(str(metadata.get("error")))
            for discovery in discoveries:
                # 处理字典格式
                if isinstance(discovery, dict):
                    # 支持 content 和 evidence 字段
                    content = discovery.get("content") or discovery.get("evidence", "")
                    metadata = discovery.get("metadata", {})

                    # 添加来源信息（如果有）
                    source_info = ""
                    if metadata.get("source"):
                        source_info = f" - {metadata['source']}"
                    elif metadata.get("url"):
                        source_info = f" - [来源]({metadata['url']})"
                    elif discovery.get("source"):
                        source_info = f" - {discovery['source']}"

                    # 跳过空内容
                    if content.strip():
                        all_discoveries.append(f"- {content}{source_info}")

                # 处理 Discovery 对象（dataclass）
                elif hasattr(discovery, "content"):
                    content = discovery.content
                    if content and content.strip():
                        all_discoveries.append(f"- {content}")

                # 处理其他类型（转为字符串）
                else:
                    content = str(discovery).strip()
                    if content and content not in ["Discovery()", ""]:
                        all_discoveries.append(f"- {content}")

        # 显示数量上限为 120 条，避免大量输出被截断
        max_discoveries = 120
        formatted = "\n".join(all_discoveries[:max_discoveries])

        # 如果有更多结果，添加提示
        if len(all_discoveries) > max_discoveries:
            formatted += f"\n\n*... 还有 {len(all_discoveries) - max_discoveries} 条发现（已省略）*"

        header = f"共 {len(all_discoveries)} 条发现"

        if formatted.strip():
            if error_messages:
                error_line = f"\n\n> ⚠️ 部分任务失败：{'; '.join(error_messages[:3])}"
                return "\n".join([header, "", formatted]) + error_line
            return "\n".join([header, "", formatted])

        if error_messages:
            return "\n".join([header, "", f"⚠️ 任务失败：{'; '.join(error_messages[:3])}"])

        return header if header else "暂无有效发现。"

    def _generate_debate_section(self, result: CoordinatorResult) -> str:
        """生成红蓝队对抗章节（表格化 v3.0）。

        Args:
            result: 编排器结果

        Returns:
            对抗内容
        """
        red_results = result.agent_results.get("red_team", [])
        blue_results = result.agent_results.get("blue_team", [])

        red_points = self._extract_debate_points(red_results) if red_results else []
        blue_points = self._extract_debate_points(blue_results) if blue_results else []

        # 尝试生成表格化的涌现结论
        if red_points or blue_points:
            content = self._generate_debate_table(red_points, blue_points)
        else:
            content = "暂无红蓝对抗分析。"

        return content

    def _generate_debate_table(self, red_points: list[str], blue_points: list[str]) -> str:
        """生成红蓝对抗涌现结论表格。

        Args:
            red_points: 红队观点列表
            blue_points: 蓝队观点列表

        Returns:
            表格化的对抗内容
        """
        lines = ["| 争议点 | 红队批判 | 蓝队辩护 | 涌现结论 | 置信度 |", "|-------|---------|---------|---------|--------|"]

        # 配对红蓝观点
        max_len = max(len(red_points), len(blue_points))
        if max_len == 0:
            return "暂无红蓝对抗分析。"

        for i in range(min(max_len, 10)):  # 最多显示10条
            red = red_points[i] if i < len(red_points) else "-"
            blue = blue_points[i] if i < len(blue_points) else "-"

            # 截断过长的内容
            red_short = red[:50] + "..." if len(red) > 50 else red
            blue_short = blue[:50] + "..." if len(blue) > 50 else blue

            # 简单的涌现结论生成
            if red != "-" and blue != "-":
                conclusion = "需辩证看待，结合具体场景评估"
                confidence = "中"
            elif red != "-":
                conclusion = "需关注风险点"
                confidence = "中"
            else:
                conclusion = "可参考优势"
                confidence = "中"

            lines.append(f"| 争议{i+1} | {red_short} | {blue_short} | {conclusion} | {confidence} |")

        # 添加详细观点
        content = "\n".join(lines)

        # 添加详细的红队观点
        if red_points:
            content += "\n\n### ⚔️ 红队观点详情（批判）\n\n"
            limit = 8
            content += "\n".join([f"- {p}" for p in red_points[:limit]])
            if len(red_points) > limit:
                content += f"\n\n*... 还有 {len(red_points) - limit} 条红队观点*"

        # 添加详细的蓝队观点
        if blue_points:
            content += "\n\n### 🛡️ 蓝队观点详情（辩护）\n\n"
            limit = 8
            content += "\n".join([f"- {p}" for p in blue_points[:limit]])
            if len(blue_points) > limit:
                content += f"\n\n*... 还有 {len(blue_points) - limit} 条蓝队观点*"

        return content

    def _generate_positioning_section(self, result: CoordinatorResult) -> str:
        """生成竞品定位画像章节（v3.0 新增）。

        Args:
            result: 编排器结果

        Returns:
            定位画像内容
        """
        target = result.target
        elite_results = result.agent_results.get("elite", [])
        scout_results = result.agent_results.get("scout", [])
        market_results = result.agent_results.get("market", [])

        # 尝试从 Elite 结果中提取定位信息
        positioning = {
            "core_positioning": f"{target} 是一款[待补充核心定位]",
            "target_users": "目标用户群体待分析",
            "value_proposition": "核心价值主张待提炼",
        }

        if elite_results:
            elite_metadata = elite_results[0].metadata if hasattr(elite_results[0], "metadata") else {}
            if isinstance(elite_metadata, dict):
                positioning.update(elite_metadata.get("positioning", {}))

        # 从 Scout 和 Market 结果中补充信息
        discovery_hints = []
        for agent_results in [scout_results, market_results]:
            for agent_result in agent_results:
                discoveries = agent_result.discoveries if hasattr(agent_result, "discoveries") else []
                for discovery in discoveries[:3]:
                    if isinstance(discovery, dict):
                        content = discovery.get("content", "")
                        if content:
                            discovery_hints.append(content[:100])

        lines = [
            f"**核心定位**：{positioning.get('core_positioning', f'{target} 是一款[待补充]')}",
            f"**目标用户**：{positioning.get('target_users', '目标用户群体待分析')}",
            f"**价值主张**：{positioning.get('value_proposition', '核心价值主张待提炼')}",
        ]

        if discovery_hints:
            lines.append("\n**关键发现支撑**：")
            for hint in discovery_hints[:3]:
                lines.append(f"- {hint}...")

        return "\n".join(lines)

    def _generate_dimension_comparison_table(self, result: CoordinatorResult) -> str:
        """生成核心维度对比表（v3.0 新增）。

        Args:
            result: 编排器结果

        Returns:
            维度对比表内容
        """
        dimensions = {
            "产品功能": {"score": "-", "gap": "待评估", "implication": "-", "source": "-"},
            "用户体验": {"score": "-", "gap": "待评估", "implication": "-", "source": "-"},
            "技术能力": {"score": "-", "gap": "待评估", "implication": "-", "source": "-"},
            "市场份额": {"score": "-", "gap": "待评估", "implication": "-", "source": "-"},
            "商业化": {"score": "-", "gap": "待评估", "implication": "-", "source": "-"},
        }

        # 从各 Agent 结果中提取维度评分
        agent_dimension_map = {
            "scout": "产品功能",
            "experience": "用户体验",
            "technical": "技术能力",
            "market": "市场份额",
        }

        for agent_type, dimension in agent_dimension_map.items():
            agent_results = result.agent_results.get(agent_type, [])
            if agent_results:
                # 简单评分：基于发现数量
                total_discoveries = sum(
                    len(r.discoveries) if hasattr(r, "discoveries") else 0
                    for r in agent_results
                )
                if total_discoveries > 10:
                    score = "强"
                    gap = "落后"
                elif total_discoveries > 5:
                    score = "中"
                    gap = "持平"
                else:
                    score = "弱"
                    gap = "领先"

                dimensions[dimension]["score"] = f"{score}（{total_discoveries}条发现）"
                dimensions[dimension]["gap"] = gap
                dimensions[dimension]["implication"] = "需结合具体发现分析"
                dimensions[dimension]["source"] = f"[{agent_type}]"

        # 生成表格
        lines = [
            "| 维度 | 竞品表现 | 我方差距 | 战略含义 | 数据支撑 |",
            "|------|---------|---------|---------|---------|",
        ]

        for dimension, data in dimensions.items():
            lines.append(
                f"| {dimension} | {data['score']} | {data['gap']} | {data['implication']} | {data['source']} |"
            )

        return "\n".join(lines)

    def _generate_swot_section(self, result: CoordinatorResult) -> str:
        """生成 SWOT 分析章节（v3.0 新增，结构化表格）。

        Args:
            result: 编排器结果

        Returns:
            SWOT 分析内容
        """
        blue_results = result.agent_results.get("blue_team", [])
        red_results = result.agent_results.get("red_team", [])
        market_results = result.agent_results.get("market", [])

        # 提取优势（从蓝队）
        strengths = []
        for agent_result in blue_results:
            discoveries = agent_result.discoveries if hasattr(agent_result, "discoveries") else []
            for discovery in discoveries[:5]:
                if isinstance(discovery, dict):
                    content = discovery.get("content", "")
                    if content:
                        strengths.append({
                            "item": content[:60] + "..." if len(content) > 60 else content,
                            "evidence": discovery.get("metadata", {}).get("source", "蓝队分析"),
                            "sustainability": "中",
                            "source": "blue_team",
                        })

        # 提取劣势（从红队）
        weaknesses = []
        for agent_result in red_results:
            discoveries = agent_result.discoveries if hasattr(agent_result, "discoveries") else []
            for discovery in discoveries[:5]:
                if isinstance(discovery, dict):
                    content = discovery.get("content", "")
                    if content:
                        weaknesses.append({
                            "item": content[:60] + "..." if len(content) > 60 else content,
                            "impact": "中",
                            "urgency": "中",
                            "source": "red_team",
                        })

        # 提取机会和威胁（从市场）
        opportunities = []
        threats = []
        for agent_result in market_results:
            discoveries = agent_result.discoveries if hasattr(agent_result, "discoveries") else []
            for discovery in discoveries[:5]:
                if isinstance(discovery, dict):
                    content = discovery.get("content", "")
                    if content:
                        # 简单分类：包含"机会"或"增长"的归为机会，包含"威胁"或"风险"的归为威胁
                        if any(kw in content for kw in ["机会", "增长", "潜力", "蓝海"]):
                            opportunities.append({
                                "item": content[:60] + "..." if len(content) > 60 else content,
                                "market_size": "待估算",
                                "match": "中",
                                "difficulty": "中",
                            })
                        elif any(kw in content for kw in ["威胁", "风险", "竞争", "挑战"]):
                            threats.append({
                                "item": content[:60] + "..." if len(content) > 60 else content,
                                "probability": "中",
                                "impact": "中",
                                "strategy": "待制定",
                            })

        # 生成 SWOT 表格
        lines = []

        # 优势表格
        lines.append("### 优势 (Strengths)")
        if strengths:
            lines.extend([
                "| 优势项 | 量化证据 | 可持续性 | 来源于 |",
                "|-------|---------|---------|--------|",
            ])
            for s in strengths[:4]:
                lines.append(f"| {s['item']} | {s['evidence']} | {s['sustainability']} | {s['source']} |")
        else:
            lines.append("暂无优势分析数据。")

        # 劣势表格
        lines.append("\n### 劣势 (Weaknesses)")
        if weaknesses:
            lines.extend([
                "| 劣势项 | 影响程度 | 紧迫性 | 来源于 |",
                "|-------|---------|--------|--------|",
            ])
            for w in weaknesses[:4]:
                lines.append(f"| {w['item']} | {w['impact']} | {w['urgency']} | {w['source']} |")
        else:
            lines.append("暂无劣势分析数据。")

        # 机会表格
        lines.append("\n### 机会 (Opportunities)")
        if opportunities:
            lines.extend([
                "| 机会项 | 市场规模(估) | 我方匹配度 | 捕获难度 |",
                "|-------|-------------|-----------|---------|",
            ])
            for o in opportunities[:4]:
                lines.append(f"| {o['item']} | {o['market_size']} | {o['match']} | {o['difficulty']} |")
        else:
            lines.append("暂无机会分析数据。")

        # 威胁表格
        lines.append("\n### 威胁 (Threats)")
        if threats:
            lines.extend([
                "| 威胁项 | 发生概率 | 影响程度 | 应对策略概要 |",
                "|-------|---------|---------|-------------|",
            ])
            for t in threats[:4]:
                lines.append(f"| {t['item']} | {t['probability']} | {t['impact']} | {t['strategy']} |")
        else:
            lines.append("暂无威胁分析数据。")

        return "\n".join(lines)

    def _extract_debate_points(self, results: list[Any]) -> list[str]:
        """提取辩论观点。

        Args:
            results: 结果列表

        Returns:
            观点列表
        """
        points = []

        for result in results:
            discoveries = result.discoveries if hasattr(result, "discoveries") else []
            for discovery in discoveries:
                if isinstance(discovery, dict):
                    content = discovery.get("content", "")
                    if content:
                        points.append(content)

        return points

    def _generate_insights_section(self, result: CoordinatorResult) -> str:
        """生成综合洞察章节。

        Args:
            result: 编排器结果

        Returns:
            洞察内容
        """
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            return "暂无综合洞察。"

        elite_result = elite_results[0]
        insights = elite_result.metadata.get("emergent_insights", [])

        if not insights:
            return "暂无涌现洞察。"

        lines = []
        for i, insight in enumerate(insights, 1):
            description = insight.get("description", "")
            significance = insight.get("significance", "")

            lines.append(f"#### 洞察 {i}\n")
            lines.append(f"{description}\n")
            if significance:
                lines.append(f"*战略价值: {significance}*\n")

        return "\n".join(lines)

    def _generate_recommendations(self, result: CoordinatorResult) -> str:
        """生成可执行建议。

        Args:
            result: 编排器结果

        Returns:
            建议内容
        """
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            return "暂无建议。"

        # 简单实现：基于发现生成建议
        recommendations = []

        # 从市场分析生成建议
        if "market" in result.agent_results:
            recommendations.append("**市场策略**: 关注差异化竞争，强化核心价值主张。")

        # 从技术分析生成建议
        if "technical" in result.agent_results:
            recommendations.append("**技术方向**: 考虑性能优化和技术栈升级。")

        # 从体验分析生成建议
        if "experience" in result.agent_results:
            recommendations.append("**用户体验**: 优化核心流程，降低学习成本。")

        return "\n\n".join(recommendations) if recommendations else "暂无具体建议。"

    def _assemble_markdown(self, sections: list[ReportSection]) -> str:
        """组装 Markdown 报告。

        Args:
            sections: 章节列表

        Returns:
            完整的 Markdown 内容
        """
        lines = []

        for section in sections:
            prefix = "#" * section.level
            lines.append(f"\n{prefix} {section.title}\n")
            lines.append(section.content)

        return "\n".join(lines)

    @staticmethod
    def _slugify_target(target: str) -> str:
        return str(target).replace("/", "-").replace(" ", "_")

    def _fallback_history_snapshot(self, result: CoordinatorResult) -> dict[str, Any]:
        """构建最小可用快照，避免报告链路被历史对比阻断。"""
        risks: list[str] = []
        for raw_error in getattr(result, "errors", []) or []:
            if isinstance(raw_error, dict):
                text = str(raw_error.get("error") or "").strip()
            else:
                text = str(raw_error).strip()
            if text:
                risks.append(text[:140])

        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        return {
            "target": str(getattr(result, "target", "") or ""),
            "run_id": str(metadata.get("run_id") or ""),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "conclusions": [],
            "evidence": [],
            "risks": risks[:10],
        }

    def _normalize_history_snapshot(
        self,
        snapshot: dict[str, Any],
        result: CoordinatorResult,
    ) -> dict[str, Any]:
        """归一化快照结构，保证后续读写逻辑稳定。"""
        normalized = dict(snapshot)
        metadata = result.metadata if isinstance(result.metadata, dict) else {}

        normalized["target"] = str(normalized.get("target") or result.target or "")
        normalized["run_id"] = str(normalized.get("run_id") or metadata.get("run_id") or "")
        normalized["timestamp"] = str(
            normalized.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        for key in ("conclusions", "evidence", "risks"):
            value = normalized.get(key)
            normalized[key] = list(value) if isinstance(value, list) else []

        return normalized

    def _safe_history_snapshot(self, result: CoordinatorResult) -> dict[str, Any]:
        """安全获取历史快照：异常时降级为最小结构。"""
        try:
            snapshot = self._section_generator.build_history_snapshot(result)
        except Exception:
            snapshot = None

        if not isinstance(snapshot, dict):
            snapshot = self._fallback_history_snapshot(result)

        return self._normalize_history_snapshot(snapshot, result)

    def _history_file_for_target(self, target: str) -> Path:
        return self._history_dir / f"{self._slugify_target(target)}.jsonl"

    def _load_previous_snapshot(
        self,
        target: str,
        current_run_id: str,
    ) -> dict[str, Any] | None:
        snapshots = self._read_snapshots(target)
        for snapshot in reversed(snapshots):
            snapshot_run_id = str(snapshot.get("run_id") or "")
            if current_run_id and snapshot_run_id == current_run_id:
                continue
            return snapshot
        return None

    def _read_snapshots(self, target: str) -> list[dict[str, Any]]:
        history_file = self._history_file_for_target(target)
        if not history_file.exists():
            return []

        snapshots: list[dict[str, Any]] = []
        for line in history_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                snapshot = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(snapshot, dict):
                snapshots.append(snapshot)
        return snapshots

    def _persist_history_snapshot(self, result: CoordinatorResult) -> None:
        snapshot = self._safe_history_snapshot(result)
        target = str(snapshot.get("target") or result.target)
        history_file = self._history_file_for_target(target)
        history_file.parent.mkdir(parents=True, exist_ok=True)

        existing = self._read_snapshots(target)
        if existing:
            last = existing[-1]
            current_run_id = str(snapshot.get("run_id") or "")
            last_run_id = str(last.get("run_id") or "")
            if current_run_id and current_run_id == last_run_id:
                return
            if (
                not current_run_id
                and last.get("conclusions") == snapshot.get("conclusions")
                and last.get("evidence") == snapshot.get("evidence")
                and last.get("risks") == snapshot.get("risks")
            ):
                return

        with open(history_file, "a", encoding="utf-8") as file:
            file.write(json.dumps(snapshot, ensure_ascii=False))
            file.write("\n")


def generate_diff_report(
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any] | None,
) -> "DiffReport":
    """生成差异报告。

    Args:
        current_snapshot: 当前分析快照
        previous_snapshot: 之前的分析快照

    Returns:
        差异报告
    """
    from src.scheduler import DiffReport

    if not previous_snapshot:
        return DiffReport(
            target=current_snapshot.get("target", ""),
            previous_timestamp="",
            current_timestamp=current_snapshot.get("timestamp", ""),
            change_score=1.0,
            added_conclusions=current_snapshot.get("conclusions", []),
            added_evidence=current_snapshot.get("evidence", []),
            added_risks=current_snapshot.get("risks", []),
            alerts_triggered=["首次分析"],
        )

    current_conclusions = set(current_snapshot.get("conclusions", []))
    previous_conclusions = set(previous_snapshot.get("conclusions", []))

    current_evidence = set(current_snapshot.get("evidence", []))
    previous_evidence = set(previous_snapshot.get("evidence", []))

    current_risks = set(current_snapshot.get("risks", []))
    previous_risks = set(previous_snapshot.get("risks", []))

    # 计算变化
    added_conclusions = list(current_conclusions - previous_conclusions)
    removed_conclusions = list(previous_conclusions - current_conclusions)

    added_evidence = list(current_evidence - previous_evidence)
    removed_evidence = list(previous_evidence - current_evidence)

    added_risks = list(current_risks - previous_risks)
    removed_risks = list(previous_risks - current_risks)

    # 计算变化程度
    total_items = len(current_conclusions) + len(previous_conclusions) + \
                  len(current_evidence) + len(previous_evidence) + \
                  len(current_risks) + len(previous_risks)

    changed_items = len(added_conclusions) + len(removed_conclusions) + \
                    len(added_evidence) + len(removed_evidence) + \
                    len(added_risks) + len(removed_risks)

    change_score = changed_items / total_items if total_items > 0 else 0.0

    # 触发告警
    alerts = []
    if change_score > 0.3:
        alerts.append(f"显著变化: {change_score:.1%} 内容更新")
    if len(added_risks) > 2:
        alerts.append(f"新增风险: {len(added_risks)} 项")

    return DiffReport(
        target=current_snapshot.get("target", ""),
        previous_timestamp=previous_snapshot.get("timestamp", ""),
        current_timestamp=current_snapshot.get("timestamp", ""),
        change_score=change_score,
        added_conclusions=added_conclusions,
        removed_conclusions=removed_conclusions,
        added_evidence=added_evidence,
        removed_evidence=removed_evidence,
        added_risks=added_risks,
        removed_risks=removed_risks,
        alerts_triggered=alerts,
    )


# 全局报告生成器实例（延迟加载）
_reporter: Reporter | None = None


def get_reporter() -> Reporter:
    """获取全局报告生成器实例。

    Returns:
        报告生成器
    """
    global _reporter
    if _reporter is None:
        _reporter = Reporter()
    return _reporter


def reset_reporter() -> None:
    """重置全局报告生成器。"""
    global _reporter
    _reporter = None
