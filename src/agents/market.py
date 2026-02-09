"""市场分析 Agent 模块。

负责分析产品的市场地位和竞争格局。
使用 Signal 结构（新版本）进行信息收集。
"""

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


class MarketAgent(BaseAgent):
    """市场分析 Agent。

    分析市场定位、用户评价、市场份额等。
    支持在线搜索以获取最新市场信息。
    使用 Signal 结构（新版本）进行信息收集。
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化市场分析 Agent。"""
        super().__init__(
            agent_type=AgentType.MARKET,
            name="市场分析专家",
            **kwargs,
        )

    def execute(self, **context: Any) -> AgentResult:
        """执行市场分析任务。

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
        prompt = self._build_market_prompt(target, competitors, bool(search_context))

        # 第三步：基于现有发现进行分析
        response = self.think_with_discoveries(
            prompt,
            agent_types=["scout"],
            context=context,
        )

        # 第四步：解析并存储发现/信号
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

        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=discoveries,
            handoffs_created=0,
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
            f"{target} 市场份额 用户评价 口碑"
        ]

        # 如果有竞品，搜索对比信息
        if competitors:
            queries.append(f"{target} 对比 {competitors[0]} 竞品分析")

        # 使用并行搜索方法
        results = self.search_context_async(queries, max_results=5)

        # 构建上下文
        context_parts = []
        for query in queries:
            if query in results and results[query]:
                context_parts.append(f"## 搜索结果: {query}\n{results[query]}")

        return "\n\n".join(context_parts) if context_parts else ""

    def _build_market_prompt(
        self, target: str, competitors: list[str], has_search: bool = False
    ) -> str:
        """构建市场分析提示词。

        Args:
            target: 目标产品
            competitors: 竞品列表
            has_search: 是否有搜索结果

        Returns:
            提示词
        """
        prompt = f"""请对「{target}」的市场地位进行全面分析。

基于已有的产品信息，从以下维度分析：

1. **市场定位**：与竞品的差异化、目标细分市场
2. **用户评价**：应用商店评分、用户反馈趋势（正面/负面）
3. **竞争格局**：主要竞争对手、市场集中度
4. **增长趋势**：用户增长情况、融资情况（如有）
5. **SWOT 分析**：
   - 优势（Strengths）
   - 劣势（Weaknesses）
   - 机会（Opportunities）
   - 威胁（Threats）

请以结构化的方式输出，每个发现单独一行，以「- 」开头。
对于 SWOT 分析，请分别标注 [S]、[W]、[O]、[T]。

要求：至少提供 15-30 条有价值的发现。
"""

        if competitors:
            prompt += f"\n\n对比产品：{', '.join(competitors)}\n"

        if has_search:
            prompt += "\n**注意**：已提供市场信息搜索结果作为参考。\n"

        return prompt

    def _build_deep_search_prompt(self, target: str, count: int) -> str:
        """构建深化搜索提示词。

        Args:
            target: 目标产品
            count: 需要补充的发现数量

        Returns:
            提示词
        """
        return f"""请继续对「{target}」的市场地位进行深入分析，再提供至少 {count} 条新的发现。

请从以下角度补充：
1. 更细致的市场细分
2. 用户反馈中的具体问题
3. 竞品对比的优劣势
4. 市场机会和威胁

每条发现单独一行，以「- 」开头。
"""

    def _parse_and_store_discoveries(self, response: str, target: str) -> list[Any]:
        """解析响应并存储发现（旧版本，向后兼容）。

        使用增强的多格式解析器，支持 SWOT 分类。

        Args:
            response: LLM 响应
            target: 目标产品

        Returns:
            发现列表
        """
        import re

        # 识别 SWOT 分类
        swot_keywords = {
            "优势": "strength",
            "劣势": "weakness",
            "机会": "opportunity",
            "威胁": "threat",
            "Strengths": "strength",
            "Weaknesses": "weakness",
            "Opportunities": "opportunity",
            "Threats": "threat",
        }

        # 使用基类的增强解析方法获取原始发现
        raw_discoveries = self._parse_and_store_discoveries_from_text(
            response,
            target,
            DiscoverySource.ANALYSIS,
        )

        # 处理 SWOT 分类
        lines = response.split("\n")
        current_category = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检测 SWOT 标题
            for keyword, category in swot_keywords.items():
                if keyword in line and len(line) < 30:
                    current_category = category
                    break

        # 为所有发现添加当前分类 - 由于 Discovery 是 frozen，需要创建新对象
        if current_category:
            processed_discoveries = []
            for discovery in raw_discoveries:
                # 创建新的 metadata（合并原有和新增）
                new_metadata = {
                    **discovery.metadata,
                    "category": current_category,
                }

                # 创建新的 Discovery 对象（因为 Discovery 是 frozen 的）
                from src.environment import Discovery
                new_discovery = Discovery(
                    id=discovery.id,
                    agent_type=discovery.agent_type,
                    content=discovery.content,
                    source=discovery.source,
                    quality_score=discovery.quality_score,
                    references=discovery.references,
                    metadata=new_metadata,
                    timestamp=discovery.timestamp,
                )
                processed_discoveries.append(new_discovery)
            return processed_discoveries

        return raw_discoveries

    def _parse_and_store_signals(self, response: str, target: str) -> list[Any]:
        """解析响应并存储信号（新版本）。

        Args:
            response: LLM 响应
            target: 目标产品

        Returns:
            Signal 列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        signals = []
        lines = response.split("\n")

        # SWOT 到 SignalType 的映射
        swot_to_type = {
            "strength": SignalType.OPPORTUNITY,
            "weakness": SignalType.THREAT,
            "opportunity": SignalType.OPPORTUNITY,
            "threat": SignalType.THREAT,
        }

        current_category = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 检测 SWOT 标题
            detected = False
            for keyword, category in swot_to_type.items():
                if keyword in line and len(line) < 20:
                    current_category = category
                    detected = True
                    break

            if detected:
                continue

            # 处理发现内容
            if line.startswith("- ") or line.startswith("• "):
                evidence = line[2:].strip()

                if len(evidence) < 10:
                    continue

                # 确定信号类型
                signal_type = current_category or SignalType.INSIGHT

                # 确定情感倾向
                if signal_type == SignalType.OPPORTUNITY:
                    sentiment = Sentiment.POSITIVE
                elif signal_type == SignalType.THREAT:
                    sentiment = Sentiment.NEGATIVE
                else:
                    sentiment = Sentiment.NEUTRAL

                # 估算置信度和强度
                confidence = min(1.0, len(evidence) / 150)
                strength = min(1.0, len(evidence) / 120)

                # 确定可行动性
                if signal_type == SignalType.THREAT:
                    actionability = Actionability.SHORT_TERM
                elif signal_type == SignalType.OPPORTUNITY:
                    actionability = Actionability.LONG_TERM
                else:
                    actionability = Actionability.INFORMATIONAL

                # 提取标签
                tags = ["market"]
                if "份额" in evidence or "market share" in evidence.lower():
                    tags.append("market_share")
                if "用户" in evidence or "user" in evidence.lower():
                    tags.append("users")
                if "竞争" in evidence or "competition" in evidence.lower():
                    tags.append("competition")

                signal = self.emit_signal(
                    signal_type=signal_type,
                    evidence=evidence,
                    confidence=confidence,
                    strength=strength,
                    sentiment=sentiment,
                    tags=tags,
                    source="market_analysis",
                    actionability=actionability,
                    metadata={"target": target, "swot_category": current_category},
                )

                if signal:
                    signals.append(signal)

        return signals
