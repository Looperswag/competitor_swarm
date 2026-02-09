"""体验 Agent 模块。

负责分析产品的 UI/UX 设计和用户体验。
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


class ExperienceAgent(BaseAgent):
    """体验 Agent。

    分析 UI/UX 设计、交互体验、易用性等。
    支持在线搜索以获取用户评价和体验反馈。
    使用 Signal 结构（新版本）进行信息收集。
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化体验 Agent。"""
        super().__init__(
            agent_type=AgentType.EXPERIENCE,
            name="体验专家",
            **kwargs,
        )

    def execute(self, **context: Any) -> AgentResult:
        """执行体验分析任务。

        Args:
            **context: 执行上下文，应包含：
                - target: 目标产品/公司名称

        Returns:
            Agent 执行结果
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

        # 第二步：构建分析提示
        prompt = self._build_experience_prompt(target, bool(search_context))

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
                "discovery_count": discovery_count,
                "search_used": bool(search_context),
                "use_signals": self.USE_SIGNALS and SIGNALS_AVAILABLE,
            },
        )

    def _get_search_context(self, target: str) -> str:
        """获取搜索上下文。

        Args:
            target: 目标产品

        Returns:
            搜索上下文字符串
        """
        # 使用并行搜索 - 虽然只有一个查询，但为了一致性使用并行接口
        queries = [
            f"{target} 用户体验 UI设计 评价 反馈"
        ]

        # 使用并行搜索方法
        results = self.search_context_async(queries, max_results=5)

        # 构建上下文
        context_parts = []
        for query in queries:
            if query in results and results[query]:
                context_parts.append(f"## 搜索结果: {query}\n{results[query]}")

        return "\n\n".join(context_parts) if context_parts else ""

    def _build_experience_prompt(self, target: str, has_search: bool = False) -> str:
        """构建体验分析提示词。

        Args:
            target: 目标产品
            has_search: 是否有搜索结果

        Returns:
            提示词
        """
        prompt = f"""请对「{target}」的用户体验进行全面分析。

基于已有的产品信息，从以下维度分析：

1. **界面设计**：视觉风格、色彩方案、布局结构
2. **交互体验**：操作流程、反馈机制、动画效果
3. **易用性**：学习曲线、帮助引导、新手友好度
4. **信息架构**：内容组织、导航设计、信息层次
5. **移动端体验**：响应式设计、移动端功能完整性
6. **用户反馈**：用户评价中的常见问题和表扬点

请以结构化的方式输出，每个发现单独一行，以「- 」开头。
对于优点和问题，请分别标注「✓」和「✗」。

要求：至少提供 15-30 条有价值的发现。
"""

        if has_search:
            prompt += "\n**注意**：已提供用户反馈搜索结果作为参考。\n"

        return prompt

    def _build_deep_search_prompt(self, target: str, count: int) -> str:
        """构建深化搜索提示词。

        Args:
            target: 目标产品
            count: 需要补充的发现数量

        Returns:
            提示词
        """
        return f"""请继续对「{target}」的用户体验进行深入分析，再提供至少 {count} 条新的发现。

请从以下角度补充：
1. 更具体的交互细节
2. 用户评价中提到的问题
3. 竞品的体验对比
4. 可优化的体验点

每条发现单独一行，以「- 」开头，标注「✓」或「✗」。
"""

    def _parse_and_store_discoveries(self, response: str, target: str) -> list[Any]:
        """解析响应并存储发现（旧版本，向后兼容）。

        使用增强的多格式解析器，支持情感标记。

        Args:
            response: LLM 响应
            target: 目标产品

        Returns:
            发现列表
        """
        # 使用基类的增强解析方法获取原始发现
        raw_discoveries = self._parse_and_store_discoveries_from_text(
            response,
            target,
            DiscoverySource.ANALYSIS,
        )

        # 处理情感标记 - 由于 Discovery 是 frozen，需要创建新对象
        processed_discoveries = []
        for discovery in raw_discoveries:
            content = discovery.content
            is_positive = "✓" in content or "+" in content or "√" in content
            is_negative = "✗" in content or "×" in content or "-" in content

            # 移除标记符号但保留信息
            clean_content = content
            for marker in ["✓", "✗", "+", "-", "√", "×"]:
                clean_content = clean_content.replace(marker, "").strip()

            # 创建新的 metadata（合并原有和新增）
            new_metadata = {
                **discovery.metadata,
                "is_positive": is_positive,
                "is_negative": is_negative,
            }

            # 创建新的 Discovery 对象（因为 Discovery 是 frozen 的）
            from src.environment import Discovery
            new_discovery = Discovery(
                id=discovery.id,
                agent_type=discovery.agent_type,
                content=clean_content,
                source=discovery.source,
                quality_score=discovery.quality_score,
                references=discovery.references,
                metadata=new_metadata,
                timestamp=discovery.timestamp,
            )
            processed_discoveries.append(new_discovery)

        return processed_discoveries

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

        for line in lines:
            line = line.strip()
            if not line or not (line.startswith("- ") or line.startswith("• ")):
                continue

            evidence = line[2:].strip()

            # 移除标记符号但保留信息
            is_positive = "✓" in evidence or "+" in evidence
            is_negative = "✗" in evidence or "-" in evidence
            clean_evidence = evidence.replace("✓", "").replace("✗", "").strip()

            if len(clean_evidence) < 10:
                continue

            # 确定情感倾向
            sentiment = Sentiment.POSITIVE if is_positive else (Sentiment.NEGATIVE if is_negative else Sentiment.NEUTRAL)

            # 确定信号类型
            signal_type = SignalType.NEED if is_negative else SignalType.OPPORTUNITY

            # 估算置信度和强度
            confidence = min(1.0, len(clean_evidence) / 150)
            strength = min(1.0, len(clean_evidence) / 120)

            # 确定可行动性
            actionability = Actionability.SHORT_TERM if is_negative else Actionability.INFORMATIONAL

            # 提取标签
            tags = ["ux", "design"]
            if "交互" in clean_evidence or "interface" in clean_evidence.lower():
                tags.append("interaction")
            if "易用" in clean_evidence or "usable" in clean_evidence.lower():
                tags.append("usability")

            signal = self.emit_signal(
                signal_type=signal_type,
                evidence=clean_evidence,
                confidence=confidence,
                strength=strength,
                sentiment=sentiment,
                tags=tags,
                source="ux_analysis",
                actionability=actionability,
                metadata={"target": target, "is_positive": is_positive, "is_negative": is_negative},
            )

            if signal:
                signals.append(signal)

        return signals
