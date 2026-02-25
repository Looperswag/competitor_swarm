"""PM 可读版 Markdown 报告转换器。

将 HTML/JSON 可视化数据导出为面向产品经理的可读 Markdown 报告。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ConversionStats:
    """转换统计信息。"""

    filtered_promotional_items: int = 0


class PMMarkdownConverter:
    """将 JSON 报告转换为可读 Markdown。"""

    AGENT_ORDER = ["scout", "experience", "technical", "market", "red_team", "blue_team"]
    AGENT_NAME = {
        "scout": "侦察",
        "experience": "体验",
        "technical": "技术",
        "market": "市场",
        "red_team": "红队",
        "blue_team": "蓝队",
    }
    SIDE_NAME = {"red": "红方", "blue": "蓝方"}
    VERDICT_NAME = {"SUPPORTED": "成立", "REFUTED": "被反驳", "UNCERTAIN": "待定"}

    def __init__(self) -> None:
        self.stats = ConversionStats()

    def convert_file(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        readable: bool = True,
    ) -> str:
        """将 JSON 文件转换为 Markdown 文件。"""
        source_path = Path(input_path)
        with source_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("JSON 顶层结构必须是对象")

        markdown = self.convert_data(data, readable=readable)

        if output_path is None:
            output_file = source_path.with_name(f"{source_path.stem}_readable.md")
        else:
            output_file = Path(output_path)

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(markdown, encoding="utf-8")
        return str(output_file)

    def convert_data(self, data: dict[str, Any], *, readable: bool = True) -> str:
        """将 JSON 数据转换为可读 Markdown。"""
        # 当前仅支持可读输出，保留参数以兼容 CLI 选项。
        _ = readable
        self.stats = ConversionStats()

        target = self._clean_text(str(data.get("target") or "未知目标"))
        timestamp = self._clean_text(str(data.get("timestamp") or ""))
        total_discoveries = int(data.get("total_discoveries") or 0)

        lines: list[str] = [
            f"# {target} 竞品分析（可读版）",
            "",
            "- 报告类型：PM 可直接阅读版本",
            f"- 数据时间：{timestamp or '未知'}",
            f"- 发现总数：{total_discoveries}",
            "",
        ]

        self._append_one_page_conclusion(lines, data)
        self._append_strategic_conclusion(lines, data)
        self._append_strategic_positioning(lines, data)
        self._append_risk_and_opportunity(lines, data)
        self._append_full_process(lines, data)
        self._append_filter_notes(lines)

        return "\n".join(lines).strip() + "\n"

    def _append_one_page_conclusion(self, lines: list[str], data: dict[str, Any]) -> None:
        lines.extend(["## 一页结论（先看这里）", ""])

        quick_read = data.get("quick_read", {}) if isinstance(data.get("quick_read"), dict) else {}
        threats = self._clean_items(quick_read.get("threats", []))
        opportunities = self._clean_items(quick_read.get("opportunities", []))

        recommendation_source = self._extract_recommendation_texts(data.get("recommendations", []))
        actions = self._clean_items(recommendation_source[:3])
        if not actions:
            actions = self._clean_items(quick_read.get("actions", []))

        if not threats:
            threats = self._clean_items(data.get("red_points", []), limit=3)
        if not opportunities:
            opportunities = self._clean_items(data.get("blue_points", []), limit=3)

        lines.extend(["### 核心威胁", ""])
        if threats:
            for item in threats[:3]:
                lines.append(f"- {self._format_fact_line(item)}")
        else:
            lines.append("- 暂无高置信度威胁结论。")

        lines.extend(["", "### 核心机会", ""])
        if opportunities:
            for item in opportunities[:3]:
                lines.append(f"- {self._format_fact_line(item)}")
        else:
            lines.append("- 暂无明确战略机会。")

        lines.extend(["", "### 建议优先动作", ""])
        if actions:
            for item in actions[:3]:
                lines.append(f"- {self._format_fact_line(item)}")
        else:
            lines.append("- 暂无可执行动作。")
        lines.append("")

    def _append_strategic_conclusion(self, lines: list[str], data: dict[str, Any]) -> None:
        lines.extend(["## 战略结论", ""])
        summary = self._clean_summary(str(data.get("summary") or ""))
        if summary:
            lines.append(summary)
        else:
            lines.append("暂无可用战略结论。")
        lines.append("")

    def _append_strategic_positioning(self, lines: list[str], data: dict[str, Any]) -> None:
        lines.extend(["## 战略定位（文本化）", ""])
        matrix = data.get("strategic_matrix", [])
        if not isinstance(matrix, list) or not matrix:
            lines.append("- 暂无战略定位矩阵数据。")
            lines.append("")
            return

        for item in matrix:
            if not isinstance(item, dict):
                continue
            dimension = self._clean_text(str(item.get("dimension") or "未知维度"))
            competitor = self._clean_text(str(item.get("competitor_performance") or "未知"))
            gap = self._clean_text(str(item.get("our_gap") or "未知"))
            implication = self._clean_text(str(item.get("strategic_implication") or "暂无说明"))
            lines.append(
                f"- {dimension}：竞品表现 {competitor}；我方差距 {gap}；战略含义 {implication}"
            )
        lines.append("")

    def _append_risk_and_opportunity(self, lines: list[str], data: dict[str, Any]) -> None:
        lines.extend(["## 风险与机会", ""])
        matrix = data.get("risk_opportunity_matrix", [])
        if isinstance(matrix, list) and matrix:
            for item in matrix:
                if not isinstance(item, dict):
                    continue
                item_type = self._clean_text(str(item.get("type") or "未知"))
                title = self._clean_text(str(item.get("item") or "未命名事项"))
                impact = self._clean_text(str(item.get("impact") or "未知"))
                probability = self._clean_text(str(item.get("probability") or "未知"))
                strategy = self._clean_text(str(item.get("strategy") or "暂无策略"))
                lines.append(
                    f"- [{item_type}] {title}；影响程度 {impact}；发生概率 {probability}；应对策略 {strategy}"
                )
            lines.append("")
            return

        lines.append("- 风险/机会矩阵为空，以下内容由现有字段整理。")
        lines.append("")
        quick_read = data.get("quick_read", {}) if isinstance(data.get("quick_read"), dict) else {}
        threats = self._clean_items(quick_read.get("threats", []), limit=5)
        opportunities = self._clean_items(quick_read.get("opportunities", []), limit=5)

        if not threats:
            threats = self._clean_items(data.get("red_points", []), limit=5)
        if not opportunities:
            opportunities = self._clean_items(data.get("blue_points", []), limit=5)

        lines.append("### 风险")
        lines.append("")
        if threats:
            for item in threats:
                lines.append(f"- {self._format_fact_line(item)}")
        else:
            lines.append("- 暂无风险条目。")

        lines.extend(["", "### 机会", ""])
        if opportunities:
            for item in opportunities:
                lines.append(f"- {self._format_fact_line(item)}")
        else:
            lines.append("- 暂无机会条目。")
        lines.append("")

    def _append_full_process(self, lines: list[str], data: dict[str, Any]) -> None:
        lines.extend(["## 调研全过程", ""])
        phase_strategy = data.get("phase_strategy", {}) if isinstance(data.get("phase_strategy"), dict) else {}
        validation = phase_strategy.get("validation", {}) if isinstance(phase_strategy.get("validation"), dict) else {}
        debate = phase_strategy.get("debate", {}) if isinstance(phase_strategy.get("debate"), dict) else {}

        lines.extend(["### Phase 2 交叉验证摘要", ""])
        if validation:
            lines.append(f"- 验证通过：{int(validation.get('verified_count') or 0)} 条")
            lines.append(f"- 过滤淘汰：{int(validation.get('filtered_count') or 0)} 条")
            strategy = validation.get("strategy", {}) if isinstance(validation.get("strategy"), dict) else {}
            if strategy:
                lines.append(
                    "- 阈值："
                    f"confidence ≥ {strategy.get('min_confidence', 'N/A')}；"
                    f"strength ≥ {strategy.get('min_strength', 'N/A')}；"
                    f"weighted_score ≥ {strategy.get('min_weighted_score', 'N/A')}"
                )
                lines.append(
                    f"- 维度上限：{strategy.get('max_signals_per_dimension', 'N/A')} 条/维度"
                )
        else:
            lines.append("- 无 Phase 2 数据。")

        lines.extend(["", "### Phase 3 红蓝辩论摘要", ""])
        if debate:
            lines.append(f"- 辩论轮数：{int(debate.get('debate_rounds') or 0)}")
            lines.append(f"- 红队观点数：{int(debate.get('red_points') or 0)}")
            lines.append(f"- 蓝队观点数：{int(debate.get('blue_points') or 0)}")
            lines.append(f"- claim 总数：{int(debate.get('claim_count') or 0)}")
            lines.append(f"- 未决 claim：{int(debate.get('unresolved_claim_count') or 0)}")
        else:
            lines.append("- 无 Phase 3 数据。")

        lines.extend(["", "### 红蓝 claim 完整记录", ""])
        claims = debate.get("claims", []) if isinstance(debate.get("claims"), list) else []
        if claims:
            sorted_claims = sorted(
                [claim for claim in claims if isinstance(claim, dict)],
                key=lambda claim: (int(claim.get("round") or 0), str(claim.get("side") or "")),
            )
            for claim in sorted_claims:
                side = self.SIDE_NAME.get(str(claim.get("side") or ""), str(claim.get("side") or "未知"))
                verdict = self.VERDICT_NAME.get(str(claim.get("verdict") or ""), str(claim.get("verdict") or "未知"))
                round_no = int(claim.get("round") or 0)
                confidence = claim.get("confidence")
                confidence_text = f"{float(confidence):.2f}" if isinstance(confidence, (int, float)) else "N/A"
                text = self._clean_text(str(claim.get("text") or ""))
                if self._is_promotional_honor(text):
                    self.stats.filtered_promotional_items += 1
                    continue
                formatted = self._format_fact_line(text)
                lines.append(
                    f"- Round {round_no}｜{side}｜判定 {verdict}｜置信度 {confidence_text}｜{formatted}"
                )
        else:
            lines.append("- 无 claim 记录。")

        lines.append("")
        lines.append("### 各维度完整发现")
        lines.append("")
        agent_discoveries = data.get("agent_discoveries", {})
        if not isinstance(agent_discoveries, dict):
            agent_discoveries = {}

        for agent_key in self.AGENT_ORDER:
            lines.extend([f"#### {self.AGENT_NAME.get(agent_key, agent_key)}", ""])
            raw_items = agent_discoveries.get(agent_key, [])
            if not isinstance(raw_items, list) or not raw_items:
                lines.append("- 暂无记录。")
                lines.append("")
                continue

            kept_count = 0
            for item in raw_items:
                if isinstance(item, dict):
                    text = str(item.get("content") or item.get("evidence") or "")
                else:
                    text = str(item)
                text = self._clean_text(text)
                if not text:
                    continue
                if self._is_promotional_honor(text):
                    self.stats.filtered_promotional_items += 1
                    continue
                lines.append(f"- {self._format_fact_line(text)}")
                kept_count += 1

            if kept_count == 0:
                lines.append("- 所有条目均因“宣传性荣誉信息”规则被过滤。")
            lines.append("")

    def _append_filter_notes(self, lines: list[str]) -> None:
        lines.extend(
            [
                "## 过滤说明",
                "",
                f"- 本次共过滤宣传性荣誉信息 {self.stats.filtered_promotional_items} 条。",
                "- 过滤规则：删除“全球第一/排名第一/奖项/荣誉称号”等营销背书类描述。",
                "- 保留规则：与风险、合规、业务判断直接相关的信息（如召回、监管、认证暂停）不会被过滤。",
                "",
            ]
        )

    def _extract_recommendation_texts(self, recommendations: Any) -> list[str]:
        if not isinstance(recommendations, list):
            return []

        texts: list[str] = []
        for item in recommendations:
            if isinstance(item, dict):
                text = (
                    str(item.get("description") or "")
                    or str(item.get("content") or "")
                    or str(item.get("title") or "")
                )
            else:
                text = str(item)

            cleaned = self._clean_text(text)
            if not cleaned:
                continue
            if self._is_promotional_honor(cleaned):
                self.stats.filtered_promotional_items += 1
                continue
            texts.append(cleaned)
        return texts

    def _clean_items(self, values: Any, *, limit: int | None = None) -> list[str]:
        if not isinstance(values, list):
            return []

        cleaned_items: list[str] = []
        for value in values:
            text = self._clean_text(str(value))
            if not text:
                continue
            if self._is_promotional_honor(text):
                self.stats.filtered_promotional_items += 1
                continue
            cleaned_items.append(text)
            if limit is not None and len(cleaned_items) >= limit:
                break
        return cleaned_items

    def _clean_summary(self, summary: str) -> str:
        text = self._clean_text(summary)
        if "| 维度 |" in text:
            text = text.split("| 维度 |", 1)[0].strip()
        text = re.sub(r"^综合报告\s*", "", text)
        return text

    def _clean_text(self, text: str) -> str:
        value = str(text or "").strip()
        if not value:
            return ""

        value = value.replace("**", "").replace("__", "").replace("`", "")
        value = re.sub(r"^#+\s*", "", value, flags=re.MULTILINE)
        value = value.replace("===== 综合报告 =====", "")
        value = value.replace("===== 战略建议 =====", "")
        value = re.sub(r"\|\s*-+\s*(\|\s*-+\s*)+\|?", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _format_fact_line(self, raw_text: str) -> str:
        parsed = self._parse_fact_segments(raw_text)
        pieces: list[str] = []

        source = parsed.get("source", "")
        if source:
            pieces.append(f"来源 {source}")

        reliability = parsed.get("source_reliability", "")
        if reliability:
            pieces.append(f"来源可靠性 {reliability}")

        conclusion = parsed.get("conclusion", "")
        if conclusion:
            pieces.append(f"结论：{conclusion}")

        evidence = parsed.get("evidence", "")
        if evidence:
            pieces.append(f"证据：{evidence}")

        time_value = parsed.get("time", "")
        if time_value:
            pieces.append(f"时间：{time_value}")

        impact = parsed.get("impact", "")
        if impact:
            pieces.append(f"影响：{impact}")

        exploitability = parsed.get("exploitability", "")
        if exploitability:
            pieces.append(f"可利用度：{exploitability}")

        confidence = parsed.get("confidence", "")
        if confidence:
            pieces.append(f"置信度：{confidence}")

        extras = parsed.get("extras", [])
        if isinstance(extras, list):
            pieces.extend(extra for extra in extras if isinstance(extra, str) and extra)

        if not pieces:
            return self._clean_text(raw_text)
        return "；".join(pieces)

    def _parse_fact_segments(self, raw_text: str) -> dict[str, Any]:
        text = self._clean_text(raw_text)
        if not text:
            return {}

        segments = re.split(r"\s+—\s+", text)
        if not segments:
            return {"conclusion": text}

        result: dict[str, Any] = {"conclusion": segments[0].strip(), "extras": []}

        # 兼容 [red_team]、[来源可靠性: 高] 前缀
        agent_match = re.match(r"^\[([^\]]+)\]\s*(.+)$", result["conclusion"])
        if agent_match:
            result["source"] = agent_match.group(1).strip()
            result["conclusion"] = agent_match.group(2).strip()

        reliability_match = re.match(r"^\[来源可靠性:\s*([^\]]+)\]\s*(.+)$", result["conclusion"])
        if reliability_match:
            result["source_reliability"] = reliability_match.group(1).strip()
            result["conclusion"] = reliability_match.group(2).strip()

        for segment in segments[1:]:
            part = segment.strip()
            if not part:
                continue

            if "：" in part:
                key, value = part.split("：", 1)
            elif ":" in part:
                key, value = part.split(":", 1)
            else:
                result["extras"].append(part)
                continue

            norm_key = key.strip().lower()
            norm_val = self._clean_text(value)
            if not norm_val:
                continue

            if "证据" in norm_key:
                result["evidence"] = norm_val
            elif "时间" in norm_key:
                result["time"] = norm_val
            elif "影响" in norm_key or "后果" in norm_key or "含义" in norm_key:
                result["impact"] = norm_val
            elif "置信度" in norm_key:
                result["confidence"] = norm_val
            elif "可利用度" in norm_key:
                result["exploitability"] = norm_val
            elif "来源可靠性" in norm_key:
                result["source_reliability"] = norm_val
            elif "来源" in norm_key and "证据" not in norm_key:
                result["source"] = norm_val
            else:
                result["extras"].append(f"{key.strip()}：{norm_val}")

        return result

    def _is_promotional_honor(self, text: str) -> bool:
        value = self._clean_text(text)
        if not value:
            return False

        risk_keywords = [
            "召回",
            "事故",
            "风险",
            "监管",
            "处罚",
            "合规",
            "投诉",
            "起火",
            "爆炸",
            "隐患",
            "下架",
            "暂停",
            "缺陷",
            "认证",
        ]
        if any(keyword in value for keyword in risk_keywords):
            return False

        promo_keywords = [
            "全球第一",
            "排名第一",
            "行业第一",
            "获奖",
            "奖项",
            "荣誉称号",
            "最佳",
            "护城河类型",
            "追赶难度/时间",
        ]
        return any(keyword in value for keyword in promo_keywords)
