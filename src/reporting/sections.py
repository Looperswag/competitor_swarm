"""章节生成模块。

提供报告各章节的生成功能。
"""

import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.coordinator import CoordinatorResult
    from src.reporting.citations import CitationManager


@dataclass
class ReportSection:
    """报告章节。"""

    title: str
    content: str
    level: int = 2  # Markdown 标题级别


class SectionGenerator:
    """章节生成器。

    生成报告的各个章节。
    """

    def __init__(self, citation_manager: "CitationManager | None" = None) -> None:
        """初始化章节生成器。

        Args:
            citation_manager: 引用管理器
        """
        self._citation_manager = citation_manager

    def _clean_markdown_text(self, text: str) -> str:
        """清理 Markdown 格式，只保留段落文本。

        Args:
            text: 原始文本

        Returns:
            清理后的文本
        """
        # 移除 Markdown 标题（# ## ### 等）
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)

        # 移除加粗标记，但保留文本
        text = text.replace('**', '').replace('__', '')

        # 移除多余的空行
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def generate_executive_summary(
        self,
        result: "CoordinatorResult",
        target: str,
    ) -> ReportSection:
        """生成执行摘要。

        Args:
            result: 编排器结果
            target: 目标产品

        Returns:
            执行摘要章节
        """
        # 获取精英 Agent 的结果
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            content = "暂无综合分析结果。"
        else:
            elite_result = elite_results[0]
            # AgentResult 是 dataclass，不是 dict
            metadata = elite_result.metadata
            if metadata is None:
                metadata = {}

            report_data = metadata.get("report", {}) if isinstance(metadata, dict) else {}

            if report_data.get("summary"):
                raw_summary = report_data["summary"]
                content = self._clean_markdown_text(raw_summary)
            else:
                content = self._generate_fallback_summary(result, target)

        return ReportSection("执行摘要", content)

    def _generate_fallback_summary(
        self,
        result: "CoordinatorResult",
        target: str,
    ) -> str:
        """生成备用摘要。

        Args:
            result: 编排器结果
            target: 目标产品

        Returns:
            摘要内容
        """
        total_discoveries = result.metadata.get("total_discoveries", 0)
        total_signals = result.metadata.get("total_signals", 0)
        duration = result.duration

        # 如果 metadata 缺失或为 0，尝试从结果中补算
        if total_discoveries == 0:
            total_discoveries = sum(
                len(r.discoveries) for rs in result.agent_results.values() for r in rs
                if hasattr(r, "discoveries") and isinstance(r.discoveries, list)
            )

        summary_parts = [
            f"本报告对「{target}」进行了全面深入的竞品分析。",
            "",
            "### 分析概览",
            f"- 分析耗时：{duration:.1f} 秒",
            f"- 总发现数量：{total_discoveries} 条",
        ]

        if total_signals:
            summary_parts.append(f"- 信号数量：{total_signals} 条")

        summary_parts.append("- 分析维度：侦察、体验、技术、市场、红蓝队对抗、综合分析")
        summary_parts.append("")
        summary_parts.append("### 维度覆盖")

        type_names = {
            "scout": "侦察",
            "experience": "体验",
            "technical": "技术",
            "market": "市场",
            "red_team": "红队",
            "blue_team": "蓝队",
            "elite": "综合",
        }
        for agent_type, results in result.agent_results.items():
            if not results or agent_type == "elite":
                continue
            discovery_count = sum(
                len(r.discoveries) for r in results
                if hasattr(r, "discoveries") and isinstance(r.discoveries, list)
            )
            summary_parts.append(
                f"- **{type_names.get(agent_type, agent_type)}**：{discovery_count} 条发现"
            )

        # 如果有错误，给出提示
        if getattr(result, "errors", None):
            summary_parts.append(f"- ⚠️ 任务异常：{len(result.errors)} 项（详见各维度或日志）")

        summary_parts.extend([
            "",
            "**核心结论**：请查看详细分析章节获取具体洞察。",
        ])

        return "\n".join(summary_parts)

    def generate_insights_section(
        self,
        result: "CoordinatorResult",
    ) -> ReportSection:
        """生成综合洞察章节。

        Args:
            result: 编排器结果

        Returns:
            综合洞察章节
        """
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            return ReportSection("综合洞察", "暂无涌现洞察。")

        elite_result = elite_results[0]
        # AgentResult 是 dataclass，不是 dict
        metadata = elite_result.metadata
        if metadata is None:
            metadata = {}

        report_data = metadata.get("report", {}) if isinstance(metadata, dict) else {}

        insights = report_data.get("insights", [])

        # 尝试从 emergent_insights 获取（向后兼容）
        if not insights and isinstance(metadata, dict):
            insights = metadata.get("emergent_insights", [])

        if not insights:
            return ReportSection("综合洞察", "暂无涌现洞察。")

        content_parts = []
        for i, insight in enumerate(insights, 1):
            if isinstance(insight, dict):
                content = insight.get("content", str(insight))
                strategic_value = insight.get("strategic_value", "medium")
            else:
                content = str(insight)
                strategic_value = "medium"

            value_map = {
                "high": "*高战略价值*",
                "medium": "*中等战略价值*",
                "low": "*低战略价值*",
            }

            content_parts.extend([
                f"#### 洞察 {i}",
                "",
                content,
                "",
                value_map.get(strategic_value, ""),
                "",
            ])

        return ReportSection("综合洞察", "\n".join(content_parts))

    def generate_recommendations_section(
        self,
        result: "CoordinatorResult",
    ) -> ReportSection:
        """生成可执行建议章节。

        Args:
            result: 编排器结果

        Returns:
            可执行建议章节
        """
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            return ReportSection("可执行建议", "暂无具体建议。")

        elite_result = elite_results[0]
        # AgentResult 是 dataclass，不是 dict
        metadata = elite_result.metadata
        if metadata is None:
            metadata = {}

        report_data = metadata.get("report", {}) if isinstance(metadata, dict) else {}

        recommendations = report_data.get("recommendations", [])
        if not recommendations:
            # 生成基础建议
            recommendations = self._generate_fallback_recommendations(result)

        content_parts = []
        for i, rec in enumerate(recommendations, 1):
            if isinstance(rec, dict):
                title = rec.get("title", rec.get("category", f"建议 {i}"))
                description = rec.get("description", rec.get("content", ""))
                priority = rec.get("priority", "medium")
                difficulty = rec.get("difficulty", "medium")
            else:
                title = f"建议 {i}"
                description = str(rec)
                priority = "medium"
                difficulty = "medium"

            priority_map = {
                "high": "**[高优先级]**",
                "medium": "*[中优先级]*",
                "low": "[低优先级]",
            }

            difficulty_map = {
                "high": "难度：高",
                "medium": "难度：中",
                "low": "难度：低",
            }

            content_parts.extend([
                f"### {title}",
                "",
                f"{priority_map.get(priority, '')} {difficulty_map.get(difficulty, '')}",
                "",
                description,
                "",
            ])

        return ReportSection("可执行建议", "\n".join(content_parts))

    def _generate_fallback_recommendations(
        self,
        result: "CoordinatorResult",
    ) -> list[dict[str, Any]]:
        """生成备用建议。

        Args:
            result: 编排器结果

        Returns:
            建议列表
        """
        recommendations = []

        # 根据各维度结果生成建议
        if "market" in result.agent_results:
            recommendations.append({
                "title": "市场策略建议",
                "description": "关注差异化竞争，强化核心价值主张，在目标细分市场建立领先地位。",
                "priority": "high",
                "difficulty": "medium",
            })

        if "technical" in result.agent_results:
            recommendations.append({
                "title": "技术方向建议",
                "description": "持续关注技术栈更新，优化系统性能和安全性，为规模化发展做好技术储备。",
                "priority": "high",
                "difficulty": "high",
            })

        if "experience" in result.agent_results:
            recommendations.append({
                "title": "用户体验建议",
                "description": "优化核心流程，降低学习成本，提升跨设备体验的一致性。",
                "priority": "medium",
                "difficulty": "medium",
            })

        if "red_team" in result.agent_results or "blue_team" in result.agent_results:
            recommendations.append({
                "title": "产品优化建议",
                "description": "平衡功能完整性与易用性，在保持核心优势的同时弥补关键短板。",
                "priority": "high",
                "difficulty": "medium",
            })

        return recommendations

    def generate_appendix(
        self,
        result: "CoordinatorResult",
    ) -> list[ReportSection]:
        """生成附录章节。

        Args:
            result: 编排器结果

        Returns:
            附录章节列表
        """
        sections = []

        # 来源索引
        if self._citation_manager and self._citation_manager.count() > 0:
            sections.append(ReportSection(
                "附录",
                self._citation_manager.format_appendix(),
                level=2,
            ))

        # 分析方法论
        sections.append(ReportSection(
            "附录",
            self._generate_methodology_section(),
            level=2,
        ))

        return sections

    def _generate_methodology_section(self) -> str:
        """生成分析方法论说明。

        Returns:
            方法论说明内容
        """
        return """## 分析方法论

本报告采用多智能体协同分析框架，通过以下六个专业维度进行深度竞品分析：

### 分析维度

1. **侦察分析**：收集产品基本面、商业模式、功能清单、用户定位等公开信息
2. **体验分析**：评估 UI/UX 设计、交互流程、易学性和跨设备一致性
3. **技术分析**：推测技术栈选择、架构模式、性能特征和安全机制
4. **市场分析**：分析市场定位、竞争格局、用户评价和增长趋势
5. **红队批判**：找出产品问题、风险和竞争劣势
6. **蓝队辩护**：识别核心优势、创新点和竞争壁垒

### 协作机制

- **Stigmergy 通信**：Agent 之间通过共享环境间接通信，高质量发现会被更多引用
- **任务交接 (Handoff)**：Agent 可以请求其他 Agent 深入分析特定领域
- **红蓝队对抗**：通过批判性分析和辩护性回应，揭示产品全貌

### 信息来源

- 官方渠道（官网、文档、公告）
- 应用商店和评价平台
- 行业媒体和新闻报道
- 技术博客和开发者社区
- 专家分析和行业报告

*报告生成时间：请查看元信息中的生成时间。*
"""
