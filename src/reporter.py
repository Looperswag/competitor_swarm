"""报告生成器模块。

负责生成结构化的 Markdown 报告。
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.coordinator import CoordinatorResult
from src.utils.config import get_config
from src.reporting import CitationManager, SectionGenerator, Formatters, get_html_generator


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

        # 初始化辅助模块
        self._citation_manager = CitationManager()
        self._section_generator = SectionGenerator(self._citation_manager)
        self._formatters = Formatters()

    def generate_markdown(self, result: CoordinatorResult) -> str:
        """生成 Markdown 报告。

        Args:
            result: 编排器结果

        Returns:
            Markdown 报告内容
        """
        sections: list[ReportSection] = []

        # 标题和元信息
        sections.append(ReportSection("竞品分析报告", self._generate_title(result), level=1))
        sections.append(ReportSection("元信息", self._generate_metadata(result)))

        # 执行摘要（使用新的章节生成器）
        summary_section = self._section_generator.generate_executive_summary(result, result.target)
        sections.append(summary_section)

        # 各维度分析
        sections.extend(self._generate_dimension_sections(result))

        # 红蓝队对抗
        sections.append(ReportSection("红蓝队对抗", self._generate_debate_section(result)))

        # 综合洞察（使用新的章节生成器）
        insights_section = self._section_generator.generate_insights_section(result)
        sections.append(insights_section)

        # 可执行建议（使用新的章节生成器）
        recommendations_section = self._section_generator.generate_recommendations_section(result)
        sections.append(recommendations_section)

        # 附录
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
            target_safe = result.target.replace("/", "-").replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analysis_{target_safe}_{timestamp}.md"

        report_content = self.generate_markdown(result)
        report_path = self._output_path / filename

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

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
        return html_generator.generate_html(result, filename)

    def save_json_report(self, result: CoordinatorResult, filename: str | None = None) -> str:
        """保存 JSON 格式报告数据。

        Args:
            result: 编排器结果
            filename: 文件名，默认基于目标名称生成

        Returns:
            保存的 JSON 文件路径
        """
        html_generator = get_html_generator()
        return html_generator.generate_json(result, filename)

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
        """生成红蓝队对抗章节。

        Args:
            result: 编排器结果

        Returns:
            对抗内容
        """
        red_results = result.agent_results.get("red_team", [])
        blue_results = result.agent_results.get("blue_team", [])

        content = ""

        # 红队观点
        content += "### ⚔️ 红队观点（批判）\n\n"
        if red_results:
            red_points = self._extract_debate_points(red_results)
            limit = 15
            content += "\n".join([f"- {p}" for p in red_points[:limit]])
            if len(red_points) > limit:
                content += f"\n\n*... 还有 {len(red_points) - limit} 条红队观点（已省略）*"
        else:
            content += "暂无红队分析。"

        content += "\n\n### 🛡️ 蓝队观点（辩护）\n\n"
        if blue_results:
            blue_points = self._extract_debate_points(blue_results)
            limit = 15
            content += "\n".join([f"- {p}" for p in blue_points[:limit]])
            if len(blue_points) > limit:
                content += f"\n\n*... 还有 {len(blue_points) - limit} 条蓝队观点（已省略）*"
        else:
            content += "暂无蓝队分析。"

        return content

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
