"""HTML 可视化报告生成器模块。

生成交互式、现代化的 HTML 报告。
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
        - 支持新的增强格式（战略矩阵、风险/机会矩阵）

        Args:
            result: 编排器结果

        Returns:
            格式化的报告数据
        """
        # 收集各 Agent 的发现
        agent_discoveries = {}
        agent_stats = {}
        total_discovery_count = 0
        agent_source_links: dict[str, list[dict[str, str]]] = {}
        agent_source_hints: dict[str, str] = {}
        elite_report_data: dict[str, Any] = {}

        for agent_type, agent_results in result.agent_results.items():
            if agent_type == "elite":
                continue

            discoveries = []
            for agent_result in agent_results:
                # 统一发现格式：可能是字典或 Discovery 对象
                raw_discoveries = agent_result.discoveries
                if isinstance(raw_discoveries, list):
                    for item in raw_discoveries:
                        normalized = self._normalize_discovery_item(item, agent_type)
                        content = normalized.get("content", "")
                        if content and len(content.strip()) >= 8:  # 过滤过短内容
                            discoveries.append(normalized)
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
        strategic_matrix = []
        risk_opportunity_matrix = []

        if elite_results:
            elite_result = elite_results[0]
            metadata = elite_result.metadata or {}

            # 尝试多个路径获取数据
            report_data = metadata.get("report", {})
            if isinstance(report_data, dict):
                elite_report_data = report_data
            else:
                elite_report_data = {}

            summary = elite_report_data.get("summary", "") or metadata.get("summary", "")

            # 获取洞察（多路径兼容）
            insights = elite_report_data.get("insights", []) or metadata.get("emergent_insights", [])
            # 标准化洞察格式
            insights = self._normalize_insights(insights)

            # 获取建议
            recommendations = elite_report_data.get("recommendations", []) or metadata.get("strategic_recommendations", [])
            # 标准化建议格式
            recommendations = self._normalize_recommendations(recommendations)

            # 获取战略定位矩阵
            strategic_matrix = elite_report_data.get("strategic_matrix", [])
            if not isinstance(strategic_matrix, list):
                strategic_matrix = []

            # 获取风险/机会矩阵
            risk_opportunity_matrix = elite_report_data.get("risk_opportunity_matrix", [])
            if not isinstance(risk_opportunity_matrix, list):
                risk_opportunity_matrix = []

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
        phase_strategy = self._extract_phase_strategy(result)
        quick_read = self._build_quick_read_summary(
            red_points=red_points,
            blue_points=blue_points,
            recommendations=recommendations,
        )
        summary_paragraphs = self._build_summary_paragraphs(
            summary=summary or "暂无摘要。",
            full_analysis=str(elite_report_data.get("full_analysis", "") or ""),
        )
        agent_source_links, agent_source_hints = self._build_agent_source_maps(
            agent_discoveries=agent_discoveries,
            target=result.target or "竞品目标",
        )
        agent_flow = self._build_agent_flow_data(result)

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
            "summary_paragraphs": summary_paragraphs,
            "insights": insights,
            "recommendations": recommendations,
            "red_points": red_points,
            "blue_points": blue_points,
            "phase_strategy": phase_strategy,
            "quick_read": quick_read,
            "strategic_matrix": strategic_matrix,
            "risk_opportunity_matrix": risk_opportunity_matrix,
            "agent_source_links": agent_source_links,
            "agent_source_hints": agent_source_hints,
            "agent_flow": agent_flow,
        }

    def _build_quick_read_summary(
        self,
        red_points: list[str],
        blue_points: list[str],
        recommendations: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        """构建 3 分钟速读摘要。"""
        threats = self._pick_unique_items(red_points, limit=3, max_length=100)
        opportunities = self._pick_unique_items(blue_points, limit=3, max_length=100)

        actions: list[str] = []
        for recommendation in recommendations:
            if not isinstance(recommendation, dict):
                continue
            title = str(recommendation.get("title") or "").strip()
            description = str(
                recommendation.get("description")
                or recommendation.get("content")
                or ""
            ).strip()
            action = f"{title}: {description}" if title and description else (title or description)
            if not action:
                continue
            action = self._truncate_text(action, max_length=110)
            if action not in actions:
                actions.append(action)
            if len(actions) >= 3:
                break

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

        return {
            "threats": threats,
            "opportunities": opportunities,
            "actions": actions[:3],
        }

    def _pick_unique_items(self, items: list[str], limit: int, max_length: int) -> list[str]:
        """按顺序提取去重后的要点列表。"""
        selected: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = " ".join(str(item).split()).strip()
            if not text:
                continue
            text = self._truncate_text(text, max_length=max_length)
            if text in seen:
                continue
            seen.add(text)
            selected.append(text)
            if len(selected) >= limit:
                break
        return selected

    @staticmethod
    def _truncate_text(text: str, max_length: int) -> str:
        """截断文本避免摘要过长。"""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3].rstrip() + "..."

    def _extract_phase_strategy(self, result: CoordinatorResult) -> dict[str, Any]:
        """提取阶段策略摘要。"""
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        phase_progress = metadata.get("phase_progress", {})
        if not isinstance(phase_progress, dict):
            return {}

        phase_metadata = phase_progress.get("phase_metadata", {})
        if not isinstance(phase_metadata, dict):
            return {}

        strategy: dict[str, Any] = {}
        validation = phase_metadata.get("validation")
        if isinstance(validation, dict):
            strategy["validation"] = validation

        debate = phase_metadata.get("debate")
        if isinstance(debate, dict):
            strategy["debate"] = debate

        return strategy

    def _normalize_discovery_item(
        self,
        discovery: Any,
        agent_type: str,
    ) -> dict[str, Any]:
        """标准化发现结构，保留 HTML 渲染所需信息。"""
        content = self._extract_content(discovery)
        source = ""
        timestamp = ""
        confidence: float | None = None
        metadata: dict[str, Any] = {}
        direct_url = ""

        if isinstance(discovery, dict):
            source = str(discovery.get("source") or "")
            timestamp = str(discovery.get("timestamp") or "")
            raw_confidence = discovery.get("confidence")
            if isinstance(raw_confidence, (int, float)):
                confidence = float(raw_confidence)
            raw_metadata = discovery.get("metadata")
            if isinstance(raw_metadata, dict):
                metadata = dict(raw_metadata)
            for key in ("url", "source_url", "link"):
                candidate = discovery.get(key)
                if candidate:
                    direct_url = str(candidate).strip()
                    break
        else:
            raw_source = getattr(discovery, "source", "")
            source = str(getattr(raw_source, "value", raw_source) or "")
            timestamp = str(getattr(discovery, "timestamp", "") or "")
            raw_confidence = getattr(discovery, "confidence", None)
            if isinstance(raw_confidence, (int, float)):
                confidence = float(raw_confidence)
            raw_metadata = getattr(discovery, "metadata", None)
            if isinstance(raw_metadata, dict):
                metadata = dict(raw_metadata)
            for key in ("url", "source_url", "link"):
                candidate = getattr(discovery, key, None)
                if candidate:
                    direct_url = str(candidate).strip()
                    break

        source_url = self._extract_discovery_url(
            direct_url=direct_url,
            metadata=metadata,
            content=content,
        )
        source_hint = self._extract_source_hint(
            content=content,
            source=source,
            metadata=metadata,
        )

        normalized: dict[str, Any] = {
            "content": content,
            "agent_type": agent_type,
            "source": source,
            "timestamp": timestamp,
            "metadata": metadata,
        }
        if confidence is not None:
            normalized["confidence"] = round(confidence, 4)
        if source_url:
            normalized["url"] = source_url
        if source_hint:
            normalized["source_hint"] = source_hint
        return normalized

    def _extract_discovery_url(
        self,
        *,
        direct_url: str = "",
        metadata: dict[str, Any] | None = None,
        content: str = "",
    ) -> str:
        """提取并验证发现 URL。"""
        candidates: list[str] = []

        if direct_url:
            candidates.append(direct_url)

        if isinstance(metadata, dict):
            for key in ("url", "source_url", "link"):
                raw = metadata.get(key)
                if raw:
                    candidates.append(str(raw))

        inline_url = self._extract_url_from_text(content)
        if inline_url:
            candidates.append(inline_url)

        for raw in candidates:
            candidate = str(raw).strip().rstrip(".,;)]")
            if self._is_safe_http_url(candidate):
                return candidate

        return ""

    @staticmethod
    def _is_safe_http_url(value: str) -> bool:
        """仅允许 http/https URL。"""
        if not value:
            return False
        try:
            parsed = urlparse(value)
        except Exception:
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        return bool(parsed.netloc)

    @staticmethod
    def _extract_url_from_text(content: str) -> str:
        """从文本中提取首个 URL。"""
        if not content:
            return ""
        match = re.search(r"https?://[^\s<>'\"]+", str(content))
        if not match:
            return ""
        return match.group(0)

    def _extract_source_hint(
        self,
        *,
        content: str,
        source: str,
        metadata: dict[str, Any],
    ) -> str:
        """提取来源提示词（用于无 URL 时搜索兜底）。"""
        if isinstance(metadata, dict):
            raw_hint = metadata.get("source") or metadata.get("site_name")
            if raw_hint:
                return self._truncate_text(self._clean_markdown_artifacts(str(raw_hint)), 60)

        bracket = re.match(r"^\[([^\]]+)\]", str(content).strip())
        if bracket:
            return self._truncate_text(self._clean_markdown_artifacts(bracket.group(1)), 60)

        if source:
            return self._truncate_text(self._clean_markdown_artifacts(source), 60)

        first_clause = str(content).split("—", 1)[0].split(":", 1)[0]
        cleaned = self._clean_markdown_artifacts(first_clause)
        return self._truncate_text(cleaned, 60) if cleaned else ""

    def _build_agent_source_maps(
        self,
        *,
        agent_discoveries: dict[str, list[dict[str, Any]]],
        target: str,
        max_links_per_agent: int = 5,
    ) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
        """构建每个 Agent 的来源链接和来源提示词。"""
        source_links: dict[str, list[dict[str, str]]] = {}
        source_hints: dict[str, str] = {}

        for agent_type, discoveries in agent_discoveries.items():
            links: list[dict[str, str]] = []
            seen_urls: set[str] = set()
            hint = ""

            for discovery in discoveries:
                if not isinstance(discovery, dict):
                    continue
                if not hint:
                    raw_hint = str(
                        discovery.get("source_hint")
                        or discovery.get("source")
                        or ""
                    ).strip()
                    if raw_hint:
                        hint = self._truncate_text(self._clean_markdown_artifacts(raw_hint), 60)

                raw_url = str(discovery.get("url") or "").strip()
                if not raw_url or raw_url in seen_urls or not self._is_safe_http_url(raw_url):
                    continue

                label = str(
                    discovery.get("source_hint")
                    or discovery.get("source")
                    or self.AGENT_CONFIG.get(agent_type, {}).get("name", agent_type)
                ).strip()
                links.append({
                    "url": raw_url,
                    "label": self._truncate_text(self._clean_markdown_artifacts(label), 80),
                })
                seen_urls.add(raw_url)

                if len(links) >= max_links_per_agent:
                    break

            if not hint:
                fallback_name = self.AGENT_CONFIG.get(agent_type, {}).get("name", agent_type)
                hint = f"{target} {fallback_name}"

            source_links[agent_type] = links
            source_hints[agent_type] = hint

        for agent_type, config in self.AGENT_CONFIG.items():
            source_links.setdefault(agent_type, [])
            source_hints.setdefault(agent_type, f"{target} {config.get('name', agent_type)}")

        return source_links, source_hints

    def _extract_summary_section(self, full_analysis: str) -> str:
        """优先从 full_analysis 中提取“执行摘要”章节。"""
        if not full_analysis:
            return ""

        match = re.search(
            r"##\s*执行摘要\s*([\s\S]*?)(?=\n##\s+|\n=====|$)",
            str(full_analysis),
        )
        if not match:
            return ""
        return match.group(1).strip()

    def _build_summary_paragraphs(
        self,
        *,
        summary: str,
        full_analysis: str = "",
    ) -> list[str]:
        """构建 HTML 执行摘要段落（去 Markdown 噪音）。"""
        raw_summary = self._extract_summary_section(full_analysis) or summary
        cleaned = self._clean_markdown_artifacts(raw_summary)
        if not cleaned:
            return ["暂无摘要。"]

        sentences = [
            chunk.strip()
            for chunk in re.split(r"(?<=[。！？!?])\s+", cleaned)
            if chunk.strip()
        ]
        if not sentences:
            return [cleaned]

        paragraphs: list[str] = []
        current = ""
        for sentence in sentences:
            if not current:
                current = sentence
                continue
            if len(current) + len(sentence) + 1 <= 140:
                current = f"{current} {sentence}"
            else:
                paragraphs.append(current.strip())
                current = sentence
        if current:
            paragraphs.append(current.strip())

        return paragraphs[:4] if paragraphs else [cleaned]

    def _build_agent_flow_data(self, result: CoordinatorResult) -> dict[str, Any]:
        """构建附录中的 Agent 信息传递说明。"""
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        phase_progress = metadata.get("phase_progress", {})
        if not isinstance(phase_progress, dict):
            phase_progress = {}
        phase_metadata = phase_progress.get("phase_metadata", {})
        if not isinstance(phase_metadata, dict):
            phase_metadata = {}

        validation = phase_metadata.get("validation", {})
        if not isinstance(validation, dict):
            validation = {}
        debate = phase_metadata.get("debate", {})
        if not isinstance(debate, dict):
            debate = {}
        synthesis = phase_metadata.get("synthesis", {})
        if not isinstance(synthesis, dict):
            synthesis = {}

        handoff_by_agent: dict[str, int] = {}
        handoff_total = 0
        for agent_type, agent_results in result.agent_results.items():
            agent_handoffs = 0
            for agent_result in agent_results:
                try:
                    agent_handoffs += max(0, int(getattr(agent_result, "handoffs_created", 0) or 0))
                except (TypeError, ValueError):
                    continue
            if agent_handoffs > 0:
                handoff_by_agent[agent_type] = agent_handoffs
                handoff_total += agent_handoffs

        return {
            "stages": [
                {
                    "id": "collection",
                    "title": "Phase 1 信息收集",
                    "mode": "并行独立",
                    "description": "Scout / Experience / Technical / Market 并发采集并写入共享环境。",
                },
                {
                    "id": "validation",
                    "title": "Phase 2 交叉验证",
                    "mode": "交叉校验",
                    "description": "按维度进行验证过滤，提升有效信号置信度并淘汰噪声。",
                },
                {
                    "id": "debate",
                    "title": "Phase 3 红蓝辩论",
                    "mode": "对抗验证",
                    "description": "红蓝队围绕 claim 多轮博弈，形成结构化裁决与信号强度调整。",
                },
                {
                    "id": "synthesis",
                    "title": "Phase 4 报告综合",
                    "mode": "统合输出",
                    "description": "Elite 聚合多源证据、辩论结果与策略信号生成最终报告。",
                },
            ],
            "flow_notes": [
                "Agents 通过 Stigmergy 共享环境间接协作，而非点对点硬编码通信。",
                "信号被引用、验证、辩论后会更新强度，最终由 Elite 汇总。",
                "引用链和辩论 claim 会在 run 内追踪并沉淀为可回溯元数据。",
            ],
            "handoff": {
                "total": handoff_total,
                "by_agent": handoff_by_agent,
            },
            "validation": {
                "verified_count": int(validation.get("verified_count") or 0),
                "filtered_count": int(validation.get("filtered_count") or 0),
            },
            "debate": {
                "rounds": int(debate.get("debate_rounds") or 0),
                "claim_count": int(debate.get("claim_count") or 0),
                "unresolved_claim_count": int(debate.get("unresolved_claim_count") or 0),
                "transcript_id": str(debate.get("debate_transcript_id") or ""),
            },
            "synthesis": {
                "report_generated": bool(synthesis.get("report_generated")),
            },
            "signal": {
                "total_signals": int(metadata.get("total_signals") or 0),
                "total_discoveries": int(metadata.get("total_discoveries") or 0),
            },
        }

    def _clean_markdown_artifacts(self, text: str) -> str:
        """清理 Markdown/表格符号，输出纯叙述文本。"""
        value = str(text or "").strip()
        if not value:
            return ""

        value = value.replace("**", "").replace("__", "").replace("`", "")
        value = value.replace("===== 综合报告 =====", " ")
        value = value.replace("===== 战略建议 =====", " ")
        value = re.sub(r"={3,}\s*[^=\n]*\s*={3,}", " ", value)
        value = re.sub(r"^#+\s*", "", value, flags=re.MULTILINE)
        value = re.sub(r"^\s*\|?\s*-{2,}.*$", " ", value, flags=re.MULTILINE)
        value = re.sub(
            r"^\s*\|.*\|\s*$",
            lambda m: " ".join(
                part.strip()
                for part in m.group(0).strip().strip("|").split("|")
                if part.strip()
            ),
            value,
            flags=re.MULTILINE,
        )
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _normalize_insights(self, insights: list[Any]) -> list[dict[str, Any]]:
        """标准化洞察格式（增强版）。

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
                    "strategic_implication": item.get("strategic_implication", ""),
                    "actionable_direction": item.get("actionable_direction", ""),
                    "evidence_chain": item.get("evidence_chain", []),
                })

        return normalized

    def _normalize_recommendations(self, recommendations: list[Any]) -> list[dict[str, Any]]:
        """标准化建议格式（增强版）。

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
                        "title": "",
                        "priority": "medium",
                        "impact": "待评估",
                        "difficulty": "medium",
                        "roi": "medium",
                        "timeline": "medium",
                        "steps": [],
                        "success_metrics": "",
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
                    "roi": item.get("roi", "medium"),
                    "timeline": item.get("timeline", "medium"),
                    "steps": item.get("steps", []),
                    "success_metrics": item.get("success_metrics", ""),
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
        # 注入数据到 JavaScript。必须转义脚本终止符和特殊分隔符，
        # 避免数据中出现 </script> 或 U+2028/U+2029 导致前端脚本中断。
        data_json = self._serialize_report_data_for_script(data)

        # 读取模板并替换数据
        template = self._get_html_template()

        return template.replace("{{REPORT_DATA}}", data_json)

    def _serialize_report_data_for_script(self, data: dict[str, Any]) -> str:
        """序列化并转义报告数据，确保可安全嵌入 <script>。

        - 将 `<`, `>`, `&` 转义为 unicode，避免闭合标签被 HTML 解析器提前识别。
        - 转义 U+2028/U+2029，避免 JavaScript 解析器将其当作行终止符。
        """
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        return (
            payload
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

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
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@600;700&display=swap');

        :root {
            --paper: #f5f7fb;
            --paper-soft: #eef2f8;
            --card: #ffffff;
            --ink: #162033;
            --muted: #5e6a80;
            --line: #d6deeb;
            --brand: #2b4fc7;
            --brand-soft: #e3ebff;
            --accent-threat: #dd3b49;
            --accent-opportunity: #2f7ef3;
            --accent-action: #10a978;
            --accent-warm: #df8a26;
            --shadow-soft: 0 14px 32px rgba(21, 40, 90, 0.08);
            --bg-primary: var(--paper);
            --bg-secondary: var(--paper-soft);
            --bg-card: var(--card);
            --text-primary: var(--ink);
            --text-secondary: var(--muted);
            --border: var(--line);
            --accent: var(--brand);
            --accent-hover: #1f3eaa;
        }

        .dark {
            --paper: #0d1424;
            --paper-soft: #162138;
            --card: #1a2740;
            --ink: #edf3ff;
            --muted: #a5b5d0;
            --line: #2b3b5c;
            --brand: #8fa8ff;
            --brand-soft: #223665;
            --accent-threat: #f07a85;
            --accent-opportunity: #7fb4ff;
            --accent-action: #59d6ad;
            --accent-warm: #f0ba73;
            --shadow-soft: 0 14px 32px rgba(1, 8, 24, 0.38);
            --bg-primary: var(--paper);
            --bg-secondary: var(--paper-soft);
            --bg-card: var(--card);
            --text-primary: var(--ink);
            --text-secondary: var(--muted);
            --border: var(--line);
            --accent: var(--brand);
            --accent-hover: #9ab0ff;
        }

        * {
            box-sizing: border-box;
            transition: background-color 0.25s ease, color 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
        }

        body {
            margin: 0;
            font-family: 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif;
            background:
                radial-gradient(circle at 12% 12%, rgba(51, 87, 202, 0.08), transparent 26%),
                radial-gradient(circle at 84% 9%, rgba(206, 76, 60, 0.07), transparent 28%),
                var(--paper);
            color: var(--ink);
            font-size: 17px;
            line-height: 1.76;
        }

        body.mobile-nav-open {
            overflow: hidden;
        }

        .text-sm {
            font-size: 1rem !important;
            line-height: 1.7rem !important;
        }

        .text-xs {
            font-size: 0.9rem !important;
            line-height: 1.52rem !important;
        }

        h1, h2, h3, h4 {
            font-family: 'Noto Serif SC', 'Source Han Serif SC', serif;
            letter-spacing: 0.02em;
        }

        code, pre {
            font-family: 'JetBrains Mono', monospace;
        }

        section {
            scroll-margin-top: 1.4rem;
        }

        .card {
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 18px;
            box-shadow: var(--shadow-soft);
        }

        .chapter-title {
            margin-bottom: 1rem;
            font-size: 2rem;
            font-weight: 700;
            line-height: 1.24;
        }

        .chapter-subtitle {
            margin: -0.4rem 0 1.1rem 0;
            color: var(--muted);
            font-size: 0.95rem;
            letter-spacing: 0.01em;
        }

        .insight-card {
            border-left: 5px solid var(--brand);
        }

        .insight-card.high { border-left-color: var(--accent-threat); }
        .insight-card.medium { border-left-color: var(--accent-warm); }
        .insight-card.low { border-left-color: var(--accent-action); }

        .priority-high { color: var(--accent-threat); }
        .priority-medium { color: var(--accent-warm); }
        .priority-low { color: var(--accent-action); }

        .sidebar {
            position: fixed;
            left: 0;
            top: 0;
            bottom: 0;
            width: 276px;
            padding: 1.25rem 1rem 1.5rem;
            background: color-mix(in srgb, var(--card) 92%, var(--paper-soft));
            border-right: 1px solid var(--line);
            overflow-y: auto;
            z-index: 60;
        }

        .sidebar-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 1.4rem;
            padding: 0 0.3rem;
        }

        .sidebar-close {
            display: none;
            border: 1px solid var(--line);
            border-radius: 999px;
            width: 2rem;
            height: 2rem;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
            background: var(--card);
            color: var(--ink);
        }

        .nav-link {
            display: block;
            padding: 0.52rem 0.8rem;
            border-radius: 10px;
            color: var(--muted);
            text-decoration: none;
            font-size: 0.95rem;
        }

        .nav-link:hover {
            background: var(--paper-soft);
            color: var(--ink);
        }

        .nav-link.is-active {
            background: var(--brand-soft);
            color: var(--brand);
            font-weight: 700;
            border: 1px solid color-mix(in srgb, var(--brand) 28%, transparent);
        }

        .main-content {
            margin-left: 276px;
            max-width: 1260px;
            padding: 2rem 1.75rem 3rem;
            margin-right: auto;
        }

        .mobile-nav-overlay {
            position: fixed;
            inset: 0;
            background: rgba(12, 19, 34, 0.38);
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.25s ease;
            z-index: 55;
        }

        .mobile-nav-overlay.open {
            opacity: 1;
            pointer-events: auto;
        }

        .mobile-nav-btn {
            border: 1px solid var(--line);
            background: var(--card);
            border-radius: 999px;
            color: var(--ink);
            padding: 0.5rem 0.95rem;
            font-size: 0.96rem;
            font-weight: 600;
        }

        .summary-paragraph {
            margin-bottom: 1rem;
            line-height: 1.84;
        }

        .summary-paragraph:last-child {
            margin-bottom: 0;
        }

        .narrative-block {
            display: flex;
            flex-direction: column;
            gap: 0.46rem;
            max-width: 100%;
        }

        .narrative-body {
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
            font-size: 1rem;
            line-height: 1.78;
        }

        .line-clamp {
            display: -webkit-box;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: var(--line-clamp, 3);
            overflow: hidden;
        }

        .narrative-block.expanded .line-clamp {
            display: block;
            -webkit-line-clamp: unset;
            overflow: visible;
        }

        .meta-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.38rem;
            align-items: center;
            margin-top: 0.1rem;
        }

        .meta-wrap {
            display: inline-flex;
            flex-wrap: wrap;
            gap: 0.38rem;
            margin-left: 0.35rem;
            vertical-align: middle;
        }

        .meta-chip {
            display: inline-flex;
            align-items: center;
            max-width: 100%;
            color: var(--muted);
            background: color-mix(in srgb, var(--paper-soft) 82%, var(--card));
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 0.08rem 0.58rem;
            font-size: 0.82rem;
            line-height: 1.36rem;
            word-break: break-word;
        }

        .meta-rail {
            display: block;
            margin-top: 0.28rem;
            color: var(--muted);
            font-size: 0.82rem;
            line-height: 1.45rem;
            overflow-wrap: anywhere;
        }

        .collapse-toggle {
            align-self: flex-start;
            border: 0;
            background: transparent;
            color: var(--brand);
            font-size: 0.82rem;
            font-weight: 600;
            padding: 0;
            cursor: pointer;
            text-decoration: underline;
            text-underline-offset: 0.18em;
        }

        .narrative-item {
            border: 1px solid var(--line);
            background: color-mix(in srgb, var(--card) 78%, var(--paper-soft));
            border-radius: 14px;
            padding: 0.82rem 0.95rem;
        }

        .narrative-index {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1.45rem;
            height: 1.45rem;
            border-radius: 999px;
            background: var(--paper-soft);
            color: var(--muted);
            font-size: 0.76rem;
            font-weight: 700;
            margin-right: 0.48rem;
            flex-shrink: 0;
        }

        .debate-stream {
            display: flex;
            flex-direction: column;
            gap: 0.72rem;
        }

        .source-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.34rem;
            padding: 0.15rem 0.56rem;
            border-radius: 999px;
            border: 1px solid var(--line);
            text-decoration: none;
            font-size: 0.82rem;
            line-height: 1.3rem;
            background: var(--paper-soft);
            color: var(--ink);
        }

        .source-badge:hover {
            background: color-mix(in srgb, var(--brand) 16%, var(--paper-soft));
        }

        .dimension-number {
            font-size: 2.1rem;
            font-weight: 700;
            line-height: 1;
        }

        .discovery-tools {
            position: sticky;
            top: 0.85rem;
            z-index: 15;
        }

        .discovery-group {
            margin-bottom: 1rem;
        }

        .discovery-group-header {
            width: 100%;
            border: 1px solid var(--line);
            background: var(--card);
            border-radius: 14px;
            padding: 0.8rem 0.95rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.8rem;
            cursor: pointer;
            text-align: left;
        }

        .discovery-group-body {
            margin-top: 0.6rem;
            display: grid;
            gap: 0.7rem;
        }

        .discovery-group.collapsed .discovery-group-body {
            display: none;
        }

        .group-collapse-icon {
            color: var(--muted);
            font-size: 0.9rem;
        }

        .appendix-grid {
            display: grid;
            grid-template-columns: repeat(1, minmax(0, 1fr));
            gap: 1rem;
        }

        .filter-btn.active {
            background: var(--brand-soft);
            color: var(--brand);
            border-color: color-mix(in srgb, var(--brand) 40%, var(--line));
            font-weight: 700;
        }

        @media (min-width: 1024px) {
            .appendix-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 1023px) {
            .chapter-title {
                font-size: 1.72rem;
            }

            .sidebar {
                transform: translateX(-106%);
                transition: transform 0.25s ease;
            }

            .sidebar.open {
                transform: translateX(0);
            }

            .sidebar-close {
                display: inline-flex;
            }

            .main-content {
                margin-left: 0;
                padding: 1.1rem 0.9rem 2rem;
            }
        }
    </style>
</head>
<body class="antialiased">
    <div id="mobile-nav-overlay" class="mobile-nav-overlay"></div>

    <!-- 侧边导航栏 -->
    <nav id="sidebar" class="sidebar">
        <div class="sidebar-header">
            <div>
                <h1 class="text-xl font-bold" style="color: var(--brand);">CompetitorSwarm</h1>
                <p class="text-sm mt-1" style="color: var(--muted);">竞品分析可视化报告</p>
            </div>
            <button id="mobile-menu-close" class="sidebar-close" aria-label="关闭导航">✕</button>
        </div>

        <nav class="space-y-1">
            <a href="#overview" class="nav-link">📊 概览</a>
            <a href="#quick-read" class="nav-link">⚡ 3 分钟速读</a>
            <a href="#phase-strategy" class="nav-link">🧭 阶段策略</a>
            <a href="#dimensions" class="nav-link">🎯 维度分析</a>
            <a href="#insights" class="nav-link">💡 综合洞察</a>
            <a href="#strategic-matrix" class="nav-link">📊 战略定位</a>
            <a href="#risk-matrix" class="nav-link">⚠️ 风险/机会</a>
            <a href="#recommendations" class="nav-link">📋 可执行建议</a>
            <a href="#debate" class="nav-link">⚔️ 红蓝队对抗</a>
            <a href="#discoveries" class="nav-link">🔍 详细发现</a>
            <a href="#appendix-agent-flow" class="nav-link">📎 附录：Agent 信息传递</a>
        </nav>

        <div class="mt-6">
            <button id="theme-toggle" class="w-full px-4 py-2 rounded-lg border flex items-center justify-center gap-2">
                <span id="theme-icon">🌙</span>
                <span id="theme-text">深色模式</span>
            </button>
        </div>
    </nav>

    <!-- 主内容区 -->
    <main class="main-content">
        <!-- 移动端导航 -->
        <div class="mb-4 lg:hidden">
            <button id="mobile-menu-btn" class="mobile-nav-btn">
                ☰ 导航
            </button>
        </div>

        <!-- 概览卡片 -->
        <section id="overview" class="mb-8">
            <h2 class="chapter-title">📊 分析概览</h2>
            <p class="chapter-subtitle">从全局指标到关键证据，快速把握本次分析的可信结论。</p>

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
                <div id="summary-content" class="max-w-none"></div>
            </div>
        </section>

        <!-- 3 分钟速读 -->
        <section id="quick-read" class="mb-8">
            <h2 class="chapter-title">⚡ 核心洞察（3 分钟速读）</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div class="card p-5" style="border-left: 4px solid var(--accent-threat);">
                    <h3 class="text-lg font-semibold mb-3">⚠️ Top Threat</h3>
                    <ul id="quick-threats" class="space-y-3"></ul>
                </div>
                <div class="card p-5" style="border-left: 4px solid var(--accent-opportunity);">
                    <h3 class="text-lg font-semibold mb-3">🚀 Top Opportunity</h3>
                    <ul id="quick-opportunities" class="space-y-3"></ul>
                </div>
                <div class="card p-5" style="border-left: 4px solid var(--accent-action);">
                    <h3 class="text-lg font-semibold mb-3">✅ Top Actions</h3>
                    <ul id="quick-actions" class="space-y-3"></ul>
                </div>
            </div>
        </section>

        <!-- 阶段策略 -->
        <section id="phase-strategy" class="mb-8">
            <h2 class="chapter-title">🧭 阶段策略摘要</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="card p-6" style="border-left: 4px solid #14b8a6;">
                    <h3 class="text-lg font-semibold mb-4">Phase 2 交叉验证</h3>
                    <div id="phase-validation-content" class="space-y-2 text-sm"></div>
                </div>
                <div class="card p-6" style="border-left: 4px solid #f59e0b;">
                    <h3 class="text-lg font-semibold mb-4">Phase 3 红蓝辩论</h3>
                    <div id="phase-debate-content" class="space-y-2 text-sm"></div>
                </div>
            </div>
        </section>

        <!-- 维度分析 -->
        <section id="dimensions" class="mb-8">
            <h2 class="chapter-title">🎯 维度分析</h2>
            <div id="dimensions-grid" class="grid grid-cols-1 md:grid-cols-2 gap-4"></div>
        </section>

        <!-- 综合洞察 -->
        <section id="insights" class="mb-8">
            <h2 class="chapter-title">💡 综合洞察</h2>
            <div id="insights-container" class="space-y-4"></div>
        </section>

        <!-- 战略定位矩阵 -->
        <section id="strategic-matrix" class="mb-8">
            <h2 class="chapter-title">📊 战略定位矩阵</h2>
            <div id="strategic-matrix-container" class="card p-4 overflow-x-auto"></div>
        </section>

        <!-- 风险/机会矩阵 -->
        <section id="risk-matrix" class="mb-8">
            <h2 class="chapter-title">⚠️ 风险/机会矩阵</h2>
            <div id="risk-matrix-container" class="card p-4 overflow-x-auto"></div>
        </section>

        <!-- 可执行建议 -->
        <section id="recommendations" class="mb-8">
            <h2 class="chapter-title">📋 可执行建议</h2>
            <div id="recommendations-container" class="space-y-4"></div>
        </section>

        <!-- 红蓝队对抗 -->
        <section id="debate" class="mb-8">
            <h2 class="chapter-title">⚔️ 红蓝队对抗</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="card p-6" style="border-left: 4px solid var(--accent-threat);">
                    <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
                        <span>⚔️</span>
                        <span>红队观点</span>
                    </h3>
                    <div id="red-points-container" class="debate-stream"></div>
                </div>
                <div class="card p-6" style="border-left: 4px solid var(--accent-opportunity);">
                    <h3 class="text-lg font-semibold mb-4 flex items-center gap-2">
                        <span>🛡️</span>
                        <span>蓝队观点</span>
                    </h3>
                    <div id="blue-points-container" class="debate-stream"></div>
                </div>
            </div>
        </section>

        <!-- 详细发现 -->
        <section id="discoveries" class="mb-8">
            <h2 class="chapter-title">🔍 详细发现</h2>

            <!-- 筛选器 -->
            <div class="card p-4 mb-4 discovery-tools">
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

        <!-- 附录：Agent 信息传递 -->
        <section id="appendix-agent-flow" class="mb-8">
            <h2 class="chapter-title">📎 附录：Agent 信息传递</h2>
            <div id="agent-flow-container" class="card p-6"></div>
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
            initMobileDrawer();
            renderOverview();
            renderQuickRead();
            renderPhaseStrategy();
            renderDimensions();
            renderInsights();
            renderStrategicMatrix();
            renderRiskMatrix();
            renderRecommendations();
            renderDebate();
            renderDiscoveries();
            renderAgentFlowAppendix();
            initFilters();
            initSmoothScroll();
            initActiveSectionObserver();
            initNarrativeToggle();
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

        function initMobileDrawer() {
            const menuBtn = document.getElementById('mobile-menu-btn');
            const closeBtn = document.getElementById('mobile-menu-close');
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('mobile-nav-overlay');
            if (!menuBtn || !closeBtn || !sidebar || !overlay) {
                return;
            }

            const openDrawer = () => {
                sidebar.classList.add('open');
                overlay.classList.add('open');
                document.body.classList.add('mobile-nav-open');
            };

            const closeDrawer = () => {
                sidebar.classList.remove('open');
                overlay.classList.remove('open');
                document.body.classList.remove('mobile-nav-open');
            };

            menuBtn.addEventListener('click', openDrawer);
            closeBtn.addEventListener('click', closeDrawer);
            overlay.addEventListener('click', closeDrawer);

            document.querySelectorAll('.nav-link').forEach((link) => {
                link.addEventListener('click', () => {
                    if (window.innerWidth < 1024) {
                        closeDrawer();
                    }
                });
            });

            window.addEventListener('resize', () => {
                if (window.innerWidth >= 1024) {
                    closeDrawer();
                }
            });
        }

        function initActiveSectionObserver() {
            const links = Array.from(document.querySelectorAll('.nav-link[href^="#"]'));
            if (!links.length) {
                return;
            }
            const linkMap = new Map();
            const sections = [];
            links.forEach((link) => {
                const targetId = link.getAttribute('href');
                if (!targetId) {
                    return;
                }
                const target = document.querySelector(targetId);
                if (target) {
                    linkMap.set(targetId.slice(1), link);
                    sections.push(target);
                }
            });
            if (!sections.length) {
                return;
            }

            const setActive = (id) => {
                links.forEach((link) => link.classList.remove('is-active'));
                const hit = linkMap.get(id);
                if (hit) {
                    hit.classList.add('is-active');
                }
            };
            setActive(sections[0].id);

            const observer = new IntersectionObserver((entries) => {
                const visible = entries
                    .filter((entry) => entry.isIntersecting)
                    .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
                if (visible.length) {
                    setActive(visible[0].target.id);
                }
            }, {
                root: null,
                rootMargin: '-20% 0px -55% 0px',
                threshold: [0.2, 0.4, 0.65],
            });

            sections.forEach((section) => observer.observe(section));
        }

        function initNarrativeToggle() {
            document.addEventListener('click', (event) => {
                const toggle = event.target.closest('[data-collapse-target]');
                if (!toggle) {
                    return;
                }
                const targetId = toggle.getAttribute('data-collapse-target');
                if (!targetId) {
                    return;
                }
                const host = document.getElementById(targetId);
                if (!host) {
                    return;
                }
                const wrapper = host.closest('.narrative-block');
                const expanded = wrapper?.classList.toggle('expanded');
                toggle.textContent = expanded ? '收起' : '展开';
                toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
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

            // 渲染摘要（HTML 段落化，不使用 Markdown 语法）
            renderSummaryParagraphs(data);

            // 渲染雷达图
            renderRadarChart();
        }

        function renderSummaryParagraphs(data) {
            const summaryContainer = document.getElementById('summary-content');
            if (!summaryContainer) {
                return;
            }

            const rawParagraphs = Array.isArray(data.summary_paragraphs)
                ? data.summary_paragraphs
                : [];
            const paragraphs = rawParagraphs.length > 0
                ? rawParagraphs
                : [data.summary || '暂无摘要。'];

            summaryContainer.innerHTML = paragraphs
                .map((paragraph) => `
                    <div class="summary-paragraph">
                        ${renderNarrativeBlock(String(paragraph), { collapsible: false, maxMeta: 3 })}
                    </div>
                `)
                .join('');
        }

        function renderQuickRead() {
            const data = window.REPORT_DATA;
            const quick = data.quick_read || {};

            const threats = Array.isArray(quick.threats) ? quick.threats : [];
            const opportunities = Array.isArray(quick.opportunities) ? quick.opportunities : [];
            const actions = Array.isArray(quick.actions) ? quick.actions : [];

            const writeList = (containerId, items, fallbackText) => {
                const container = document.getElementById(containerId);
                if (!container) {
                    return;
                }
                const rows = (items.length > 0 ? items : [fallbackText])
                    .map((item, index) => `
                        <li class="narrative-item list-none">
                            <div class="flex items-start gap-2">
                                <span class="narrative-index">${index + 1}</span>
                                <div class="flex-1">${renderNarrativeBlock(String(item), { collapsible: true, lines: 3, maxMeta: 3 })}</div>
                            </div>
                        </li>
                    `)
                    .join('');
                container.innerHTML = rows;
            };

            writeList('quick-threats', threats, '暂无高置信度威胁结论。');
            writeList('quick-opportunities', opportunities, '暂无明确战略机会。');
            writeList('quick-actions', actions, '暂无可执行行动项。');
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

        // 渲染阶段策略摘要
        function renderPhaseStrategy() {
            const data = window.REPORT_DATA;
            const validationContainer = document.getElementById('phase-validation-content');
            const debateContainer = document.getElementById('phase-debate-content');

            if (!validationContainer || !debateContainer) {
                return;
            }

            const strategy = data.phase_strategy || {};
            const validation = strategy.validation || null;
            const debate = strategy.debate || null;

            if (validation && Object.keys(validation).length > 0) {
                const rules = validation.strategy || {};
                let validationHtml = `
                    <p>验证通过: <strong>${validation.verified_count || 0}</strong> 条</p>
                    <p>过滤淘汰: <strong>${validation.filtered_count || 0}</strong> 条</p>
                `;

                if (Object.keys(rules).length > 0) {
                    validationHtml += `
                        <p>阈值配置
                            <span class="meta-wrap">
                                <span class="meta-chip">(confidence ≥ ${rules.min_confidence ?? 'N/A'})</span>
                                <span class="meta-chip">(strength ≥ ${rules.min_strength ?? 'N/A'})</span>
                                <span class="meta-chip">(weighted_score ≥ ${rules.min_weighted_score ?? 'N/A'})</span>
                            </span>
                        </p>
                        <p>维度上限: ${rules.max_signals_per_dimension ?? 'N/A'} 条/维度</p>
                    `;
                }

                const dimensionSummary = validation.dimension_summary || {};
                const dimensionRows = [];
                for (const [dimension, detail] of Object.entries(dimensionSummary)) {
                    if (!detail || typeof detail !== 'object') {
                        continue;
                    }
                    dimensionRows.push(
                        `<li>${escapeHtml(dimension)}: 候选 ${detail.candidate_count || 0} / 通过 ${detail.verified_count || 0} / 过滤 ${detail.filtered_count || 0}</li>`
                    );
                }
                if (dimensionRows.length > 0) {
                    validationHtml += `
                        <div class="mt-2">
                            <p class="font-medium mb-1">维度明细</p>
                            <ul class="list-disc ml-5 space-y-1">
                                ${dimensionRows.join('')}
                            </ul>
                        </div>
                    `;
                }

                validationContainer.innerHTML = validationHtml;
            } else {
                validationContainer.innerHTML = '<p style="color: var(--text-secondary);">暂无交叉验证策略数据</p>';
            }

            if (debate && Object.keys(debate).length > 0) {
                const rules = debate.strategy || {};
                const adjustment = debate.signal_adjustment || {};
                let debateHtml = `
                    <p>辩论轮数: <strong>${debate.debate_rounds || 0}</strong></p>
                    <p>红队观点: <strong>${debate.red_points || 0}</strong> 条</p>
                    <p>蓝队观点: <strong>${debate.blue_points || 0}</strong> 条</p>
                `;

                if (Object.keys(rules).length > 0) {
                    debateHtml += `
                        <p>调整策略
                            <span class="meta-wrap">
                                <span class="meta-chip">(step=${rules.strength_step ?? 'N/A'})</span>
                                <span class="meta-chip">(decay=${rules.round_decay ?? 'N/A'})</span>
                                <span class="meta-chip">(max_adjustment=${rules.max_adjustment ?? 'N/A'})</span>
                                <span class="meta-chip">(verified_only=${String(rules.verified_only ?? 'N/A')})</span>
                            </span>
                        </p>
                    `;
                }

                debateHtml += `
                    <p>信号调整: <strong>${adjustment.adjusted_signals || 0}</strong> 条,
                    总变动 <strong>${adjustment.total_delta || 0}</strong></p>
                `;

                debateContainer.innerHTML = debateHtml;
            } else {
                debateContainer.innerHTML = '<p style="color: var(--text-secondary);">暂无红蓝辩论策略数据</p>';
            }
        }

        // 渲染维度分析
        function renderDimensions() {
            const data = window.REPORT_DATA;
            const container = document.getElementById('dimensions-grid');
            container.innerHTML = '';

            for (const [agentType, stats] of Object.entries(data.agent_stats)) {
                const card = document.createElement('div');
                card.className = 'card p-5';
                card.style.borderTop = `4px solid ${stats.color}`;
                card.dataset.agent = agentType;

                card.innerHTML = `
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-lg font-semibold">${stats.icon} ${stats.name}</p>
                            <p class="text-xs" style="color: var(--muted);">维度观察密度</p>
                        </div>
                        <span class="dimension-number" style="color: ${stats.color}">${stats.count}</span>
                    </div>
                    <p class="text-sm mt-3" style="color: var(--muted);">${stats.count} 条发现</p>
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

                const content = cleanMarkdownArtifacts(insight.content || insight.description || '');
                const strategicImplication = insight.strategic_implication || '';
                const actionableDirection = insight.actionable_direction || '';
                const evidenceChain = insight.evidence_chain || [];
                const sourceLinksByAgent = data.agent_source_links || {};
                const sourceHintsByAgent = data.agent_source_hints || {};

                const valueLabels = {
                    high: '🔴 高战略价值',
                    medium: '🟡 中等战略价值',
                    low: '🟢 低战略价值'
                };

                let cardHtml = `
                    <div class="flex items-start justify-between mb-2">
                        <h4 class="font-semibold">洞察 ${index + 1}</h4>
                        <span class="px-2 py-1 rounded text-xs priority-${strategicValue}">
                            ${valueLabels[strategicValue] || '中等战略价值'}
                        </span>
                    </div>
                    <div class="max-w-none text-sm mb-3">
                        ${renderNarrativeBlock(content, { collapsible: true, lines: 4 })}
                    </div>
                `;

                // 战略含义
                if (strategicImplication) {
                    cardHtml += `
                        <div class="mt-2 p-2 rounded" style="background: var(--paper-soft);">
                            <span class="font-medium text-sm">战略含义：</span>
                            <div class="text-sm">${renderNarrativeBlock(strategicImplication, { collapsible: true, lines: 3 })}</div>
                        </div>
                    `;
                }

                // 可行动方向
                if (actionableDirection) {
                    cardHtml += `
                        <div class="mt-2 p-2 rounded" style="background: var(--paper-soft);">
                            <span class="font-medium text-sm">可行动方向：</span>
                            <div class="text-sm">${renderNarrativeBlock(actionableDirection, { collapsible: true, lines: 3 })}</div>
                        </div>
                    `;
                }

                // 证据链
                if (evidenceChain.length > 0) {
                    const agentVisuals = {
                        scout: { icon: '🔍', name: '侦察' },
                        technical: { icon: '🔬', name: '技术' },
                        market: { icon: '📊', name: '市场' },
                        red_team: { icon: '⚔️', name: '红队' },
                        blue_team: { icon: '🛡️', name: '蓝队' },
                        experience: { icon: '🎨', name: '体验' },
                        elite: { icon: '👑', name: '综合' }
                    };
                    const chainHtml = evidenceChain.map((agentKey) => {
                        const visual = agentVisuals[agentKey] || { icon: '📋', name: agentKey };
                        const sourceItems = Array.isArray(sourceLinksByAgent[agentKey])
                            ? sourceLinksByAgent[agentKey]
                            : [];
                        const sourceItem = sourceItems.length > 0 ? sourceItems[0] : null;
                        const directUrl = sourceItem ? sanitizeUrl(sourceItem.url) : '';
                        const sourceHint = sourceHintsByAgent[agentKey] || sourceItem?.label || visual.name;
                        const href = directUrl || buildSearchFallbackUrl(data.target, agentKey, sourceHint);
                        const title = sourceItem?.label || sourceHint || `${visual.name} 来源`;
                        return `
                            <a class="source-badge"
                               href="${escapeHtml(href)}"
                               target="_blank"
                               rel="noopener noreferrer"
                               title="${escapeHtml(title)}">
                                <span>${visual.icon}</span>
                                <span>${escapeHtml(visual.name)}</span>
                            </a>
                        `;
                    }).join(' ');
                    cardHtml += `
                        <div class="mt-2 flex items-center gap-2 flex-wrap">
                            <span class="text-xs" style="color: var(--text-secondary);">证据来源：</span>
                            ${chainHtml}
                        </div>
                    `;
                }

                card.innerHTML = cardHtml;
                container.appendChild(card);
            });
        }

        // 渲染战略定位矩阵
        function renderStrategicMatrix() {
            const data = window.REPORT_DATA;
            const container = document.getElementById('strategic-matrix-container');

            if (!data.strategic_matrix || data.strategic_matrix.length === 0) {
                container.innerHTML = '<p class="text-sm" style="color: var(--text-secondary);">暂无战略定位数据</p>';
                return;
            }

            let tableHtml = `
                <table class="w-full text-sm">
                    <thead>
                        <tr class="border-b" style="border-color: var(--border);">
                            <th class="text-left p-2">维度</th>
                            <th class="text-left p-2">竞品表现</th>
                            <th class="text-left p-2">我方差距</th>
                            <th class="text-left p-2">战略含义</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            data.strategic_matrix.forEach(row => {
                const perfValue = (row.competitor_performance || '').toLowerCase();
                const gapValue = (row.our_gap || '').toLowerCase();

                const perfClass = perfValue.includes('强') ? 'text-red-500' : (perfValue.includes('弱') ? 'text-green-500' : 'text-yellow-500');
                const gapClass = gapValue.includes('落后') ? 'text-red-500' : (gapValue.includes('领先') ? 'text-green-500' : 'text-yellow-500');

                tableHtml += `
                    <tr class="border-b" style="border-color: var(--border);">
                        <td class="p-2 font-medium">${escapeHtml(row.dimension || '')}</td>
                        <td class="p-2 ${perfClass}">${escapeHtml(row.competitor_performance || '')}</td>
                        <td class="p-2 ${gapClass}">${escapeHtml(row.our_gap || '')}</td>
                        <td class="p-2">${escapeHtml(row.strategic_implication || '')}</td>
                    </tr>
                `;
            });

            tableHtml += '</tbody></table>';
            container.innerHTML = tableHtml;
        }

        // 渲染风险/机会矩阵
        function renderRiskMatrix() {
            const data = window.REPORT_DATA;
            const container = document.getElementById('risk-matrix-container');

            if (!data.risk_opportunity_matrix || data.risk_opportunity_matrix.length === 0) {
                container.innerHTML = '<p class="text-sm" style="color: var(--text-secondary);">暂无风险/机会数据</p>';
                return;
            }

            let tableHtml = `
                <table class="w-full text-sm">
                    <thead>
                        <tr class="border-b" style="border-color: var(--border);">
                            <th class="text-left p-2">类型</th>
                            <th class="text-left p-2">事项</th>
                            <th class="text-left p-2">影响程度</th>
                            <th class="text-left p-2">发生概率</th>
                            <th class="text-left p-2">应对策略</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            data.risk_opportunity_matrix.forEach(row => {
                const isRisk = (row.type || '').includes('风险');
                const typeEmoji = isRisk ? '⚠️' : '🚀';
                const typeClass = isRisk ? 'text-red-500' : 'text-blue-500';

                tableHtml += `
                    <tr class="border-b" style="border-color: var(--border);">
                        <td class="p-2 ${typeClass}">${typeEmoji} ${escapeHtml(row.type || '')}</td>
                        <td class="p-2">${escapeHtml(row.item || '')}</td>
                        <td class="p-2">${escapeHtml(row.impact || '')}</td>
                        <td class="p-2">${escapeHtml(row.probability || '')}</td>
                        <td class="p-2">${escapeHtml(row.strategy || '')}</td>
                    </tr>
                `;
            });

            tableHtml += '</tbody></table>';
            container.innerHTML = tableHtml;
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
                const roi = rec.roi || 'medium';
                const timeline = rec.timeline || 'medium';
                const steps = Array.isArray(rec.steps) ? rec.steps : [];
                const successMetrics = cleanMarkdownArtifacts(rec.success_metrics || '');

                card.className = 'card p-4';

                const title = cleanMarkdownArtifacts(rec.title || `建议 ${index + 1}`);
                const description = cleanMarkdownArtifacts(rec.description || rec.content || '');

                const priorityLabels = {
                    high: '🔴 高优先级',
                    medium: '🟡 中优先级',
                    low: '🟢 低优先级'
                };

                const difficultyLabels = {
                    high: '困难',
                    medium: '中等',
                    low: '简单'
                };

                const roiLabels = {
                    high: '高',
                    medium: '中',
                    low: '低'
                };

                const timelineLabels = {
                    short: '短期(1-3月)',
                    medium: '中期(3-6月)',
                    long: '长期(6-12月)'
                };

                let cardHtml = `
                    <div class="flex items-start justify-between mb-3">
                        <h4 class="font-semibold text-lg">${title}</h4>
                    </div>

                    <!-- 属性表格 -->
                    <table class="w-full text-sm mb-3">
                        <tbody>
                            <tr class="border-b" style="border-color: var(--border);">
                                <td class="p-2 font-medium w-24">优先级</td>
                                <td class="p-2">${priorityLabels[priority] || '中等'}</td>
                                <td class="p-2 font-medium w-24">实施难度</td>
                                <td class="p-2">${difficultyLabels[difficulty] || '中等'}</td>
                            </tr>
                            <tr>
                                <td class="p-2 font-medium">预期 ROI</td>
                                <td class="p-2">${roiLabels[roi] || '中'}</td>
                                <td class="p-2 font-medium">时间线</td>
                                <td class="p-2">${timelineLabels[timeline] || '中期'}</td>
                            </tr>
                        </tbody>
                    </table>
                `;

                // 行动描述
                if (description) {
                    cardHtml += `
                        <div class="mb-3 p-3 rounded" style="background: var(--paper-soft);">
                            <span class="font-medium">行动描述：</span>
                            <div class="mt-1">${renderNarrativeBlock(description, { collapsible: true, lines: 4 })}</div>
                        </div>
                    `;
                }

                // 实施步骤
                if (steps.length > 0) {
                    cardHtml += `
                        <div class="mb-3">
                            <span class="font-medium">实施步骤：</span>
                            <ol class="list-decimal ml-5 mt-2 space-y-1">
                                ${steps.map((s) => `<li class="text-sm">${renderNarrativeBlock(String(s), { collapsible: false, maxMeta: 2 })}</li>`).join('')}
                            </ol>
                        </div>
                    `;
                }

                // 成功指标
                if (successMetrics) {
                    cardHtml += `
                        <div class="p-2 rounded" style="background: color-mix(in srgb, var(--accent-action) 10%, var(--card)); border-left: 3px solid var(--accent-action);">
                            <span class="font-medium text-green-600">成功指标：</span>
                            <div class="text-sm mt-1">${renderNarrativeBlock(successMetrics, { collapsible: true, lines: 3 })}</div>
                        </div>
                    `;
                }

                card.innerHTML = cardHtml;
                container.appendChild(card);
            });
        }

        // 渲染红蓝队对抗
        function renderDebate() {
            const data = window.REPORT_DATA;

            const redContainer = document.getElementById('red-points-container');
            const blueContainer = document.getElementById('blue-points-container');

            if (data.red_points && data.red_points.length > 0) {
                redContainer.innerHTML = data.red_points.slice(0, 12).map((point, index) => `
                    <article class="narrative-item">
                        <div class="flex items-start gap-2">
                            <span class="narrative-index">${index + 1}</span>
                            <div class="flex-1">${renderNarrativeBlock(point, { collapsible: true, lines: 4 })}</div>
                        </div>
                    </article>
                `).join('');
            } else {
                redContainer.innerHTML = '<p class="text-sm" style="color: var(--text-secondary);">暂无红队分析</p>';
            }

            if (data.blue_points && data.blue_points.length > 0) {
                blueContainer.innerHTML = data.blue_points.slice(0, 12).map((point, index) => `
                    <article class="narrative-item">
                        <div class="flex items-start gap-2">
                            <span class="narrative-index">${index + 1}</span>
                            <div class="flex-1">${renderNarrativeBlock(point, { collapsible: true, lines: 4 })}</div>
                        </div>
                    </article>
                `).join('');
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

            const groups = [];
            for (const [agentType, discoveries] of Object.entries(data.agent_discoveries || {})) {
                const config = agentConfig[agentType] || { icon: '📋', name: agentType, color: '#6b7280' };
                const normalized = (Array.isArray(discoveries) ? discoveries : [])
                    .map((discovery) => {
                        const rawContent = typeof discovery === 'string'
                            ? discovery
                            : (discovery.content || discovery.evidence || '');
                        return cleanMarkdownArtifacts(rawContent);
                    })
                    .filter(Boolean);

                if (normalized.length === 0) {
                    continue;
                }

                const groupId = `discoveries-group-${agentType}`;
                const itemHtml = normalized.map((content, index) => `
                    <article class="discovery-item narrative-item" data-agent="${escapeHtml(agentType)}" data-content="${escapeHtml(content.toLowerCase())}">
                        <div class="flex items-start gap-2">
                            <span class="narrative-index">${index + 1}</span>
                            <div class="flex-1">${renderNarrativeBlock(content, { collapsible: true, lines: 4 })}</div>
                        </div>
                    </article>
                `).join('');

                groups.push(`
                    <section class="discovery-group" data-agent-group="${escapeHtml(agentType)}">
                        <button type="button" class="discovery-group-header" data-group-toggle="${escapeHtml(groupId)}">
                            <span class="flex items-center gap-2">
                                <span style="color:${config.color};">${config.icon}</span>
                                <span class="font-semibold">${escapeHtml(config.name)}</span>
                                <span class="text-xs px-2 py-0.5 rounded-full" style="background:${config.color}20; color:${config.color};">
                                    ${normalized.length} 条
                                </span>
                            </span>
                            <span class="group-collapse-icon" id="${escapeHtml(groupId)}-icon">▼</span>
                        </button>
                        <div class="discovery-group-body" id="${escapeHtml(groupId)}">${itemHtml}</div>
                    </section>
                `);
            }

            if (!groups.length) {
                container.innerHTML = '<p class="text-sm text-center" style="color: var(--text-secondary);">暂无发现数据</p>';
                return;
            }

            container.innerHTML = groups.join('');
            container.querySelectorAll('[data-group-toggle]').forEach((button) => {
                button.addEventListener('click', () => {
                    const targetId = button.getAttribute('data-group-toggle');
                    if (!targetId) {
                        return;
                    }
                    const body = document.getElementById(targetId);
                    const icon = document.getElementById(`${targetId}-icon`);
                    const group = button.closest('.discovery-group');
                    if (!body || !group) {
                        return;
                    }
                    group.classList.toggle('collapsed');
                    const collapsed = group.classList.contains('collapsed');
                    if (icon) {
                        icon.textContent = collapsed ? '▶' : '▼';
                    }
                });
            });
        }

        function renderAgentFlowAppendix() {
            const data = window.REPORT_DATA;
            const container = document.getElementById('agent-flow-container');
            if (!container) {
                return;
            }

            const flow = data.agent_flow || {};
            const stages = Array.isArray(flow.stages) ? flow.stages : [];
            const notes = Array.isArray(flow.flow_notes) ? flow.flow_notes : [];

            const validation = flow.validation || {};
            const debate = flow.debate || {};
            const signal = flow.signal || {};
            const handoff = flow.handoff || {};
            const handoffByAgent = handoff.by_agent && typeof handoff.by_agent === 'object'
                ? handoff.by_agent
                : {};

            const agentLabelMap = {
                scout: '侦察',
                experience: '体验',
                technical: '技术',
                market: '市场',
                red_team: '红队',
                blue_team: '蓝队',
                elite: '综合',
            };

            const stageRows = stages.map((stage) => `
                <li>
                    <span class="font-medium">${escapeHtml(stage.title || '')}</span>
                    <span class="meta-wrap">
                        <span class="meta-chip">(${escapeHtml(stage.mode || '未定义')})</span>
                    </span>
                    <div class="text-sm mt-1">${escapeHtml(stage.description || '')}</div>
                </li>
            `).join('');

            const handoffRows = Object.entries(handoffByAgent).map(([agent, count]) => `
                <li>${escapeHtml(agentLabelMap[agent] || agent)}: <strong>${Number(count) || 0}</strong> 次</li>
            `).join('');

            const noteRows = notes.map((note) => `<li>${escapeHtml(String(note))}</li>`).join('');
            const transcript = debate.transcript_id ? `
                <span class="meta-wrap">
                    <span class="meta-chip">(transcript: ${escapeHtml(String(debate.transcript_id))})</span>
                </span>
            ` : '';

            container.innerHTML = `
                <div class="appendix-grid">
                    <div class="p-4 rounded" style="background: var(--bg-secondary); border: 1px solid var(--border);">
                        <h3 class="text-lg font-semibold mb-3">阶段数据流</h3>
                        ${stageRows ? `<ol class="list-decimal ml-5 space-y-3">${stageRows}</ol>` : '<p class="text-sm">暂无阶段信息</p>'}
                    </div>
                    <div class="p-4 rounded" style="background: var(--bg-secondary); border: 1px solid var(--border);">
                        <h3 class="text-lg font-semibold mb-3">Run 级统计</h3>
                        <ul class="space-y-2 text-sm">
                            <li>信号总量: <strong>${Number(signal.total_signals) || 0}</strong></li>
                            <li>发现总量: <strong>${Number(signal.total_discoveries) || 0}</strong></li>
                            <li>验证通过: <strong>${Number(validation.verified_count) || 0}</strong></li>
                            <li>验证过滤: <strong>${Number(validation.filtered_count) || 0}</strong></li>
                            <li>辩论轮数: <strong>${Number(debate.rounds) || 0}</strong></li>
                            <li>Claim 数: <strong>${Number(debate.claim_count) || 0}</strong> ${transcript}</li>
                            <li>未决 Claim: <strong>${Number(debate.unresolved_claim_count) || 0}</strong></li>
                            <li>Handoff 总数: <strong>${Number(handoff.total) || 0}</strong></li>
                        </ul>
                        <div class="mt-3">
                            <p class="text-sm font-medium mb-1">Handoff 明细</p>
                            ${handoffRows ? `<ul class="list-disc ml-5 text-sm space-y-1">${handoffRows}</ul>` : '<p class="text-sm" style="color: var(--text-secondary);">本次 run 无 handoff 记录</p>'}
                        </div>
                    </div>
                </div>
                <div class="mt-4 p-4 rounded" style="background: var(--bg-secondary); border: 1px solid var(--border);">
                    <h3 class="text-lg font-semibold mb-2">协作机制说明</h3>
                    ${noteRows ? `<ul class="list-disc ml-5 text-sm space-y-1">${noteRows}</ul>` : '<p class="text-sm">暂无补充说明</p>'}
                </div>
            `;
        }

        // 初始化筛选器
        function initFilters() {
            const filterBtns = document.querySelectorAll('.filter-btn');
            const searchInput = document.getElementById('search-input');
            if (!filterBtns.length || !searchInput) {
                return;
            }

            filterBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    filterBtns.forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    applyFilters();
                });
            });

            searchInput.addEventListener('input', applyFilters);
            applyFilters();

            function applyFilters() {
                const activeFilter = document.querySelector('.filter-btn.active').dataset.filter;
                const searchTerm = searchInput.value.toLowerCase();
                const discoveries = document.querySelectorAll('.discovery-item');

                discoveries.forEach((card) => {
                    const agent = card.dataset.agent || '';
                    const content = card.dataset.content || '';

                    const matchesFilter = activeFilter === 'all' || agent === activeFilter;
                    const matchesSearch = !searchTerm || content.includes(searchTerm);

                    card.style.display = matchesFilter && matchesSearch ? 'block' : 'none';
                });

                document.querySelectorAll('.discovery-group').forEach((group) => {
                    const items = Array.from(group.querySelectorAll('.discovery-item'));
                    const visibleCount = items.filter((item) => item.style.display !== 'none').length;
                    group.style.display = visibleCount > 0 ? 'block' : 'none';
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

        function cleanMarkdownArtifacts(text) {
            if (!text) {
                return '';
            }
            return String(text)
                .replace(/\\*\\*(.+?)\\*\\*/g, '$1')
                .replace(/__(.+?)__/g, '$1')
                .replace(/`([^`]+)`/g, '$1')
                .replace(/^#{1,6}\\s+/gm, '')
                .replace(/^\\s*\\|?\\s*-{2,}.*$/gm, ' ')
                .replace(/^\\s*\\|.*\\|\\s*$/gm, (line) => line.replace(/\\|/g, ' '))
                .replace(/={3,}\\s*[^=\\n]*\\s*={3,}/g, ' ')
                .replace(/\\s+/g, ' ')
                .trim();
        }

        let narrativeIdSeed = 0;

        function truncateTextClient(text, maxLength) {
            if (!text || text.length <= maxLength) {
                return text || '';
            }
            return `${text.slice(0, maxLength - 1).trim()}…`;
        }

        function splitNarrativeAndMeta(text) {
            const cleaned = cleanMarkdownArtifacts(text);
            if (!cleaned) {
                return { narrative: '', metaItems: [], extra: '' };
            }

            const metaItems = [];
            const extraParts = [];
            const pushMeta = (key, value) => {
                const normalizedKey = cleanMarkdownArtifacts(String(key || '')).trim();
                const normalizedValue = cleanMarkdownArtifacts(String(value || '')).trim();
                if (!normalizedKey || !normalizedValue) {
                    return;
                }
                metaItems.push({ key: normalizedKey, value: normalizedValue });
            };

            let narrative = cleaned.replace(/^\\[[^\\]]+\\]\\s*/, '').trim();
            const segments = narrative.split(/\\s+—\\s+/).map((s) => cleanMarkdownArtifacts(s)).filter(Boolean);
            if (segments.length > 1) {
                narrative = segments[0];
                segments.slice(1).forEach((segment) => {
                    const match = segment.match(/^(时间|置信度|来源可靠性|可信度|来源|可利用度)\\s*[:：]\\s*(.+)$/);
                    if (match) {
                        pushMeta(match[1], match[2]);
                    } else {
                        extraParts.push(segment);
                    }
                });
            }

            const inlineMetaPattern = /(时间|置信度|来源可靠性|可信度|来源|可利用度)\\s*[:：]\\s*([^；;，,]+)/g;
            let inlineMatch;
            while ((inlineMatch = inlineMetaPattern.exec(narrative)) !== null) {
                pushMeta(inlineMatch[1], inlineMatch[2]);
            }
            narrative = narrative.replace(inlineMetaPattern, ' ').replace(/\\s+/g, ' ').trim();
            if (!narrative) {
                narrative = cleaned;
            }

            const dedupMap = new Map();
            metaItems.forEach((item) => {
                const dedupKey = `${item.key}:${item.value}`;
                if (!dedupMap.has(dedupKey)) {
                    dedupMap.set(dedupKey, item);
                }
            });
            const dedupMeta = Array.from(dedupMap.values());

            const compactMeta = [];
            dedupMeta.forEach((item) => {
                if (item.key === '来源' && item.value.length > 48) {
                    extraParts.push(`${item.key}: ${item.value}`);
                } else {
                    compactMeta.push(item);
                }
            });

            const extra = cleanMarkdownArtifacts(extraParts.join('； '));
            return {
                narrative,
                metaItems: compactMeta.slice(0, 4),
                extra: truncateTextClient(extra, 200),
            };
        }

        function renderNarrativeBlock(text, options = {}) {
            const parsed = splitNarrativeAndMeta(text);
            const narrative = parsed.narrative || '';
            if (!narrative) {
                return '';
            }

            const collapsible = options.collapsible === true;
            const lineCount = Number(options.lines || 4);
            const collapseThreshold = Number(options.threshold || 92);
            const maxMeta = Number(options.maxMeta || 4);
            const metaItems = Array.isArray(parsed.metaItems) ? parsed.metaItems.slice(0, maxMeta) : [];
            const needsToggle = collapsible && narrative.length > collapseThreshold;
            const blockId = `narrative-${++narrativeIdSeed}`;

            const bodyClass = needsToggle ? 'narrative-body line-clamp' : 'narrative-body';
            const bodyStyle = needsToggle ? ` style="--line-clamp:${lineCount};"` : '';
            const metaHtml = metaItems.length
                ? `<div class="meta-row">${metaItems.map((item) => `<span class="meta-chip">(${escapeHtml(item.key)}: ${escapeHtml(item.value)})</span>`).join('')}</div>`
                : '';
            const extraHtml = parsed.extra
                ? `<div class="meta-rail" title="${escapeHtml(parsed.extra)}">${escapeHtml(parsed.extra)}</div>`
                : '';
            const toggleHtml = needsToggle
                ? `<button class="collapse-toggle" data-collapse-target="${blockId}" aria-expanded="false">展开</button>`
                : '';

            return `
                <div class="narrative-block${needsToggle ? '' : ' expanded'}">
                    <div id="${blockId}" class="${bodyClass}"${bodyStyle}>${escapeHtml(narrative)}</div>
                    ${metaHtml}
                    ${extraHtml}
                    ${toggleHtml}
                </div>
            `;
        }

        function renderNarrativeLine(text) {
            const parsed = splitNarrativeAndMeta(text);
            if (!parsed.narrative) {
                return '';
            }
            const chips = (parsed.metaItems || [])
                .map((item) => `<span class="meta-chip">(${escapeHtml(item.key)}: ${escapeHtml(item.value)})</span>`)
                .join('');
            const extraChip = parsed.extra
                ? `<span class="meta-chip">(${escapeHtml(truncateTextClient(parsed.extra, 60))})</span>`
                : '';
            if (!chips && !extraChip) {
                return escapeHtml(parsed.narrative);
            }
            return `${escapeHtml(parsed.narrative)}<span class="meta-wrap">${chips}${extraChip}</span>`;
        }

        function sanitizeUrl(rawUrl) {
            if (!rawUrl) {
                return '';
            }
            try {
                const parsed = new URL(String(rawUrl).trim());
                if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                    return parsed.toString();
                }
            } catch (error) {
                return '';
            }
            return '';
        }

        function buildSearchFallbackUrl(target, agentKey, sourceHint) {
            const query = [target, agentKey, sourceHint]
                .map((item) => String(item || '').trim())
                .filter(Boolean)
                .join(' ');
            return `https://duckduckgo.com/?q=${encodeURIComponent(query || 'competitor analysis source')}`;
        }

        // 保留旧方法供兼容调用
        function formatMarkdown(text) {
            return cleanMarkdownArtifacts(text).replace(/\\n/g, '<br>');
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
