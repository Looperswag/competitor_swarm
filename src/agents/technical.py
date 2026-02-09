"""技术分析 Agent 模块。

负责推测产品使用的技术栈和架构。
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


class TechnicalAgent(BaseAgent):
    """技术分析 Agent。

    推测技术栈、架构模式、性能特征等。
    支持在线搜索以获取技术文档和开发信息。
    使用 Signal 结构（新版本）进行信息收集。
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化技术分析 Agent。"""
        super().__init__(
            agent_type=AgentType.TECHNICAL,
            name="技术分析专家",
            **kwargs,
        )

    def execute(self, **context: Any) -> AgentResult:
        """执行技术分析任务。

        Args:
            **context: 执行上下文，应包含：
                - target: 目标产品/公司名称
                - _handoff: handoff 上下文（可选）

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

        # 检查是否有 handoff 上下文
        handoff_context = context.get("_handoff")

        # 第一步：获取搜索上下文
        search_context = self._get_search_context(target)
        if search_context:
            context["_search_context"] = search_context

        # 第二步：构建分析提示
        prompt = self._build_technical_prompt(target, handoff_context, bool(search_context))

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
                "from_handoff": handoff_context is not None,
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
            f"{target} 技术栈 架构 API 文档"
        ]

        # 使用并行搜索方法
        results = self.search_context_async(queries, max_results=5)

        # 构建上下文
        context_parts = []
        for query in queries:
            if query in results and results[query]:
                context_parts.append(f"## 搜索结果: {query}\n{results[query]}")

        return "\n\n".join(context_parts) if context_parts else ""

    def _build_technical_prompt(
        self, target: str, handoff_context: Any, has_search: bool = False
    ) -> str:
        """构建技术分析提示词。

        Args:
            target: 目标产品
            handoff_context: handoff 上下文
            has_search: 是否有搜索结果

        Returns:
            提示词
        """
        prompt = f"""请对「{target}」的技术实现进行深入分析。

基于已有的产品信息，从以下维度分析（使用"推测"而非断言）：

1. **前端技术**：可能使用的框架、库、构建工具
2. **后端技术**：可能的架构模式（单体/微服务）、API 设计风格
3. **数据存储**：可能的数据库选择（关系型/文档型/图数据库等）
4. **性能特征**：加载速度、实时性要求、可能的优化手段
5. **安全机制**：认证方式、数据加密、API 安全
6. **基础设施**：可能的云服务提供商、CDN 使用等
7. **开发实践**：可能的开发流程、测试策略、部署方式

对于每个推测，请：
- 给出推测依据（如：从功能特性推断）
- 标注置信度（高/中/低）

请以结构化的方式输出，每个发现单独一行，以「- 」开头。
格式：「[置信度] 推测内容 - 依据」

要求：至少提供 15-30 条技术推测。
"""

        if handoff_context:
            prompt += f"\n\n特别关注以下信息：{handoff_context.get('reasoning', '')}"

        if has_search:
            prompt += "\n**注意**：已提供技术文档搜索结果作为参考。\n"

        return prompt

    def _build_deep_search_prompt(self, target: str, count: int) -> str:
        """构建深化搜索提示词。

        Args:
            target: 目标产品
            count: 需要补充的发现数量

        Returns:
            提示词
        """
        return f"""请继续对「{target}」的技术实现进行深入分析，再提供至少 {count} 条新的推测。

请从以下角度补充：
1. 更细致的技术选型
2. 可能的性能瓶颈
3. 可扩展性考虑
4. 技术债务风险

每条发现单独一行，以「- 」开头。
格式：「[置信度] 推测内容 - 依据」
"""

    def _parse_and_store_discoveries(self, response: str, target: str) -> list[Any]:
        """解析响应并存储发现（旧版本，向后兼容）。

        使用增强的多格式解析器，支持置信度标记。

        Args:
            response: LLM 响应
            target: 目标产品

        Returns:
            发现列表
        """
        import re

        # 使用基类的增强解析方法获取原始发现
        raw_discoveries = self._parse_and_store_discoveries_from_text(
            response,
            target,
            DiscoverySource.INFERENCE,
        )

        # 处理置信度标记
        # 处理置信度标记 - 由于 Discovery 是 frozen，需要创建新对象
        processed_discoveries = []
        for discovery in raw_discoveries:
            content = discovery.content
            confidence = "中"
            clean_content = content

            # 解析置信度标记
            if "[高]" in content or "【高】" in content:
                confidence = "高"
                clean_content = re.sub(r'[\[【]高[\]】]', '', content).strip()
            elif "[低]" in content or "【低】" in content:
                confidence = "低"
                clean_content = re.sub(r'[\[【]低[\]】]', '', content).strip()
            elif "[中]" in content or "【中】" in content:
                clean_content = re.sub(r'[\[【]中[\]】]', '', content).strip()

            # 更新质量和元数据
            quality_map = {"高": 0.7, "中": 0.5, "低": 0.3}
            base_quality = quality_map.get(confidence, 0.5)

            # 创建新的 metadata（合并原有和新增）
            new_metadata = {
                **discovery.metadata,
                "confidence": confidence,
            }

            # 创建新的 Discovery 对象（因为 Discovery 是 frozen 的）
            from src.environment import Discovery
            new_discovery = Discovery(
                id=discovery.id,
                agent_type=discovery.agent_type,
                content=clean_content,
                source=discovery.source,
                quality_score=max(base_quality, discovery.quality_score),
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

            if len(evidence) < 15:
                continue

            # 解析置信度
            confidence_label = "中"
            confidence_value = 0.5
            if "[高]" in evidence or "【高】" in evidence:
                confidence_label = "高"
                confidence_value = 0.7
                evidence = evidence.replace("[高]", "").replace("【高】", "").strip()
            elif "[低]" in evidence or "【低】" in evidence:
                confidence_label = "低"
                confidence_value = 0.3
                evidence = evidence.replace("[低]", "").replace("【低】", "").strip()
            elif "[中]" in evidence or "【中】" in evidence:
                evidence = evidence.replace("[中]", "").replace("【中】", "").strip()

            # 确定信号类型（技术推测多为风险或洞察）
            signal_type = SignalType.RISK if "风险" in evidence or "瓶颈" in evidence else SignalType.INSIGHT

            # 估算强度
            strength = confidence_value * 1.2  # 强度与置信度相关

            # 确定可行动性
            actionability = Actionability.LONG_TERM  # 技术问题通常需要长期关注

            # 提取标签
            tags = ["technical", "infrastructure"]
            if "前端" in evidence or "front" in evidence.lower():
                tags.append("frontend")
            if "后端" in evidence or "back" in evidence.lower():
                tags.append("backend")
            if "性能" in evidence or "performance" in evidence.lower():
                tags.append("performance")
            if "安全" in evidence or "security" in evidence.lower():
                tags.append("security")

            signal = self.emit_signal(
                signal_type=signal_type,
                evidence=evidence,
                confidence=confidence_value,
                strength=min(1.0, strength),
                sentiment=Sentiment.NEUTRAL,
                tags=tags,
                source="technical_inference",
                actionability=actionability,
                metadata={"target": target, "confidence_label": confidence_label},
            )

            if signal:
                signals.append(signal)

        return signals
