"""章节生成模块。

提供报告各章节的生成功能。
"""

import re
from dataclasses import dataclass
from datetime import datetime
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

    def generate_quick_read_section(self, result: "CoordinatorResult") -> ReportSection:
        """生成固定头部的 3 分钟速读章节。"""
        threats = self._collect_key_points(
            result,
            agent_types=["red_team", "technical", "market"],
            limit=3,
            max_length=100,
        )
        opportunities = self._collect_key_points(
            result,
            agent_types=["blue_team", "market", "experience", "scout"],
            limit=3,
            max_length=100,
        )
        actions = self._collect_action_points(result, limit=3, max_length=120)

        if not threats:
            threats = ["暂无高置信度威胁结论。"]
        if not opportunities:
            opportunities = ["暂无明确战略机会。"]
        if not actions:
            actions = [
                "优先核验高风险结论并补充证据来源。",
                "围绕最具确定性的机会制定 30 天行动计划。",
                "将关键改进项拆解为负责人、截止时间和验收标准。",
            ]

        content_lines = [
            "### Top Threat",
            *[f"- {item}" for item in threats],
            "",
            "### Top Opportunity",
            *[f"- {item}" for item in opportunities],
            "",
            "### Top Actions",
            *[f"- {item}" for item in actions[:3]],
        ]
        return ReportSection("核心洞察（3 分钟速读）", "\n".join(content_lines))

    def build_history_snapshot(self, result: "CoordinatorResult") -> dict[str, Any]:
        """构建用于历史对比的快照数据。"""
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        run_id = metadata.get("run_id")

        conclusions = self._collect_conclusions(result, limit=10, max_length=140)
        evidence = self._collect_key_points(
            result,
            agent_types=["scout", "experience", "technical", "market"],
            limit=12,
            max_length=140,
        )
        risks = self._collect_key_points(
            result,
            agent_types=["red_team"],
            limit=10,
            max_length=140,
        )

        for raw_error in getattr(result, "errors", []) or []:
            error_text = ""
            if isinstance(raw_error, dict):
                error_text = str(raw_error.get("error") or "").strip()
            else:
                error_text = str(raw_error).strip()
            if error_text:
                risks.append(self._truncate_text(error_text, max_length=140))

        return {
            "target": str(getattr(result, "target", "") or ""),
            "run_id": str(run_id) if run_id is not None else "",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "conclusions": self._unique_limited(conclusions, limit=10),
            "evidence": self._unique_limited(evidence, limit=12),
            "risks": self._unique_limited(risks, limit=10),
        }

    def generate_history_diff_section(
        self,
        current_snapshot: dict[str, Any],
        previous_snapshot: dict[str, Any] | None,
    ) -> ReportSection:
        """生成同目标多次分析的历史对比章节。"""
        if not previous_snapshot:
            return ReportSection(
                "历史对比（同目标）",
                "暂无可对比的历史记录（需至少两次同目标分析）。",
            )

        previous_time = str(previous_snapshot.get("timestamp") or "未知")
        current_time = str(current_snapshot.get("timestamp") or "未知")

        conclusion_rows = self._format_diff_rows(
            old_items=previous_snapshot.get("conclusions", []),
            new_items=current_snapshot.get("conclusions", []),
        )
        evidence_rows = self._format_diff_rows(
            old_items=previous_snapshot.get("evidence", []),
            new_items=current_snapshot.get("evidence", []),
        )
        risk_rows = self._format_diff_rows(
            old_items=previous_snapshot.get("risks", []),
            new_items=current_snapshot.get("risks", []),
        )

        lines = [
            f"- 对比基线: {previous_time}",
            f"- 当前结果: {current_time}",
            "",
            "### 结论变化",
            *conclusion_rows,
            "",
            "### 证据变化",
            *evidence_rows,
            "",
            "### 风险变化",
            *risk_rows,
        ]
        return ReportSection("历史对比（同目标）", "\n".join(lines).rstrip())

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

    def _collect_conclusions(self, result: "CoordinatorResult", limit: int, max_length: int) -> list[str]:
        """提取结论类文本（优先综合 Agent 洞察）。"""
        conclusions: list[str] = []
        elite_results = result.agent_results.get("elite", [])

        if elite_results:
            elite_result = elite_results[0]
            metadata = elite_result.metadata if hasattr(elite_result, "metadata") else {}
            if metadata is None:
                metadata = {}
            report_data = metadata.get("report", {}) if isinstance(metadata, dict) else {}

            insights = report_data.get("insights", [])
            if not insights and isinstance(metadata, dict):
                insights = metadata.get("emergent_insights", [])

            for item in insights:
                if isinstance(item, dict):
                    text = (
                        item.get("content")
                        or item.get("description")
                        or item.get("text")
                        or ""
                    )
                else:
                    text = str(item)
                text = " ".join(str(text).split()).strip()
                if text:
                    conclusions.append(self._truncate_text(text, max_length=max_length))

            summary_text = report_data.get("summary", "")
            for sentence in re.split(r"[。！？\n]", str(summary_text or "")):
                sentence = " ".join(sentence.split()).strip()
                if len(sentence) >= 8:
                    conclusions.append(self._truncate_text(sentence, max_length=max_length))

        if not conclusions:
            conclusions = self._collect_key_points(
                result,
                agent_types=["blue_team", "market", "scout"],
                limit=limit,
                max_length=max_length,
            )

        return self._unique_limited(conclusions, limit=limit)

    def _collect_key_points(
        self,
        result: "CoordinatorResult",
        agent_types: list[str],
        limit: int,
        max_length: int,
    ) -> list[str]:
        """按 Agent 优先级提取关键要点。"""
        points: list[str] = []
        seen: set[str] = set()

        for agent_type in agent_types:
            for agent_result in result.agent_results.get(agent_type, []):
                discoveries = agent_result.discoveries if hasattr(agent_result, "discoveries") else []
                for discovery in discoveries:
                    text = self._extract_discovery_text(discovery)
                    if not text:
                        continue
                    normalized = self._truncate_text(text, max_length=max_length)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    points.append(normalized)
                    if len(points) >= limit:
                        return points

        return points

    def _collect_action_points(self, result: "CoordinatorResult", limit: int, max_length: int) -> list[str]:
        """提取优先行动项。"""
        actions: list[str] = []
        elite_results = result.agent_results.get("elite", [])

        if elite_results:
            elite_result = elite_results[0]
            metadata = elite_result.metadata if hasattr(elite_result, "metadata") else {}
            report_data = metadata.get("report", {}) if isinstance(metadata, dict) else {}
            recommendations = report_data.get("recommendations", [])

            for recommendation in recommendations:
                text = ""
                if isinstance(recommendation, dict):
                    title = str(recommendation.get("title") or recommendation.get("category") or "").strip()
                    description = str(
                        recommendation.get("description")
                        or recommendation.get("content")
                        or ""
                    ).strip()
                    if title and description:
                        text = f"{title}: {description}"
                    else:
                        text = title or description
                else:
                    text = str(recommendation).strip()

                if text:
                    actions.append(self._truncate_text(text, max_length=max_length))
                if len(actions) >= limit:
                    break

        return self._unique_limited(actions, limit=limit)

    @staticmethod
    def _extract_discovery_text(discovery: Any) -> str:
        """从 Discovery/Signal 结构中提取文本。"""
        if isinstance(discovery, dict):
            text = discovery.get("content") or discovery.get("evidence") or ""
        elif hasattr(discovery, "content"):
            text = getattr(discovery, "content", "")
        else:
            text = str(discovery)
        return " ".join(str(text).split()).strip()

    @staticmethod
    def _truncate_text(text: str, max_length: int) -> str:
        """截断文本，避免摘要过长。"""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3].rstrip() + "..."

    @staticmethod
    def _unique_limited(items: list[str], limit: int) -> list[str]:
        """去重并保留顺序。"""
        unique_items: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = " ".join(str(item).split()).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_items.append(normalized)
            if len(unique_items) >= limit:
                break
        return unique_items

    def _format_diff_rows(self, old_items: Any, new_items: Any) -> list[str]:
        """将变化格式化为 Markdown 行。"""
        old_list = self._normalize_items(old_items)
        new_list = self._normalize_items(new_items)

        added = [item for item in new_list if item not in old_list]
        removed = [item for item in old_list if item not in new_list]

        if not added and not removed:
            return ["- 无变化。"]

        rows: list[str] = []
        max_items = 4

        for item in added[:max_items]:
            rows.append(f"- 新增: {item}")
        if len(added) > max_items:
            rows.append(f"- 新增其余 {len(added) - max_items} 条已省略。")

        for item in removed[:max_items]:
            rows.append(f"- 移除: {item}")
        if len(removed) > max_items:
            rows.append(f"- 移除其余 {len(removed) - max_items} 条已省略。")

        return rows

    def _normalize_items(self, raw_items: Any) -> list[str]:
        """规范化列表输入并做去重。"""
        if not isinstance(raw_items, list):
            return []
        return self._unique_limited([str(item) for item in raw_items], limit=50)

    def generate_insights_section(
        self,
        result: "CoordinatorResult",
    ) -> ReportSection:
        """生成综合洞察章节（增强版）。

        支持新的增强格式，包含战略含义和可行动方向。

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
                content = insight.get("content", insight.get("description", str(insight)))
                strategic_value = insight.get("strategic_value", "medium")
                strategic_implication = insight.get("strategic_implication", "")
                actionable_direction = insight.get("actionable_direction", "")
                evidence_chain = insight.get("evidence_chain", [])
            else:
                content = str(insight)
                strategic_value = "medium"
                strategic_implication = ""
                actionable_direction = ""
                evidence_chain = []

            value_map = {
                "high": "🔴 高战略价值",
                "medium": "🟡 中等战略价值",
                "low": "🟢 低战略价值",
            }

            content_parts.extend([
                f"#### 洞察 {i}",
                "",
                content,
                "",
            ])

            # 添加战略价值标签
            if strategic_value:
                content_parts.append(f"**{value_map.get(strategic_value, '中等战略价值')}**")

            # 添加战略含义（如果有）
            if strategic_implication:
                content_parts.extend([
                    "",
                    f"**战略含义**：{strategic_implication}",
                ])

            # 添加可行动方向（如果有）
            if actionable_direction:
                content_parts.extend([
                    "",
                    f"**可行动方向**：{actionable_direction}",
                ])

            # 添加证据链（如果有）
            if evidence_chain:
                agents_str = ", ".join(f"[{a}]" for a in evidence_chain)
                content_parts.extend([
                    "",
                    f"*证据来源：{agents_str}*",
                ])

            content_parts.append("")

        return ReportSection("综合洞察", "\n".join(content_parts))

    def generate_strategic_positioning_matrix(
        self,
        result: "CoordinatorResult",
    ) -> ReportSection:
        """生成战略定位矩阵章节。

        Args:
            result: 编排器结果

        Returns:
            战略定位矩阵章节
        """
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            return ReportSection("战略定位矩阵", "暂无战略定位数据。")

        elite_result = elite_results[0]
        metadata = elite_result.metadata if hasattr(elite_result, "metadata") else {}
        if metadata is None:
            metadata = {}

        report_data = metadata.get("report", {}) if isinstance(metadata, dict) else {}
        strategic_matrix = report_data.get("strategic_matrix", [])

        if not strategic_matrix:
            return ReportSection("战略定位矩阵", "暂无战略定位数据。")

        # 生成 Markdown 表格
        content_parts = [
            "| 维度 | 竞品表现 | 我方差距 | 战略含义 |",
            "|------|---------|---------|---------|",
        ]

        for row in strategic_matrix:
            dimension = row.get("dimension", "")
            competitor_perf = row.get("competitor_performance", "")
            our_gap = row.get("our_gap", "")
            implication = row.get("strategic_implication", "")
            content_parts.append(f"| {dimension} | {competitor_perf} | {our_gap} | {implication} |")

        return ReportSection("战略定位矩阵", "\n".join(content_parts))

    def generate_risk_opportunity_matrix(
        self,
        result: "CoordinatorResult",
    ) -> ReportSection:
        """生成风险/机会矩阵章节。

        Args:
            result: 编排器结果

        Returns:
            风险/机会矩阵章节
        """
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            return ReportSection("风险/机会矩阵", "暂无风险/机会数据。")

        elite_result = elite_results[0]
        metadata = elite_result.metadata if hasattr(elite_result, "metadata") else {}
        if metadata is None:
            metadata = {}

        report_data = metadata.get("report", {}) if isinstance(metadata, dict) else {}
        risk_matrix = report_data.get("risk_opportunity_matrix", [])

        if not risk_matrix:
            return ReportSection("风险/机会矩阵", "暂无风险/机会数据。")

        # 生成 Markdown 表格
        content_parts = [
            "| 类型 | 事项 | 影响程度 | 发生概率 | 应对策略 |",
            "|------|------|---------|---------|---------|",
        ]

        for row in risk_matrix:
            type_emoji = "⚠️" if row.get("type") == "风险" else "🚀"
            item_type = row.get("type", "")
            item = row.get("item", "")
            impact = row.get("impact", "")
            probability = row.get("probability", "")
            strategy = row.get("strategy", "")
            content_parts.append(
                f"| {type_emoji} {item_type} | {item} | {impact} | {probability} | {strategy} |"
            )

        return ReportSection("风险/机会矩阵", "\n".join(content_parts))

    def generate_recommendations_section(
        self,
        result: "CoordinatorResult",
    ) -> ReportSection:
        """生成可执行建议章节（表格格式）。

        将所有建议整合成一个汇总表格，便于快速浏览和决策。

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

        # 映射表
        priority_map = {
            "high": "🔴高",
            "medium": "🟡中",
            "low": "🟢低",
        }

        difficulty_map = {
            "high": "困难",
            "medium": "中等",
            "low": "简单",
        }

        roi_map = {
            "high": "高",
            "medium": "中",
            "low": "低",
        }

        timeline_map = {
            "short": "短期(1-3月)",
            "medium": "中期(3-6月)",
            "long": "长期(6-12月)",
        }

        # 构建汇总表格
        content_parts = [
            "本节汇总所有可执行建议，按优先级排序：",
            "",
            "| # | 建议标题 | 行动描述 | 优先级 | 难度 | 预期ROI | 时间线 | 成功指标 |",
            "|---|---------|---------|--------|------|---------|--------|---------|",
        ]

        # 收集有实施步骤的建议（用于折叠详情）
        detailed_steps: list[tuple[int, str, list[str]]] = []

        for i, rec in enumerate(recommendations, 1):
            if isinstance(rec, dict):
                title = rec.get("title", rec.get("category", f"建议 {i}"))
                description = rec.get("description", rec.get("content", ""))
                priority = rec.get("priority", "medium")
                difficulty = rec.get("difficulty", "medium")
                roi = rec.get("roi", "medium")
                timeline = rec.get("timeline", "medium")
                steps = rec.get("steps", [])
                success_metrics = rec.get("success_metrics", "")
            else:
                title = f"建议 {i}"
                description = str(rec)
                priority = "medium"
                difficulty = "medium"
                roi = "medium"
                timeline = "medium"
                steps = []
                success_metrics = ""

            # 截断过长的描述（表格显示用）
            short_desc = description[:50] + "..." if len(description) > 50 else description
            short_metrics = success_metrics[:30] + "..." if len(success_metrics) > 30 else success_metrics

            # 添加表格行
            content_parts.append(
                f"| {i} | {title} | {short_desc} | {priority_map.get(priority, '中')} | "
                f"{difficulty_map.get(difficulty, '中等')} | {roi_map.get(roi, '中')} | "
                f"{timeline_map.get(timeline, '中期')} | {short_metrics or '-'} |"
            )

            # 收集有详细步骤的建议
            if steps:
                detailed_steps.append((i, title, steps))

        # 添加详细步骤折叠区块（如果有）
        if detailed_steps:
            content_parts.extend([
                "",
                "<details>",
                "<summary>📋 查看详细实施步骤</summary>",
                "",
            ])
            for idx, title, steps in detailed_steps:
                content_parts.extend([
                    f"### 建议 {idx}：{title}",
                    "",
                    "**实施步骤**：",
                ])
                for j, step in enumerate(steps, 1):
                    content_parts.append(f"{j}. {step}")
                content_parts.append("")

            content_parts.extend([
                "</details>",
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

        insight_trace = self._generate_insight_trace_section(result)
        if insight_trace:
            sections.append(ReportSection(
                "附录",
                insight_trace,
                level=2,
            ))

        # 分析方法论
        sections.append(ReportSection(
            "附录",
            self._generate_methodology_section(),
            level=2,
        ))

        return sections

    def _extract_insight_trace_entries(self, result: "CoordinatorResult") -> list[dict[str, Any]]:
        elite_results = result.agent_results.get("elite", [])
        if not elite_results:
            return []

        elite_result = elite_results[0]
        metadata = elite_result.metadata if hasattr(elite_result, "metadata") else {}
        if not isinstance(metadata, dict):
            return []

        report_data = metadata.get("report", {})
        traces = report_data.get("insight_trace", []) if isinstance(report_data, dict) else []
        if not traces:
            traces = metadata.get("insight_trace", [])

        if not isinstance(traces, list):
            return []

        normalized: list[dict[str, Any]] = []
        for trace in traces:
            if isinstance(trace, dict):
                normalized.append(trace)
        return normalized

    def _generate_insight_trace_section(self, result: "CoordinatorResult") -> str:
        traces = self._extract_insight_trace_entries(result)
        if not traces:
            return ""

        lines = ["## 洞察追溯（insight_trace）", ""]
        for idx, trace in enumerate(traces, start=1):
            trace_id = str(trace.get("trace_id") or f"trace-{idx}")
            motif_type = str(trace.get("motif_type") or "unknown")
            score = trace.get("score")
            score_text = f"{float(score):.4f}" if isinstance(score, (int, float)) else "N/A"

            signal_ids = trace.get("signal_ids", [])
            if not isinstance(signal_ids, list):
                signal_ids = []
            claim_ids = trace.get("claim_ids", [])
            if not isinstance(claim_ids, list):
                claim_ids = []
            phase_trace = trace.get("phase_trace", [])
            if not isinstance(phase_trace, list):
                phase_trace = []

            lines.append(f"### Trace {idx}: {trace_id}")
            lines.append(f"- motif_type: {motif_type}")
            lines.append(f"- score: {score_text}")
            lines.append(f"- signal_ids: {', '.join(str(item) for item in signal_ids) if signal_ids else '无'}")
            lines.append(f"- claim_ids: {', '.join(str(item) for item in claim_ids) if claim_ids else '无'}")
            lines.append(f"- phase_trace: {' -> '.join(str(item) for item in phase_trace) if phase_trace else '无'}")
            lines.append("")

        return "\n".join(lines).rstrip()

    def _generate_methodology_section(self) -> str:
        """生成分析方法论说明（增强版）。

        Returns:
            方法论说明内容
        """
        return """## 分析方法论

本报告采用 **CompetitorSwarm** 多智能体协同分析框架，通过六个专业维度的深度协作，实现对竞品的全面、客观、深入分析。

---

### 一、分析框架概述

CompetitorSwarm 是一个基于大语言模型的多 Agent 协作系统，核心理念包括：

- **专业化分工**：每个 Agent 专注于特定分析维度，形成深度专业能力
- **协同增效**：Agent 之间通过结构化通信机制共享发现，相互引用和验证
- **对抗平衡**：红蓝队机制确保分析既有批判深度，又有客观公正
- **置信度量化**：所有结论都附带置信度评分，帮助读者评估结论可靠性

---

### 二、四阶段执行流程

分析过程分为四个顺序阶段，每个阶段有不同的协作模式和目标：

| 阶段 | 名称 | 主要任务 | 协作模式 |
|-----|------|---------|---------|
| Phase 1 | 侦察发现 | 各 Agent 独立收集信息，发现初步信号 | 并行独立 |
| Phase 2 | 深度分析 | Agent 之间交叉引用，深入挖掘特定领域 | 协作分析 |
| Phase 3 | 对抗验证 | 红蓝队进行批判与辩护，检验结论稳健性 | 对抗验证 |
| Phase 4 | 整合输出 | Elite Agent 整合所有发现，生成结构化报告 | 统合输出 |

---

### 三、六维度分析详解

每个维度由专门的 Agent 负责，具有独特的分析视角和方法论：

#### 3.1 Scout（侦察分析）
- **职责**：收集产品基本面信息，建立分析基础
- **分析内容**：商业模式、功能清单、用户定位、发展历程、融资信息
- **输出特点**：客观事实为主，为后续分析提供素材

#### 3.2 Experience（体验分析）
- **职责**：从用户体验角度评估产品设计
- **分析内容**：UI/UX 设计、交互流程、易学性、跨设备一致性、无障碍设计
- **评估标准**：尼尔森十大可用性原则、Material Design/HIG 规范

#### 3.3 Technical（技术分析）
- **职责**：推测和评估产品技术实现
- **分析内容**：技术栈选择、架构模式、性能特征、安全机制、扩展性设计
- **分析方法**：网络请求分析、前端代码审查、性能指标测试

#### 3.4 Market（市场分析）
- **职责**：分析市场竞争格局和增长潜力
- **分析内容**：市场定位、竞争格局、用户评价、增长趋势、商业化策略
- **数据来源**：应用商店数据、行业报告、用户评论、第三方分析平台

#### 3.5 Red Team（红队批判）
- **职责**：批判性审视产品，发现问题和风险
- **分析内容**：功能缺陷、安全风险、竞争劣势、用户体验痛点、潜在合规问题
- **分析立场**：假设为竞争对手，寻找可攻击的弱点

#### 3.6 Blue Team（蓝队辩护）
- **职责**：识别和论证产品核心优势
- **分析内容**：核心壁垒、创新亮点、差异化优势、品牌价值、网络效应
- **分析立场**：假设为产品方，构建竞争优势的论据

---

### 四、Stigmergy 协作机制

CompetitorSwarm 采用 **Stigmergy（信息素）通信机制**，这是一种源自昆虫群体的间接协作模式：

#### 4.1 核心原理
- Agent 不直接通信，而是通过**共享环境**（Stigmergy Store）交换信息
- 每个 Agent 可以发布"发现"（Finding），其他 Agent 可以引用和验证
- 高质量发现会被多次引用，形成**信号强度**（Signal Strength）

#### 4.2 信息类型
- **发现（Finding）**：某个维度的具体观察或结论
- **信号（Signal）**：带置信度的结构化信息，包含来源和证据
- **引用（Reference）**：Agent 之间的互相引用，建立结论间的关联

#### 4.3 质量控制
- 每个信号附带**置信度评分**（0-1 范围）
- 多 Agent 交叉验证的信号获得更高置信度
- 冲突信号会触发红蓝队对抗进行裁决

---

### 五、红蓝队对抗机制

红蓝队对抗是本框架的核心创新，通过**辩证分析**揭示产品全貌：

#### 5.1 对抗流程
1. **红队发起**：提出一个批判性论点（如"某功能存在严重缺陷"）
2. **蓝队响应**：提供辩护性论据（如"该设计有特定场景考量"）
3. **交叉质询**：双方进行多轮辩论，检验论据的稳健性
4. **综合裁决**：Elite Agent 综合双方观点，给出平衡结论

#### 5.2 输出格式
```
🔴 红队观点：[批判性分析]
🔵 蓝队回应：[辩护性回应]
⚖️ 综合判断：[平衡结论 + 置信度]
```

#### 5.3 价值
- 避免单一视角的偏见
- 暴露分析中的不确定性
- 帮助决策者理解风险与机遇的平衡

---

### 六、信号验证与置信度体系

所有结论都经过严格的验证流程，并附带置信度评分：

#### 6.1 置信度计算
- **单来源信息**：基础置信度 0.5-0.7
- **交叉验证**：多个独立来源确认，置信度 0.8-0.95
- **官方确认**：来自官方渠道的信息，置信度 0.9-1.0
- **冲突信息**：来源矛盾，置信度降低至 0.3-0.5

#### 6.2 信号衰减
- 信息时效性影响置信度：近期信息权重更高
- 间接来源（如媒体报道）比直接来源（如官方文档）置信度略低

#### 6.3 定量验证（后台处理）
- 对包含量化数据（如用户数、收入、增长率）的信号进行交叉验证
- 不一致的数据会被标记并调整置信度

---

### 七、信息来源与可信度

分析使用的信息来源按可信度分级：

| 等级 | 来源类型 | 示例 | 可信度 |
|-----|---------|------|--------|
| A级 | 官方渠道 | 官网、官方文档、SEC 文件、公告 | 高 |
| B级 | 第三方平台 | 应用商店、SimilarWeb、Crunchbase | 中高 |
| C级 | 行业媒体 | 科技媒体报道、行业分析报告 | 中 |
| D级 | 社区讨论 | 用户评论、论坛讨论、社交媒体 | 中低 |
| E级 | 推测分析 | 基于模式匹配的技术推测 | 低（需标注）|

---

*报告生成时间：请查看元信息中的生成时间。*
*分析框架版本：CompetitorSwarm v1.0*
"""
