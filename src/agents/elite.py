"""精英 Agent 模块。

负责综合所有发现，生成深度洞察和可执行建议。
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from src.agents.base import BaseAgent, AgentType, AgentResult, DiscoverySource


@dataclass
class NormalizedDiscovery:
    """兼容 signals 与 legacy discovery 的统一结构。"""

    agent_type: str
    content: str
    quality_score: float
    metadata: dict[str, Any]


class EliteAgent(BaseAgent):
    """精英 Agent。

    整合多维发现，提取涌现洞察，生成最终报告。
    支持在线搜索以获取最新的行业趋势和竞品动态。
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化精英 Agent。"""
        super().__init__(
            agent_type=AgentType.ELITE,
            name="综合分析专家",
            **kwargs,
        )

    def execute(self, **context: Any) -> AgentResult:
        """执行综合分析任务。

        Args:
            **context: 执行上下文，应包含：
                - target: 目标产品/公司名称

        Returns:
            Agent 执行结果（包含结构化报告）
        """
        target = context.get("target", "")

        if not target:
            return AgentResult(
                agent_type=self.agent_type.value,
                agent_name=self.name,
                discoveries=[],
                handoffs_created=0,
                metadata={"error": "No target specified"},
            )

        # 第一步：获取搜索上下文
        search_context = self._get_search_context(target)
        if search_context:
            context["_search_context"] = search_context

        # 第二步：收集所有发现
        all_discoveries = self._collect_all_discoveries()

        # 第三步：生成综合报告
        report = self._generate_comprehensive_report(
            target, all_discoveries, context, bool(search_context)
        )

        # 第四步：提取涌现洞察
        emergent_insights = self._extract_emergent_insights(
            target, all_discoveries, bool(search_context)
        )

        # 第五步：生成战略建议
        strategic_recommendations = self._generate_strategic_recommendations(
            target, all_discoveries, report
        )

        # 第六步：存储综合发现
        discoveries = self._store_elite_discoveries(
            target, report, emergent_insights, strategic_recommendations
        )

        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[d.to_dict() for d in discoveries],
            handoffs_created=0,
            metadata={
                "target": target,
                "report": {
                    **report,
                    "insights": emergent_insights,  # 确保数据路径匹配
                    "recommendations": strategic_recommendations,  # 同时添加建议
                },
                "emergent_insights": emergent_insights,  # 保留向后兼容
                "strategic_recommendations": strategic_recommendations,
                "total_discoveries_analyzed": len(all_discoveries),
                "search_used": bool(search_context),
            },
        )

    def _get_search_context(self, target: str) -> str:
        """获取搜索上下文。

        Args:
            target: 目标产品

        Returns:
            搜索上下文字符串
        """
        queries = [
            f"{target} 最新动态 新闻",
            f"{target} 行业趋势",
            f"{target} 发展前景",
        ]

        context_parts = []
        for query in queries:
            result = self.search_context(query, max_results=5)
            if result:
                context_parts.append(f"## 搜索结果: {query}\n{result}")

        return "\n\n".join(context_parts) if context_parts else ""

    def _generate_comprehensive_report(
        self,
        target: str,
        discoveries: list[Any],
        context: dict[str, Any],
        has_search: bool = False,
    ) -> dict[str, Any]:
        """生成综合报告。

        Args:
            target: 目标产品
            discoveries: 所有发现
            context: 执行上下文
            has_search: 是否有搜索结果

        Returns:
            结构化报告
        """
        # 按维度分组发现
        by_agent = self._group_discoveries_by_agent(discoveries)

        # 构建综合分析提示
        prompt = self._build_synthesis_prompt(
            target, by_agent, has_search
        )

        # 执行综合分析
        response = self.think(
            prompt,
            {
                "_discoveries": self._format_discoveries_summary(by_agent),
                **context,
            },
        )

        return {
            "summary": self._extract_summary(response),
            "full_analysis": response,
            "discovery_count": {
                agent_type: len(agent_discoveries)
                for agent_type, agent_discoveries in by_agent.items()
            },
        }

    def _extract_emergent_insights(
        self,
        target: str,
        discoveries: list[Any],
        has_search: bool = False,
    ) -> list[dict[str, Any]]:
        """提取涌现洞察。

        使用多轮策略生成洞察：
        1. 基于高频关键词的自动洞察
        2. 基于跨维度引用的关联洞察
        3. 基于 LLM 综合的深度洞察

        Args:
            target: 目标产品
            discoveries: 所有发现
            has_search: 是否有搜索结果

        Returns:
            涌现洞察列表
        """
        all_insights = []

        # 第一步：基于高频关键词生成洞察
        keyword_insights = self._generate_keyword_based_insights(target, discoveries)
        all_insights.extend(keyword_insights)

        # 第二步：基于语义关联生成洞察
        semantic_insights = self._generate_semantic_insights(target, discoveries, has_search)
        all_insights.extend(semantic_insights)

        # 第三步：如果有足够发现，生成深度综合洞察
        if len(discoveries) >= 10:
            deep_insights = self._generate_deep_insights(target, discoveries, has_search)
            all_insights.extend(deep_insights)

        # 去重并限制数量
        unique_insights = self._deduplicate_insights(all_insights)
        return unique_insights[:5]

    def _collect_all_discoveries(self) -> list[NormalizedDiscovery]:
        """收集并规范化所有发现，兼容 signals 与 legacy discoveries。"""
        if getattr(self._environment, "signal_count", 0) > 0 and self.USE_SIGNALS:
            raw_items = self._environment.all_signals
        else:
            raw_items = self._environment.all_discoveries

        return self._normalize_discoveries(raw_items)

    def _normalize_discoveries(self, items: list[Any]) -> list[NormalizedDiscovery]:
        """将不同格式的发现统一为 NormalizedDiscovery。"""
        normalized: list[NormalizedDiscovery] = []

        for item in items:
            agent_type = self._extract_agent_type(item)
            content = self._extract_content(item)
            if not content:
                continue
            quality_score = self._extract_quality_score(item)
            metadata = self._extract_metadata(item)

            normalized.append(NormalizedDiscovery(
                agent_type=agent_type,
                content=content,
                quality_score=quality_score,
                metadata=metadata,
            ))

        return normalized

    def _extract_agent_type(self, item: Any) -> str:
        if isinstance(item, dict):
            return item.get("agent_type") or item.get("author_agent") or item.get("agent") or "unknown"
        if hasattr(item, "agent_type"):
            return getattr(item, "agent_type")
        if hasattr(item, "author_agent"):
            return getattr(item, "author_agent")
        return "unknown"

    def _extract_content(self, item: Any) -> str:
        if isinstance(item, dict):
            return (item.get("content") or item.get("evidence") or "").strip()
        if hasattr(item, "content"):
            return str(getattr(item, "content", "")).strip()
        if hasattr(item, "evidence"):
            return str(getattr(item, "evidence", "")).strip()
        return str(item).strip()

    def _extract_quality_score(self, item: Any) -> float:
        if isinstance(item, dict):
            return float(
                item.get("quality_score")
                or item.get("strength")
                or item.get("confidence")
                or 0.5
            )
        if hasattr(item, "quality_score"):
            return float(getattr(item, "quality_score", 0.5))
        if hasattr(item, "strength"):
            return float(getattr(item, "strength", 0.5))
        if hasattr(item, "confidence"):
            return float(getattr(item, "confidence", 0.5))
        return 0.5

    def _extract_metadata(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item.get("metadata", {}) or {}
        return getattr(item, "metadata", {}) or {}

    def _generate_keyword_based_insights(
        self,
        target: str,
        discoveries: list[Any],
    ) -> list[dict[str, Any]]:
        """基于高频关键词生成洞察。"""
        import re
        from collections import Counter

        # 提取所有关键词
        all_keywords = []
        for discovery in discoveries:
            # 英文单词
            english = re.findall(r'\b[a-zA-Z]{4,}\b', discovery.content.lower())
            # 中文词汇
            chinese = re.findall(r'[\u4e00-\u9fff]{2,}', discovery.content)
            all_keywords.extend(english + chinese)

        # 统计高频词
        keyword_counts = Counter(all_keywords)

        # 过滤常见词
        stop_words = {
            "产品", "功能", "用户", "可以", "应该", "可能", "the", "this", "that",
            "with", "from", "have", "will", "market", "analysis", "feature",
        }

        top_keywords = [
            kw for kw, count in keyword_counts.most_common(10)
            if kw not in stop_words and count >= 2
        ]

        if not top_keywords:
            return []

        # 基于高频词生成洞察
        insights = []
        for keyword in top_keywords[:3]:
            # 找到包含该关键词的高质量发现
            related = [
                d for d in discoveries
                if keyword.lower() in d.content.lower() and d.quality_score > 0.5
            ][:5]

            if len(related) >= 2:
                # 按维度分组
                by_agent = {}
                for d in related:
                    if d.agent_type not in by_agent:
                        by_agent[d.agent_type] = []
                    by_agent[d.agent_type].append(d)

                if len(by_agent) >= 2:
                    dimensions = list(by_agent.keys())
                    insights.append({
                        "content": f"「{keyword}」是 {target} 的核心关注点，在 {len(related)} 条发现中被提及。"
                                   f"这表明 {keyword} 对产品的战略重要性。",
                        "dimensions": dimensions,
                        "evidence": [d.content[:100] for d in related[:3]],
                        "strategic_value": "medium",
                        "source": "keyword_analysis",
                    })

        return insights

    def _generate_semantic_insights(
        self,
        target: str,
        discoveries: list[Any],
        has_search: bool,
    ) -> list[dict[str, Any]]:
        """基于语义关联生成洞察。"""
        from src.analysis.semantic_linker import SemanticLinker

        linker = SemanticLinker(self._llm_client)
        cross_dimension_links = linker.find_cross_dimension_links(
            discoveries,
            min_similarity=0.2,  # 降低阈值
            max_links_per_agent_pair=5,
            top_per_agent=10,
        )

        if not cross_dimension_links:
            return []

        # 格式化关联为提示词
        links_context = linker.format_links_for_prompt(cross_dimension_links, max_links=5)

        search_note = "\n已提供最新市场动态作为参考。" if has_search else ""

        prompt = f"""基于以下跨维度的语义关联发现，提取关于「{target}」的涌现洞察。
{search_note}

涌现洞察是指：通过关联不同维度的发现，得到任何单一维度都无法得出的深度理解。

{links_context}

请提取 1-2 个最重要的涌现洞察，以 JSON 格式输出：
[
  {{
    "content": "洞察描述（150字+）",
    "dimensions": ["agent1", "agent2"],
    "strategic_value": "high/medium/low"
  }}
]
"""

        response = self.think(prompt)
        return self._parse_insights_with_json(response)

    def _generate_deep_insights(
        self,
        target: str,
        discoveries: list[Any],
        has_search: bool,
    ) -> list[dict[str, Any]]:
        """生成深度综合洞察。"""
        # 按维度分组
        by_agent = self._group_discoveries_by_agent(discoveries)

        # 只使用高质量发现
        high_quality = []
        for agent_type, agent_discoveries in by_agent.items():
            top = sorted(agent_discoveries, key=lambda d: d.quality_score, reverse=True)[:3]
            high_quality.extend(top)

        if len(high_quality) < 5:
            return []

        summary_text = "\n".join([
            f"[{d.agent_type}] {d.content[:150]}"
            for d in high_quality[:10]
        ])

        prompt = f"""基于以下高质量发现，生成关于「{target}」的深度战略洞察。

{summary_text}

请提供 1-2 个洞察，重点关注：
1. 跨维度的矛盾或张力
2. 隐藏的机会或风险
3. 战略级别的结论

以 JSON 格式输出：
[
  {{
    "content": "洞察描述",
    "strategic_value": "high"
  }}
]
"""

        response = self.think(prompt)
        return self._parse_insights_with_json(response)

    def _deduplicate_insights(
        self,
        insights: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """去重洞察。"""
        seen = set()
        unique = []

        for insight in insights:
            # 使用内容的前50个字符作为指纹
            content = insight.get("content", "")
            fingerprint = content[:50].strip().lower()

            if fingerprint and fingerprint not in seen:
                seen.add(fingerprint)
                unique.append(insight)

        return unique

    def _generate_strategic_recommendations(
        self,
        target: str,
        discoveries: list[Any],
        report: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """生成战略建议。

        Args:
            target: 目标产品
            discoveries: 所有发现
            report: 综合报告

        Returns:
            战略建议列表
        """
        # 按优先级分组发现
        high_value_discoveries = [
            d for d in discoveries
            if d.quality_score > 0.7
        ][:20]

        prompt = f"""基于对「{target}」的全面分析，生成可执行的战略建议。

综合分析摘要：
{report.get('summary', '')}

高价值发现：
{self._format_high_value_discoveries(high_value_discoveries)}

请生成 5-8 条具体的战略建议，每条建议包括：
1. 建议描述：具体的行动建议
2. 优先级：高/中/低
3. 预期效果：实施后的预期收益
4. 实施难度：简单/中等/困难

以结构化格式输出，每条建议单独一行，以「- 」开头。
"""

        response = self.think(prompt)

        return self._parse_recommendations(response)

    def _store_elite_discoveries(
        self,
        target: str,
        report: dict[str, Any],
        insights: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
    ) -> list[Any]:
        """存储精英 Agent 的发现。

        Args:
            target: 目标产品
            report: 综合报告
            insights: 涌现洞察
            recommendations: 战略建议

        Returns:
            发现列表
        """
        discoveries = []

        # 存储摘要
        if report["summary"]:
            summary_discovery = self.add_discovery(
                content=f"综合分析摘要：{report['summary']}",
                source=DiscoverySource.ANALYSIS,
                quality_score=0.9,
                metadata={"type": "summary", "target": target},
            )
            discoveries.append(summary_discovery)

        # 存储涌现洞察
        for insight in insights:
            content = insight.get("description", "")
            if content:
                insight_discovery = self.add_discovery(
                    content=f"[涌现洞察] {content}",
                    source=DiscoverySource.ANALYSIS,
                    quality_score=0.95,
                    metadata={
                        "type": "emergent_insight",
                        "target": target,
                        "dimensions": insight.get("dimensions", []),
                        "significance": insight.get("significance", ""),
                    },
                )
                discoveries.append(insight_discovery)

        # 存储战略建议
        for rec in recommendations:
            content = rec.get("description", "")
            if content:
                rec_discovery = self.add_discovery(
                    content=f"[战略建议] {content}",
                    source=DiscoverySource.ANALYSIS,
                    quality_score=0.85,
                    metadata={
                        "type": "recommendation",
                        "target": target,
                        "priority": rec.get("priority", ""),
                        "impact": rec.get("impact", ""),
                        "difficulty": rec.get("difficulty", ""),
                    },
                )
                discoveries.append(rec_discovery)

        return discoveries

    def _group_discoveries_by_agent(self, discoveries: list[Any]) -> dict[str, list[Any]]:
        """按 Agent 类型分组发现。

        Args:
            discoveries: 所有发现

        Returns:
            分组的发现
        """
        grouped: dict[str, list[Any]] = {}

        for discovery in discoveries:
            agent_type = discovery.agent_type
            if agent_type not in grouped:
                grouped[agent_type] = []
            grouped[agent_type].append(discovery)

        return grouped

    def _build_synthesis_prompt(
        self,
        target: str,
        by_agent: dict[str, list[Any]],
        has_search: bool = False,
    ) -> str:
        """构建综合分析提示词。

        Args:
            target: 目标产品
            by_agent: 分组的发现
            has_search: 是否有搜索结果

        Returns:
            提示词
        """
        prompt = f"""请对「{target}」进行综合分析，整合所有维度的发现。

已有分析维度：
"""

        for agent_type, discoveries in by_agent.items():
            prompt += f"\n- {agent_type}: {len(discoveries)} 条发现"

        search_note = "\n已结合最新市场动态进行分析。" if has_search else ""
        prompt += f"""
{search_note}
请生成一份综合报告，包括：

1. **执行摘要**（3-5 句话）：最核心的发现和结论
2. **维度整合**：各维度之间的一致性和矛盾点
3. **红蓝队观点对比**：识别共识点和争议点
4. **竞争定位**：在竞争格局中的位置
5. **核心发现**：3-5 条最重要的发现

请以清晰、结构化的方式输出。
"""

        return prompt

    def _format_discoveries_summary(self, by_agent: dict[str, list[Any]]) -> str:
        """格式化发现摘要。

        Args:
            by_agent: 分组的发现

        Returns:
            格式化的摘要
        """
        parts = []

        for agent_type, discoveries in by_agent.items():
            if not discoveries:
                continue

            parts.append(f"\n## {agent_type} 分析\n")

            # 只显示高质量发现
            top_discoveries = sorted(
                discoveries, key=lambda d: d.quality_score, reverse=True
            )[:5]

            for discovery in top_discoveries:
                parts.append(f"- {discovery.content}\n")

        return "\n".join(parts)

    def _format_cross_agent_insights(self, insights: list[dict[str, Any]]) -> str:
        """格式化跨 Agent 洞察。

        Args:
            insights: 跨 Agent 洞察

        Returns:
            格式化的洞察
        """
        if not insights:
            return "暂无跨维度关联"

        lines = []
        for insight in insights[:10]:  # 最多显示 10 条
            lines.append(
                f"- {insight['from_agent']} → {', '.join(insight['referenced_by'])}: "
                f"{insight['content']} (被引用 {insight['reference_count']} 次)"
            )

        return "\n".join(lines)

    def _format_high_value_discoveries(self, discoveries: list[Any]) -> str:
        """格式化高价值发现。

        Args:
            discoveries: 高价值发现列表

        Returns:
            格式化的发现
        """
        return "\n".join([f"- {d.content}" for d in discoveries[:20]])

    def _extract_summary(self, response: str) -> str:
        """从响应中提取摘要。

        Args:
            response: LLM 响应

        Returns:
            摘要内容
        """
        # 简单实现：取前 500 字作为摘要
        lines = response.split("\n")
        summary_lines = []

        for line in lines:
            line = line.strip()
            if line and len(line) > 10:
                summary_lines.append(line)
                if len(summary_lines) >= 5:
                    break

        return " ".join(summary_lines)[:500]

    def _parse_insights(self, response: str) -> list[dict[str, Any]]:
        """解析洞察响应（保留向后兼容）。

        Args:
            response: LLM 响应

        Returns:
            洞察列表
        """
        # 简单实现：按段落分割
        paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]

        insights = []
        for para in paragraphs[:5]:  # 最多 5 个洞察
            insights.append({
                "description": para[:300],
                "dimensions": ["multiple"],
                "significance": "high",
            })

        return insights

    def _parse_insights_with_json(self, response: str) -> list[dict[str, Any]]:
        """解析洞察响应，优先解析 JSON 格式。

        Args:
            response: LLM 响应

        Returns:
            洞察列表
        """
        # 尝试提取 JSON 代码块
        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response, re.DOTALL)
        if json_match:
            try:
                insights = json.loads(json_match.group(1))
                if isinstance(insights, list):
                    return self._normalize_insights(insights)
            except json.JSONDecodeError:
                pass

        # 尝试直接解析 JSON（无代码块）
        try:
            stripped = response.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                insights = json.loads(stripped)
                if isinstance(insights, list):
                    return self._normalize_insights(insights)
        except json.JSONDecodeError:
            pass

        # 尝试提取非标准格式的 JSON（可能在其他位置）
        array_match = re.search(r'\[\s*\{[^\]]*\}\s*\]', response, re.DOTALL)
        if array_match:
            try:
                insights = json.loads(array_match.group(0))
                if isinstance(insights, list):
                    return self._normalize_insights(insights)
            except json.JSONDecodeError:
                pass

        # 备用：使用 markdown 列表格式解析
        return self._parse_insights_from_markdown(response)

    def _normalize_insights(self, insights: list[Any]) -> list[dict[str, Any]]:
        """标准化洞察格式。

        Args:
            insights: 原始洞察列表

        Returns:
            标准化的洞察列表
        """
        normalized = []

        for insight in insights:
            if not isinstance(insight, dict):
                continue

            normalized.append({
                "description": insight.get("content", insight.get("description", ""))[:500],
                "content": insight.get("content", insight.get("description", ""))[:500],
                "dimensions": insight.get("dimensions", ["multiple"]),
                "evidence": insight.get("evidence", []),
                "strategic_value": insight.get("strategic_value", insight.get("significance", "medium")),
            })

        return normalized[:5]  # 最多 5 个洞察

    def _parse_insights_from_markdown(self, response: str) -> list[dict[str, Any]]:
        """从 Markdown 列表格式解析洞察。

        Args:
            response: LLM 响应

        Returns:
            洞察列表
        """
        insights = []
        lines = response.split("\n")

        current_insight: dict[str, Any] = {}

        for line in lines:
            line = line.strip()

            # 检测新的洞察开始
            if line.startswith(("##", "###", "洞察", "1.", "2.", "3.", "4.", "5.")):
                if current_insight:
                    insights.append(current_insight)
                current_insight = {"content": "", "dimensions": ["multiple"], "strategic_value": "medium"}
            elif line.startswith("-") and current_insight:
                # 可能是证据列表
                if "evidence" not in current_insight:
                    current_insight["evidence"] = []
                current_insight["evidence"].append(line[1:].strip())
            elif line and current_insight:
                # 累积内容
                if current_insight["content"]:
                    current_insight["content"] += " "
                current_insight["content"] += line

        if current_insight and current_insight.get("content"):
            insights.append(current_insight)

        # 标准化格式
        return self._normalize_insights(insights)

    def _parse_recommendations(self, response: str) -> list[dict[str, Any]]:
        """解析建议响应。

        Args:
            response: LLM 响应

        Returns:
            建议列表
        """
        recommendations = []
        lines = response.split("\n")

        for line in lines:
            line = line.strip()
            if line.startswith("- ") or line.startswith("• "):
                content = line[2:].strip()
                if len(content) > 20:
                    recommendations.append({
                        "description": content[:200],
                        "priority": "中",
                        "impact": "待评估",
                        "difficulty": "中等",
                    })

        return recommendations[:10]  # 最多 10 条建议
