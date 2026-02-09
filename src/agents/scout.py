"""侦察 Agent 模块。

负责收集目标产品的公开信息。
使用 Signal 结构（新版本）进行信息收集。
"""

import re
from typing import Any

from src.agents.base import BaseAgent, AgentType, AgentResult, DiscoverySource

# 从统一模块导入 Signal 支持
from src.utils.imports import (
    SIGNALS_AVAILABLE,
    Signal,
    SignalType,
    Sentiment,
    Actionability,
)


class ScoutAgent(BaseAgent):
    """侦察 Agent。

    收集官网信息、定价、功能列表等公开信息。
    支持在线搜索以获取最新信息。
    使用 Signal 结构（新版本）进行信息收集。
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化侦察 Agent。"""
        config = kwargs.pop("config", None)
        super().__init__(
            agent_type=AgentType.SCOUT,
            name="侦察专家",
            **kwargs,
        )

    def execute(self, **context: Any) -> AgentResult:
        """执行侦察任务。

        Args:
            **context: 执行上下文，应包含：
                - target: 目标产品/公司名称
                - competitors: 竞品列表（可选）

        Returns:
            Agent 执行结果
        """
        target = context.get("target", "")
        competitors = context.get("competitors", [])

        if not target:
            return AgentResult(
                agent_type=self.agent_type.value,
                agent_name=self.name,
                discoveries=[],
                handoffs_created=0,
                metadata={"error": "No target specified"},
            )

        # 第一步：获取搜索上下文
        search_context = self._get_search_context(target, competitors)
        if search_context:
            context["_search_context"] = search_context

        # 第二步：构建分析提示
        prompt = self._build_scout_prompt(target, competitors, bool(search_context))

        # 第三步：执行分析
        response = self.think(prompt, context)

        # 第四步：解析发现/信号
        if self.USE_SIGNALS and SIGNALS_AVAILABLE:
            signals = self._parse_and_store_signals(response, target)
            discoveries = [s.to_dict() for s in signals]
            discovery_count = len(signals)
        else:
            discoveries = self._parse_and_store_discoveries(response, target)
            discovery_count = len(discoveries)

        # 第五步：确保最小发现数量
        discoveries = self._ensure_min_discoveries(
            discoveries,
            target,
            context,
            self._build_deep_search_prompt,
        )

        # 第六步：检查是否需要创建 handoff
        handoffs_created = self._check_for_handoffs(discoveries, context)

        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=discoveries,
            handoffs_created=handoffs_created,
            metadata={
                "target": target,
                "competitors": competitors,
                "discovery_count": discovery_count,
                "search_used": bool(search_context),
                "use_signals": self.USE_SIGNALS and SIGNALS_AVAILABLE,
            },
        )

    def _get_search_context(self, target: str, competitors: list[str]) -> str:
        """获取搜索上下文。

        Args:
            target: 目标产品
            competitors: 竞品列表

        Returns:
            搜索上下文字符串
        """
        # 使用并行搜索提高效率
        queries = [
            f"{target} 产品功能 定价 介绍",
        ]

        # 如果有竞品，搜索竞品对比信息
        if competitors:
            queries.append(f"{target} 对比 {competitors[0]} 优缺点")

        # 使用并行搜索方法
        results = self.search_context_async(queries, max_results=5)

        # 构建上下文
        context_parts = []
        for query in queries:
            if query in results and results[query]:
                context_parts.append(f"## 搜索结果: {query}\n{results[query]}")

        return "\n\n".join(context_parts) if context_parts else ""

    def _build_scout_prompt(self, target: str, competitors: list[str], has_search: bool = False) -> str:
        """构建侦察提示词。

        Args:
            target: 目标产品
            competitors: 竞品列表
            has_search: 是否有搜索结果

        Returns:
            提示词
        """
        base_prompt = f"""请对「{target}」进行全面的侦察分析。

请从以下维度收集信息：

1. **产品定位**：核心价值主张、目标用户群体
2. **定价策略**：价格范围、付费模式（免费/订阅/一次性）
3. **核心功能**：主要功能列表、特色功能
4. **公司信息**：成立时间、融资情况、团队规模（如有）

对于每个发现，请标注：
- 信息来源（官网/文档/新闻/公告等）
- 数据时效性（如果适用）
- 是正面还是负面信息

**输出格式要求**：
请以列表格式输出，每个发现单独一行，以「- 」开头。

示例格式：
- [官网] 该产品采用 SaaS 订阅模式，基础版免费，专业版每月 $29（2025年数据）
- [文档] 核心功能包括 X、Y、Z，其中 Z 为独家特色功能
- [新闻] 公司于 2024 年完成 A 轮融资，金额为 500 万美元

要求：至少提供 15-30 条有价值的发现。
"""

        if competitors:
            base_prompt += f"\n对比产品：{', '.join(competitors)}\n"

        if has_search:
            base_prompt += "\n**注意**：已提供搜索结果作为参考，请综合分析后生成发现。\n"

        return base_prompt

    def _build_deep_search_prompt(self, target: str, count: int) -> str:
        """构建深化搜索提示词。

        Args:
            target: 目标产品
            count: 需要补充的发现数量

        Returns:
            提示词
        """
        return f"""请继续对「{target}」进行深入分析，再提供至少 {count} 条新的发现。

请从以下角度补充：
1. 之前未覆盖的细节
2. 更深入的分析
3. 更具体的案例或数据
4. 用户评价或市场反馈

每条发现单独一行，以「- 」开头。
"""

    def _parse_and_store_discoveries(self, response: str, target: str) -> list[Any]:
        """解析响应并存储发现（旧版本，向后兼容）。

        使用增强的多格式解析器。

        Args:
            response: LLM 响应
            target: 目标产品

        Returns:
            发现列表
        """
        # 使用基类的增强解析方法
        return self._parse_and_store_discoveries_from_text(
            response,
            target,
            DiscoverySource.WEBSITE,
        )

    def _parse_and_store_signals(self, response: str, target: str) -> list[Any]:
        """解析响应并存储信号（新版本）。

        使用增强的多格式解析器。

        Args:
            response: LLM 响应
            target: 目标产品

        Returns:
            Signal 列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        import re

        signals = []

        # 策略 1: 尝试解析 JSON 格式
        json_signals = self._try_parse_json_signals(response, target)
        if json_signals:
            return json_signals

        # 策略 2: 尝试解析列表格式
        list_signals = self._try_parse_list_signals(response, target)
        if list_signals:
            return list_signals

        # 策略 3: 宽松模式解析段落
        return self._try_parse_paragraph_signals(response, target)

    def _try_parse_json_signals(self, response: str, target: str) -> list[Any] | None:
        """尝试从 JSON 格式解析信号。"""
        import json
        import re

        patterns = [
            r'```json\s*(\[.*?\])\s*```',
            r'```\s*(\[.*?\])\s*```',
            r'\[\s*\{[^\]]*\}\s*\]',
        ]

        for pattern in patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                    data = json.loads(json_str)

                    if isinstance(data, list):
                        signals = []
                        for item in data:
                            if isinstance(item, dict):
                                evidence = (
                                    item.get("content") or
                                    item.get("description") or
                                    item.get("text") or
                                    item.get("evidence") or
                                    item.get("finding", "")
                                )
                                if evidence and self._is_valid_discovery(evidence):
                                    signal = self._create_signal_from_dict(evidence, item, target)
                                    if signal:
                                        signals.append(signal)

                        if signals:
                            return signals
                except (json.JSONDecodeError, ValueError):
                    continue

        return None

    def _try_parse_list_signals(self, response: str, target: str) -> list[Any] | None:
        """尝试从列表格式解析信号。"""
        import re

        signals = []
        lines = response.split("\n")

        list_marker_count = sum(
            1 for line in lines
            if line.strip() and any(
                line.strip().startswith(marker)
                for marker in ["- ", "• ", "* ", "1.", "2.", "3.", "4.", "5.",
                               "6.", "7.", "8.", "9."]
            )
        )

        if list_marker_count < 3:
            return None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            list_patterns = [
                r'^[\-\•\*]\s+',
                r'^\d+\.\s+',
                r'^\d+\)\s+',
            ]

            evidence = None
            for pattern in list_patterns:
                if re.match(pattern, line):
                    evidence = re.sub(pattern, '', line, count=1)
                    break

            if evidence is None:
                continue

            if self._is_valid_discovery(evidence):
                signal = self._create_signal_from_evidence(evidence, target)
                if signal:
                    signals.append(signal)

        return signals if signals else None

    def _try_parse_paragraph_signals(self, response: str, target: str) -> list[Any]:
        """尝试从段落格式解析信号。"""
        import re

        signals = []
        text = re.sub(r'```.*?```', '', response, flags=re.DOTALL)
        paragraphs = re.split(r'\n\s*\n|(?<=[.!?。！？])\s*\n', text)

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            paragraph = re.sub(r'^(发现|结论|分析|要点|总结|note|discovery|conclusion)\s*[:：]?\s*', '', paragraph, flags=re.IGNORECASE)

            if self._is_valid_discovery(paragraph):
                signal = self._create_signal_from_evidence(paragraph, target)
                if signal:
                    signals.append(signal)

        return signals

    def _is_valid_discovery(self, content: str) -> bool:
        """验证内容是否为有效发现。"""
        content = content.strip()

        if len(content) < 15:
            return False

        invalid_patterns = [
            r'^暂无', r'^待补充', r'^to be determined', r'^tbd',
            r'^n/a', r'^无数据', r'^无发现', r'^没有找到',
            r'^以下是', r'^the following', r'^please note', r'^注意',
        ]

        for pattern in invalid_patterns:
            if re.match(pattern, content, re.IGNORECASE):
                return False

        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', content))
        has_english_words = bool(re.search(r'[a-zA-Z]{3,}', content))

        return has_chinese or has_english_words

    def _create_signal_from_dict(self, evidence: str, item: dict[str, Any], target: str) -> Any:
        """从字典创建信号。"""
        sentiment = self._analyze_sentiment(evidence)
        signal_type = self._classify_signal_type(evidence)
        actionability = self._determine_actionability(evidence)
        tags = self._extract_tags(evidence)

        # 使用字典中的质量评分，或自行计算
        quality = item.get("quality_score", min(1.0, len(evidence) / 200))
        confidence = quality
        strength = min(1.0, len(evidence) / 150)

        return self.emit_signal(
            signal_type=signal_type,
            evidence=evidence,
            confidence=confidence,
            strength=strength,
            sentiment=sentiment,
            tags=tags,
            source="web_search",
            actionability=actionability,
            metadata={"target": target},
        )

    def _create_signal_from_evidence(self, evidence: str, target: str) -> Any:
        """从证据创建信号。"""
        sentiment = self._analyze_sentiment(evidence)
        signal_type = self._classify_signal_type(evidence)
        actionability = self._determine_actionability(evidence)
        tags = self._extract_tags(evidence)

        confidence = min(1.0, len(evidence) / 200)
        strength = min(1.0, len(evidence) / 150)

        return self.emit_signal(
            signal_type=signal_type,
            evidence=evidence,
            confidence=confidence,
            strength=strength,
            sentiment=sentiment,
            tags=tags,
            source="web_search",
            actionability=actionability,
            metadata={"target": target},
        )

    def _analyze_sentiment(self, text: str) -> Any:
        """分析文本的情感倾向。

        Args:
            text: 文本内容

        Returns:
            Sentiment 枚举值
        """
        if not SIGNALS_AVAILABLE:
            return None

        positive_keywords = [
            "优秀", "强大", "领先", "创新", "成功",
            "excellent", "powerful", "leading", "innovative", "successful",
            "优势", "优势", "增长", "扩展",
        ]
        negative_keywords = [
            "问题", "缺陷", "不足", "落后", "失败",
            "problem", "issue", "flaw", "weakness", "failure",
            "劣势", "下降", "缩减",
        ]

        text_lower = text.lower()
        positive_count = sum(1 for kw in positive_keywords if kw.lower() in text_lower)
        negative_count = sum(1 for kw in negative_keywords if kw.lower() in text_lower)

        if positive_count > negative_count:
            return Sentiment.POSITIVE
        elif negative_count > positive_count:
            return Sentiment.NEGATIVE
        else:
            return Sentiment.NEUTRAL

    def _classify_signal_type(self, text: str) -> Any:
        """根据文本内容分类信号类型。

        Args:
            text: 文本内容

        Returns:
            SignalType 枚举值
        """
        if not SIGNALS_AVAILABLE:
            return None

        text_lower = text.lower()

        # 机会性信号
        opportunity_keywords = ["机会", "opportunity", "potential", "市场空白", "蓝海"]
        if any(kw in text_lower for kw in opportunity_keywords):
            return SignalType.OPPORTUNITY

        # 威胁性信号
        threat_keywords = ["威胁", "threat", "竞争激烈", "风险", "risk"]
        if any(kw in text_lower for kw in threat_keywords):
            return SignalType.THREAT

        # 需求性信号
        need_keywords = ["需求", "need", "用户痛点", "问题", "待解决"]
        if any(kw in text_lower for kw in need_keywords):
            return SignalType.NEED

        # 风险性信号
        risk_keywords = ["风险", "risk", "不确定性", "依赖"]
        if any(kw in text_lower for kw in risk_keywords):
            return SignalType.RISK

        # 默认为洞察性信号
        return SignalType.INSIGHT

    def _determine_actionability(self, text: str) -> Any:
        """确定信号的可行动性。

        Args:
            text: 文本内容

        Returns:
            Actionability 枚举值
        """
        if not SIGNALS_AVAILABLE:
            return None

        text_lower = text.lower()

        # 立即行动
        immediate_keywords = ["紧急", "urgent", "立即", "危机", "critical"]
        if any(kw in text_lower for kw in immediate_keywords):
            return Actionability.IMMEDIATE

        # 短期行动
        short_term_keywords = ["建议", "recommend", "应该", "可以改善", "优化"]
        if any(kw in text_lower for kw in short_term_keywords):
            return Actionability.SHORT_TERM

        # 长期行动
        long_term_keywords = ["战略", "strategy", "长期", "规划", "发展"]
        if any(kw in text_lower for kw in long_term_keywords):
            return Actionability.LONG_TERM

        # 默认为信息性
        return Actionability.INFORMATIONAL

    def _extract_tags(self, text: str) -> list[str]:
        """从文本中提取标签。

        Args:
            text: 文本内容

        Returns:
            标签列表
        """
        tags = []
        text_lower = text.lower()

        # 产品相关标签
        if any(kw in text_lower for kw in ["价格", "pricing", "费用", "cost"]):
            tags.append("pricing")
        if any(kw in text_lower for kw in ["功能", "feature", "特性"]):
            tags.append("features")
        if any(kw in text_lower for kw in ["用户", "user", "客户"]):
            tags.append("users")
        if any(kw in text_lower for kw in ["市场", "market", "竞争"]):
            tags.append("market")

        return tags

    def _check_for_handoffs(self, discoveries: list[Any], context: dict[str, Any]) -> int:
        """检查是否需要创建 handoff。

        Args:
            discoveries: 发现列表
            context: 执行上下文

        Returns:
            创建的 handoff 数量
        """
        handoffs_created = 0
        target = context.get("target", "")

        # 如果发现了技术相关信息，交接给技术 Agent
        tech_keywords = ["API", "SDK", "架构", "技术栈", "开发"]
        for discovery in discoveries:
            # 处理 Signal 和 Discovery 两种格式
            if isinstance(discovery, dict):
                content = discovery.get("evidence") or discovery.get("content", "")
                discovery_id = discovery.get("id", "")
            else:
                content = getattr(discovery, "evidence", None) or getattr(discovery, "content", "")
                discovery_id = getattr(discovery, "id", "")

            if any(keyword in content for keyword in tech_keywords):
                from src.handoff import HandoffContext, HandoffPriority

                self.create_handoff(
                    to_agent="technical",
                    context=HandoffContext(
                        source_discovery_id=discovery_id,
                        reasoning=f"发现了关于 {target} 的技术相关信息，需要深入分析。",
                        relevant_data={"discovery_content": content},
                        suggested_actions=["分析技术栈", "推测架构模式"],
                    ),
                    priority=HandoffPriority.MEDIUM,
                )
                handoffs_created += 1

        return handoffs_created
