"""红队 Agent 模块。

负责批判性分析，找出产品的潜在问题。
"""

from typing import Any

from src.agents.base import BaseAgent, AgentType, AgentResult, DiscoverySource


class RedTeamAgent(BaseAgent):
    """红队 Agent。

    寻找产品的问题、缺陷、风险等。
    支持在线搜索以获取用户负面反馈和问题报告。
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化红队 Agent。"""
        super().__init__(
            agent_type=AgentType.RED_TEAM,
            name="红队专家",
            **kwargs,
        )

    def execute(self, **context: Any) -> AgentResult:
        """执行批判性分析任务。

        Args:
            **context: 执行上下文，应包含：
                - target: 目标产品/公司名称
                - blue_team_arguments: 蓝队观点（用于反驳）

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
        prompt = self._build_red_team_prompt(target, context, bool(search_context))

        # 第三步：基于现有发现进行分析
        response = self.think_with_discoveries(
            prompt,
            agent_types=["scout", "experience", "technical", "market"],
            context=context,
        )

        # 第四步：解析并存储发现
        discoveries = self._parse_and_store_discoveries(response, target)

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
            discoveries=[d.to_dict() for d in discoveries],
            handoffs_created=0,
            metadata={
                "target": target,
                "discovery_count": len(discoveries),
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
            f"{target} 问题 缺点",
            f"{target} 用户投诉",
            f"{target} 差评",
        ]

        context_parts = []
        for query in queries:
            result = self.search_context(query, max_results=5)
            if result:
                context_parts.append(f"## 搜索结果: {query}\n{result}")

        return "\n\n".join(context_parts) if context_parts else ""

    def _build_red_team_prompt(
        self, target: str, context: dict[str, Any], has_search: bool = False
    ) -> str:
        """构建红队分析提示词。

        Args:
            target: 目标产品
            context: 执行上下文
            has_search: 是否有搜索结果

        Returns:
            提示词
        """
        prompt = f"""请对「{target}」进行批判性分析（红队视角）。

你的任务是找出这个产品的所有潜在问题和风险。从以下维度分析：

1. **功能缺陷**：缺失的关键功能、功能实现不足
2. **体验问题**：用户可能遇到的困扰、学习成本、操作复杂性
3. **技术风险**：可能的性能瓶颈、安全漏洞、扩展性问题
4. **商业风险**：盈利模式的可持续性、竞争壁垒薄弱点
5. **竞品劣势**：相比主要竞品的不利之处
6. **用户抱怨**：常见投诉、负面反馈

请以批判性的思维进行分析，不要回避问题。
对于每个发现，请说明：
- 问题的严重程度（高/中/低）
- 受影响的用户群体（如有）

请以结构化的方式输出，每个发现单独一行，以「- 」开头。
格式：「[严重程度] 问题描述 - 影响说明」

要求：至少提供 15-30 条批判性发现。
"""

        # 如果有蓝队观点，要求反驳
        if "blue_team_arguments" in context:
            blue_args = context["blue_team_arguments"]
            prompt += f"\n\n请特别反驳以下蓝队观点：\n{blue_args}\n"

        if has_search:
            prompt += "\n**注意**：已提供用户负面反馈搜索结果作为参考。\n"

        return prompt

    def _build_deep_search_prompt(self, target: str, count: int) -> str:
        """构建深化搜索提示词。

        Args:
            target: 目标产品
            count: 需要补充的发现数量

        Returns:
            提示词
        """
        return f"""请继续对「{target}」进行批判性分析，再提供至少 {count} 条新的问题发现。

请从以下角度补充：
1. 更深层次的问题
2. 用户抱怨的根因分析
3. 潜在的系统性风险
4. 可能的改进建议

每条发现单独一行，以「- 」开头。
格式：「[严重程度] 问题描述 - 影响说明」
"""

    def _parse_and_store_discoveries(self, response: str, target: str) -> list[Any]:
        """解析响应并存储发现。

        使用增强的多格式解析器，支持严重程度标记。

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
            DiscoverySource.DEBATE,
        )

        # 处理严重程度标记 - 由于 Discovery 是 frozen，需要创建新对象
        processed_discoveries = []
        for discovery in raw_discoveries:
            content = discovery.content
            severity = "中"
            clean_content = content

            # 解析严重程度标记
            if "[高]" in content or "【高】" in content or "严重" in content:
                severity = "高"
                clean_content = re.sub(r'[\[【]高[\]】]', '', content).replace("严重", "").strip()
            elif "[低]" in content or "【低】" in content or "轻微" in content:
                severity = "低"
                clean_content = re.sub(r'[\[【]低[\]】]', '', content).replace("轻微", "").strip()
            elif "[中]" in content or "【中】" in content:
                clean_content = re.sub(r'[\[【]中[\]】]', '', content).strip()

            # 基于严重程度调整质量评分
            quality_map = {"高": 0.8, "中": 0.6, "低": 0.4}
            base_quality = quality_map.get(severity, 0.6)

            # 创建新的 metadata（合并原有和新增）
            new_metadata = {
                **discovery.metadata,
                "severity": severity,
                "side": "red",
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
