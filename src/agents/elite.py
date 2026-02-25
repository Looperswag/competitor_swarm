"""精英 Agent 模块。

负责综合所有发现，生成深度洞察和可执行建议。
"""

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.agents.base import BaseAgent, AgentType, AgentResult, DiscoverySource
from src.analysis.motif_miner import MotifMiner


@dataclass
class NormalizedDiscovery:
    """兼容 signals 与 legacy discovery 的统一结构。"""

    id: str
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
        self._reset_runtime_diagnostics()
        target = context.get("target", "")

        if not target:
            return AgentResult(
                agent_type=self.agent_type.value,
                agent_name=self.name,
                discoveries=[],
                handoffs_created=0,
                metadata=self._augment_metadata({"error": "No target specified"}),
            )

        # 第一步：获取搜索上下文
        search_context = self._get_search_context(target)
        if search_context:
            context["_search_context"] = search_context
        debate_claims = context.get("debate_claims", [])
        if not isinstance(debate_claims, list):
            debate_claims = []
        debate_transcript_id = str(context.get("debate_transcript_id") or "").strip()

        # 第二步：收集所有发现
        all_discoveries = self._collect_all_discoveries()

        # 第三步：生成综合报告 + 战略建议（合并为一次 LLM 调用以减少延迟）
        report, strategic_recommendations = self._generate_report_and_recommendations(
            target, all_discoveries, context, bool(search_context)
        )

        # 第四步：提取涌现洞察（包含报告中提取的增强洞察）
        enhanced_insights = report.get("enhanced_insights", [])
        emergent_insights, insight_trace = self._extract_emergent_insights(
            target,
            all_discoveries,
            bool(search_context),
            debate_claims=debate_claims,
            report_enhanced_insights=enhanced_insights,
        )
        emergence_trace_id = f"emergence-{uuid4().hex[:12]}"
        pheromone_score = self._estimate_insight_pheromone_score(emergent_insights)

        # 第六步：存储综合发现
        discoveries = self._store_elite_discoveries(
            target, report, emergent_insights, strategic_recommendations
        )

        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[d.to_dict() for d in discoveries],
            handoffs_created=0,
            metadata=self._augment_metadata({
                "target": target,
                "report": {
                    **report,
                    "insights": emergent_insights,  # 确保数据路径匹配
                    "recommendations": strategic_recommendations,  # 同时添加建议
                    "insight_trace": insight_trace,
                },
                "emergent_insights": emergent_insights,  # 保留向后兼容
                "insight_trace": insight_trace,
                "strategic_recommendations": strategic_recommendations,
                "total_discoveries_analyzed": len(all_discoveries),
                "search_used": bool(search_context),
                "debate_transcript_id": debate_transcript_id or None,
                "emergence_trace_id": emergence_trace_id,
                "pheromone_score": round(pheromone_score, 4),
            }),
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

    def _generate_report_and_recommendations(
        self,
        target: str,
        discoveries: list[Any],
        context: dict[str, Any],
        has_search: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """一次 LLM 调用同时生成综合报告和战略建议。

        将原先 _generate_comprehensive_report + _generate_strategic_recommendations
        合并为一次调用，减少串行 LLM 延迟（节省约 8-20s）。

        支持新的增强格式输出。

        Args:
            target: 目标产品
            discoveries: 所有发现
            context: 执行上下文
            has_search: 是否有搜索结果

        Returns:
            (结构化报告, 战略建议列表)
        """
        by_agent = self._group_discoveries_by_agent(discoveries)

        # 高价值发现用于战略建议
        high_value_discoveries = [
            d for d in discoveries if d.quality_score > 0.7
        ][:20]

        search_note = "\n已结合最新市场动态进行分析。" if has_search else ""

        prompt = f"""请对「{target}」进行综合分析，整合所有维度的发现，并生成战略建议。

已有分析维度：
"""
        for agent_type, agent_discoveries in by_agent.items():
            prompt += f"\n- {agent_type}: {len(agent_discoveries)} 条发现"

        prompt += f"""
{search_note}

高价值发现：
{self._format_high_value_discoveries(high_value_discoveries)}

===== 第一部分：综合报告 =====

请生成一份综合报告，严格按照以下格式：

## 执行摘要
[3-5 句话，点明核心威胁、关键机会、主要战场]

## 战略定位矩阵
| 维度 | 竞品表现 | 我方差距 | 战略含义 |
|------|---------|---------|---------|
| 产品功能 | [强/中/弱] | [领先/持平/落后] | [一句话解读] |
| 用户体验 | [强/中/弱] | [领先/持平/落后] | [一句话解读] |
| 技术能力 | [强/中/弱] | [领先/持平/落后] | [一句话解读] |
| 市场份额 | [强/中/弱] | [领先/持平/落后] | [一句话解读] |

## 关键矛盾与结论
[明确"谁对/谁错/为何"，定义核心战场与不作为风险]

## 核心发现
- [agent_type] [发现内容]（来源：xxx，置信度：高/中/低）

## 风险/机会矩阵
| 类型 | 事项 | 影响程度 | 发生概率 | 应对策略 |
|------|------|---------|---------|---------|
| 风险/机会 | [具体事项] | 高/中/低 | 高/中/低 | [一句话] |

===== 第二部分：战略建议 =====

基于以上分析，生成 3-5 条具体的战略建议，每条建议必须包含属性表格：

## 建议 1：[标题]

| 属性 | 值 |
|------|-----|
| 优先级 | 高/中/低 |
| 实施难度 | 简单/中等/困难 |
| 预期 ROI | 高/中/低 |
| 时间线 | 短期(1-3月)/中期(3-6月)/长期(6-12月) |

**行动描述**：[2-3 句话描述具体行动]

**实施步骤**：
1. [步骤 1]
2. [步骤 2]

**成功指标**：[可量化的 KPI]

## 风险与假设
[关键假设和潜在风险]

重要：
1. 请用 "===== 战略建议 =====" 分隔报告和建议两部分
2. 每条建议必须有属性表格
3. 核心发现必须标注来源 Agent 如 [scout]、[red_team]
"""

        response = self.think(
            prompt,
            {
                "_discoveries": self._format_discoveries_summary(by_agent),
                **context,
            },
        )

        # 分割响应为报告和建议两部分
        report_text, recommendations_text = self._split_report_and_recommendations(response)

        # 解析增强格式的建议
        recommendations = self._parse_enhanced_recommendations(recommendations_text)
        if not recommendations:
            recommendations = self._parse_recommendations(recommendations_text)

        # 解析增强格式的洞察
        enhanced_insights = self._parse_enhanced_insights(report_text)

        # 提取战略定位矩阵
        strategic_matrix = self._extract_strategic_matrix(report_text)

        # 提取风险/机会矩阵
        risk_opportunity_matrix = self._extract_risk_opportunity_matrix(report_text)

        report = {
            "summary": self._extract_summary(report_text),
            "full_analysis": report_text,
            "discovery_count": {
                agent_type: len(agent_discoveries)
                for agent_type, agent_discoveries in by_agent.items()
            },
            "strategic_matrix": strategic_matrix,
            "risk_opportunity_matrix": risk_opportunity_matrix,
            "enhanced_insights": enhanced_insights,
        }

        return report, recommendations

    def _extract_strategic_matrix(self, report_text: str) -> list[dict[str, str]]:
        """从报告中提取战略定位矩阵。

        Args:
            report_text: 报告文本

        Returns:
            战略定位矩阵数据列表
        """
        matrix = []

        matrix_match = re.search(
            r'##\s*战略定位矩阵\s*\n([\s\S]*?)(?=\n##|\n=====|$)',
            report_text
        )
        if not matrix_match:
            return matrix

        matrix_text = matrix_match.group(1)

        for line in matrix_text.split("\n"):
            if line.strip().startswith("|") and "维度" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                parts = [p for p in parts if p]
                if len(parts) >= 4:
                    matrix.append({
                        "dimension": parts[0],
                        "competitor_performance": parts[1] if len(parts) > 1 else "",
                        "our_gap": parts[2] if len(parts) > 2 else "",
                        "strategic_implication": parts[3] if len(parts) > 3 else "",
                    })

        return matrix

    def _extract_risk_opportunity_matrix(self, report_text: str) -> list[dict[str, str]]:
        """从报告中提取风险/机会矩阵。

        Args:
            report_text: 报告文本

        Returns:
            风险/机会矩阵数据列表
        """
        matrix = []

        matrix_match = re.search(
            r'##\s*风险[/／]机会矩阵\s*\n([\s\S]*?)(?=\n##|\n=====|$)',
            report_text
        )
        if not matrix_match:
            return matrix

        matrix_text = matrix_match.group(1)

        for line in matrix_text.split("\n"):
            if line.strip().startswith("|") and "类型" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")]
                parts = [p for p in parts if p]
                if len(parts) >= 5:
                    matrix.append({
                        "type": parts[0],
                        "item": parts[1],
                        "impact": parts[2],
                        "probability": parts[3],
                        "strategy": parts[4],
                    })

        return matrix

    def _split_report_and_recommendations(self, response: str) -> tuple[str, str]:
        """将合并响应拆分为报告和建议两部分。

        Args:
            response: LLM 完整响应

        Returns:
            (报告文本, 建议文本)
        """
        # 尝试按分隔标记拆分
        separators = ["===== 战略建议 =====", "战略建议", "## 战略建议", "### 战略建议"]
        for sep in separators:
            if sep in response:
                parts = response.split(sep, 1)
                return parts[0].strip(), parts[1].strip()

        # 兜底：如果没有明确分隔符，查找最后一组以 "- " 开头的连续行作为建议
        lines = response.split("\n")
        last_bullet_start = -1
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].strip()
            if stripped.startswith("- ") or stripped.startswith("• "):
                last_bullet_start = i
            elif last_bullet_start != -1 and stripped:
                # 找到了非空非列表行，说明列表从 last_bullet_start 开始
                break

        if last_bullet_start > 0:
            # 往前找连续的列表项起点
            bullet_start = last_bullet_start
            for i in range(last_bullet_start - 1, -1, -1):
                stripped = lines[i].strip()
                if stripped.startswith("- ") or stripped.startswith("• "):
                    bullet_start = i
                elif stripped == "":
                    continue
                else:
                    break

            report_text = "\n".join(lines[:bullet_start]).strip()
            rec_text = "\n".join(lines[bullet_start:]).strip()
            return report_text, rec_text

        # 最终兜底：整个响应都当作报告，建议为空
        return response, ""

    def _extract_emergent_insights(
        self,
        target: str,
        discoveries: list[Any],
        has_search: bool = False,
        *,
        debate_claims: list[dict[str, Any]] | None = None,
        report_enhanced_insights: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """提取涌现洞察。

        使用多轮策略生成洞察：
        0. 基于图模式（Convergence/Tension/Bridge）的结构化洞察
        1. 从报告中提取的增强洞察
        2. 基于高频关键词的自动洞察
        3. 基于跨维度引用的关联洞察
        4. 基于 LLM 综合的深度洞察

        Args:
            target: 目标产品
            discoveries: 所有发现
            has_search: 是否有搜索结果
            debate_claims: 辩论阶段结构化 claim 列表
            report_enhanced_insights: 从报告中提取的增强洞察

        Returns:
            (涌现洞察列表, 洞察追溯链)
        """
        all_insights = []
        motif_traces: list[dict[str, Any]] = []

        # 优先使用从报告中提取的增强洞察
        if report_enhanced_insights:
            all_insights.extend(report_enhanced_insights)

        motif_insights, motif_traces = MotifMiner(self._environment).mine(
            claims=debate_claims or [],
            limit=3,
        )
        if motif_insights:
            all_insights.extend(motif_insights)

        # 第一步：基于高频关键词生成洞察
        if len(all_insights) < 5:
            keyword_insights = self._generate_keyword_based_insights(target, discoveries)
            all_insights.extend(keyword_insights)

        # 第二步：基于语义关联生成洞察
        if len(all_insights) < 5:
            semantic_insights = self._generate_semantic_insights(target, discoveries, has_search)
            all_insights.extend(semantic_insights)

        # 第三步：如果有足够发现，生成深度综合洞察
        if len(discoveries) >= 10 and len(all_insights) < 5:
            deep_insights = self._generate_deep_insights(target, discoveries, has_search)
            all_insights.extend(deep_insights)

        # 去重并限制数量
        unique_insights = self._deduplicate_insights(all_insights)
        selected_insights = unique_insights[:5]
        selected_trace_ids = {
            str(insight.get("trace_id") or "").strip()
            for insight in selected_insights
            if isinstance(insight, dict)
        }
        if selected_trace_ids:
            motif_traces = [
                trace for trace in motif_traces
                if str(trace.get("trace_id") or "").strip() in selected_trace_ids
            ]
        return selected_insights, motif_traces

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
            item_id = self._extract_id(item)
            agent_type = self._extract_agent_type(item)
            content = self._extract_content(item)
            if not content:
                continue
            quality_score = self._extract_quality_score(item)
            metadata = self._extract_metadata(item)

            normalized.append(NormalizedDiscovery(
                id=item_id,
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

    def _extract_id(self, item: Any) -> str:
        """提取或生成唯一 ID。"""
        if isinstance(item, dict):
            return str(item.get("id") or item.get("signal_id") or uuid4().hex)
        if hasattr(item, "id"):
            return str(getattr(item, "id"))
        return uuid4().hex

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

    def _estimate_insight_pheromone_score(self, insights: list[dict[str, Any]]) -> float:
        """估算本次洞察集合对应的信息素强度。"""
        scores: list[float] = []
        for insight in insights:
            raw_score = insight.get("pheromone_score")
            try:
                if raw_score is not None:
                    scores.append(max(0.0, min(1.0, float(raw_score))))
                    continue
            except (TypeError, ValueError):
                pass

            evidence_signal_ids = insight.get("evidence_signal_ids", [])
            if not isinstance(evidence_signal_ids, list):
                continue
            for signal_id in evidence_signal_ids:
                sid = str(signal_id).strip()
                if not sid:
                    continue
                scores.append(self._environment.get_signal_pheromone_value(sid))

        if not scores:
            return 0.0
        return sum(scores) / len(scores)

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
            content = insight.get("description") or insight.get("content") or ""
            if content:
                insight_discovery = self.add_discovery(
                    content=f"[涌现洞察] {content}",
                    source=DiscoverySource.ANALYSIS,
                    quality_score=0.95,
                    metadata={
                        "type": "emergent_insight",
                        "target": target,
                        "dimensions": insight.get("dimensions", []),
                        "significance": insight.get("significance", insight.get("strategic_value", "")),
                        "motif_type": insight.get("motif_type"),
                        "trace_id": insight.get("trace_id"),
                        "evidence_signal_ids": insight.get("evidence_signal_ids", []),
                        "evidence_claim_ids": insight.get("evidence_claim_ids", []),
                        "phase_trace": insight.get("phase_trace", []),
                        "pheromone_score": insight.get("pheromone_score"),
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
        """解析建议响应（增强版）。

        支持两种格式：
        1. 新格式：带属性表格的建议块
        2. 旧格式：简单列表项

        Args:
            response: LLM 响应

        Returns:
            建议列表
        """
        # 首先尝试解析增强格式
        enhanced_recommendations = self._parse_enhanced_recommendations(response)
        if enhanced_recommendations:
            return enhanced_recommendations

        # 回退到简单格式解析
        recommendations = []
        lines = response.split("\n")

        for line in lines:
            line = line.strip()
            if line.startswith("- ") or line.startswith("• "):
                content = line[2:].strip()
                if len(content) > 20:
                    recommendations.append({
                        "description": content[:200],
                        "priority": "medium",
                        "impact": "待评估",
                        "difficulty": "medium",
                    })

        return recommendations[:10]  # 最多 10 条建议

    def _parse_enhanced_recommendations(self, response: str) -> list[dict[str, Any]]:
        """解析增强格式的建议。

        支持格式：
        ## 建议 1：[标题]
        | 属性 | 值 |
        |------|-----|
        | 优先级 | 高/中/低 |
        ...

        Args:
            response: LLM 响应

        Returns:
            增强格式建议列表
        """
        recommendations = []

        # 按 "## 建议" 分割
        recommendation_blocks = re.split(r'##\s*建议\s*\d*[：:]', response)

        for block in recommendation_blocks[1:]:  # 跳过第一个（分隔前的内容）
            rec = self._parse_single_enhanced_recommendation(block)
            if rec:
                recommendations.append(rec)

        return recommendations[:10]

    def _parse_single_enhanced_recommendation(self, block: str) -> dict[str, Any] | None:
        """解析单个增强格式建议。

        Args:
            block: 单个建议的文本块

        Returns:
            解析后的建议字典，或 None
        """
        lines = block.strip().split("\n")
        if not lines:
            return None

        # 第一行是标题
        title = lines[0].strip()

        rec: dict[str, Any] = {
            "title": title,
            "description": "",
            "priority": "medium",
            "difficulty": "medium",
            "roi": "medium",
            "timeline": "medium",
            "steps": [],
            "success_metrics": "",
        }

        current_section = ""
        in_table = False
        table_content = []

        for line in lines[1:]:
            stripped = line.strip()

            # 检测属性表格
            if stripped.startswith("|") and "|" in stripped[1:]:
                in_table = True
                table_content.append(stripped)
                continue
            elif in_table and not stripped.startswith("|"):
                # 表格结束
                in_table = False
                self._parse_attribute_table(table_content, rec)
                table_content = []

            # 检测章节标题
            if stripped.startswith("**行动描述**") or stripped.startswith("行动描述"):
                current_section = "description"
                continue
            elif stripped.startswith("**实施步骤**") or stripped.startswith("实施步骤"):
                current_section = "steps"
                continue
            elif stripped.startswith("**成功指标**") or stripped.startswith("成功指标"):
                current_section = "metrics"
                continue

            # 解析内容
            if current_section == "description" and stripped:
                rec["description"] += (" " if rec["description"] else "") + stripped
            elif current_section == "steps" and stripped:
                # 解析编号步骤
                step_match = re.match(r'^\d+[\.\、]\s*(.+)', stripped)
                if step_match:
                    rec["steps"].append(step_match.group(1))
                elif stripped.startswith("- "):
                    rec["steps"].append(stripped[2:])
            elif current_section == "metrics" and stripped:
                rec["success_metrics"] = stripped

        # 处理未完成的表格
        if table_content:
            self._parse_attribute_table(table_content, rec)

        # 清理描述
        rec["description"] = rec["description"].strip()[:500]

        return rec if rec.get("title") or rec.get("description") else None

    def _parse_attribute_table(self, table_lines: list[str], rec: dict[str, Any]) -> None:
        """解析属性表格并填充建议字典。

        Args:
            table_lines: 表格行列表
            rec: 建议字典（会被修改）
        """
        for line in table_lines:
            # 跳过分隔行
            if re.match(r'^\|[-:\s|]+\|$', line):
                continue

            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]  # 移除空元素

            if len(parts) >= 2:
                key = parts[0].lower()
                value = parts[1].lower()

                if "优先级" in key or "priority" in key:
                    rec["priority"] = self._normalize_priority(value)
                elif "难度" in key or "difficulty" in key:
                    rec["difficulty"] = self._normalize_difficulty(value)
                elif "roi" in key or "收益" in key:
                    rec["roi"] = self._normalize_value(value)
                elif "时间" in key or "timeline" in key:
                    rec["timeline"] = self._normalize_timeline(value)

    def _normalize_priority(self, value: str) -> str:
        """标准化优先级。"""
        if "高" in value or "high" in value:
            return "high"
        elif "低" in value or "low" in value:
            return "low"
        return "medium"

    def _normalize_difficulty(self, value: str) -> str:
        """标准化难度。"""
        if "简单" in value or "低" in value or "easy" in value or "low" in value:
            return "low"
        elif "困难" in value or "高" in value or "hard" in value or "high" in value:
            return "high"
        return "medium"

    def _normalize_value(self, value: str) -> str:
        """标准化 ROI/价值。"""
        if "高" in value or "high" in value:
            return "high"
        elif "低" in value or "low" in value:
            return "low"
        return "medium"

    def _normalize_timeline(self, value: str) -> str:
        """标准化时间线。"""
        if "短期" in value or "short" in value or "1-3" in value:
            return "short"
        elif "长期" in value or "long" in value or "6-12" in value:
            return "long"
        return "medium"

    def _parse_enhanced_insights(self, response: str) -> list[dict[str, Any]]:
        """解析增强格式的洞察。

        支持从报告中提取洞察，包括：
        - 战略定位矩阵
        - 关键矛盾与结论
        - 核心发现中的洞察

        Args:
            response: LLM 响应（综合报告部分）

        Returns:
            增强格式洞察列表
        """
        insights = []

        # 提取关键矛盾与结论作为洞察
        contradiction_match = re.search(
            r'##\s*关键矛盾与结论\s*\n([\s\S]*?)(?=\n##|\n=====|$)',
            response
        )
        if contradiction_match:
            content = contradiction_match.group(1).strip()
            if content and len(content) > 50:
                insights.append({
                    "content": content[:500],
                    "strategic_value": "high",
                    "strategic_implication": "这是核心战略矛盾，需要重点关注",
                    "actionable_direction": "基于此矛盾制定差异化策略",
                    "evidence_chain": ["elite"],
                })

        # 从核心发现中提取洞察
        findings_match = re.search(
            r'##\s*核心发现\s*\n([\s\S]*?)(?=\n##|\n=====|$)',
            response
        )
        if findings_match:
            findings_text = findings_match.group(1)
            # 提取带 Agent 标签的发现
            agent_findings = re.findall(
                r'-\s*\[([a-z_]+)\]\s*([^\n]+)',
                findings_text
            )
            for agent, content in agent_findings[:5]:
                if len(content) > 30:
                    insights.append({
                        "content": content[:300],
                        "strategic_value": "medium",
                        "strategic_implication": "",
                        "actionable_direction": "",
                        "evidence_chain": [agent],
                    })

        # 提取战略定位矩阵
        matrix_match = re.search(
            r'##\s*战略定位矩阵\s*\n([\s\S]*?)(?=\n##|\n=====|$)',
            response
        )
        if matrix_match:
            matrix_text = matrix_match.group(1)
            # 解析表格行
            for line in matrix_text.split("\n"):
                if line.strip().startswith("|") and "维度" not in line and "---" not in line:
                    parts = [p.strip() for p in line.split("|")]
                    parts = [p for p in parts if p]
                    if len(parts) >= 4:
                        dimension = parts[0]
                        strategic_meaning = parts[3] if len(parts) > 3 else ""
                        if strategic_meaning and len(strategic_meaning) > 10:
                            insights.append({
                                "content": f"{dimension}维度：{strategic_meaning}",
                                "strategic_value": "medium",
                                "strategic_implication": strategic_meaning,
                                "actionable_direction": "",
                                "evidence_chain": ["elite"],
                            })

        return insights[:10]  # 最多 10 个洞察
