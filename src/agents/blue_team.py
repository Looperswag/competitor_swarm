"""蓝队 Agent 模块。

负责发现产品的优势和价值。
"""

from typing import Any

from src.agents.base import BaseAgent, AgentType, AgentResult, DiscoverySource


class BlueTeamAgent(BaseAgent):
    """蓝队 Agent。

    发现产品的优势、创新点、护城河等。
    支持在线搜索以获取正面评价和成功案例。
    """

    def __init__(self, **kwargs: Any) -> None:
        """初始化蓝队 Agent。"""
        super().__init__(
            agent_type=AgentType.BLUE_TEAM,
            name="蓝队专家",
            **kwargs,
        )

    def execute(self, **context: Any) -> AgentResult:
        """执行优势分析任务。

        Args:
            **context: 执行上下文，应包含：
                - target: 目标产品/公司名称
                - red_team_arguments: 红队观点（用于辩护）

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
        prompt = self._build_blue_team_prompt(target, context, bool(search_context))

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
            f"{target} 优点 优势",
            f"{target} 好评",
            f"{target} 成功案例",
        ]

        context_parts = []
        for query in queries:
            result = self.search_context(query, max_results=5)
            if result:
                context_parts.append(f"## 搜索结果: {query}\n{result}")

        return "\n\n".join(context_parts) if context_parts else ""

    def _build_blue_team_prompt(
        self, target: str, context: dict[str, Any], has_search: bool = False
    ) -> str:
        """构建蓝队分析提示词。

        Args:
            target: 目标产品
            context: 执行上下文
            has_search: 是否有搜索结果

        Returns:
            提示词
        """
        prompt = f"""请对「{target}」进行优势分析（蓝队视角）。

你的任务是发现这个产品的所有闪光点和价值。从以下维度分析：

1. **核心优势**：相比竞品的独特优势、不可替代的价值
2. **创新点**：功能或体验的创新之处、行业领先的做法
3. **用户价值**：解决了什么痛点、提升了什么效率
4. **护城河**：竞争壁垒（技术/数据/网络效应/品牌等）
5. **发展潜力**：未来的增长空间、可能的演进方向
6. **用户好评**：用户表扬的关键点

请保持客观但积极地发现价值。对于每个发现，请说明：
- 优势的独特性（独特/常见/领先）
- 可持续的潜力（高/中/低）

请以结构化的方式输出，每个发现单独一行，以「- 」开头。
格式：「[独特性] 优势描述 - 持续潜力」

要求：至少提供 15-30 条正面发现。
"""

        # 如果有红队观点，要求辩护
        if "red_team_arguments" in context:
            red_args = context["red_team_arguments"]
            prompt += f"\n\n请针对以下红队批评进行辩护或澄清：\n{red_args}\n"

        if has_search:
            prompt += "\n**注意**：已提供用户正面评价搜索结果作为参考。\n"

        return prompt

    def _build_deep_search_prompt(self, target: str, count: int) -> str:
        """构建深化搜索提示词。

        Args:
            target: 目标产品
            count: 需要补充的发现数量

        Returns:
            提示词
        """
        return f"""请继续对「{target}」进行优势分析，再提供至少 {count} 条新的正面发现。

请从以下角度补充：
1. 更细致的优势分析
2. 用户好评的深层原因
3. 与竞品的差异化价值
4. 长期发展潜力

每条发现单独一行，以「- 」开头。
格式：「[独特性] 优势描述 - 持续潜力」
"""

    def _parse_and_store_discoveries(self, response: str, target: str) -> list[Any]:
        """解析响应并存储发现。

        使用增强的多格式解析器，支持独特性标记。

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
            DiscoverySource.DEBATE,
        )

        # 处理独特性标记 - 由于 Discovery 是 frozen，需要创建新对象
        processed_discoveries = []
        for discovery in raw_discoveries:
            content = discovery.content
            uniqueness = "一般"

            if "独特" in content or "领先" in content or "创新" in content:
                uniqueness = "独特"
            elif "常见" in content or "普通" in content:
                uniqueness = "一般"

            # 基于独特性调整质量评分
            quality_map = {"独特": 0.8, "领先": 0.75, "一般": 0.5}
            base_quality = quality_map.get(uniqueness, 0.6)

            # 创建新的 metadata（合并原有和新增）
            new_metadata = {
                **discovery.metadata,
                "uniqueness": uniqueness,
                "side": "blue",
            }

            # 创建新的 Discovery 对象（因为 Discovery 是 frozen 的）
            from src.environment import Discovery
            new_discovery = Discovery(
                id=discovery.id,
                agent_type=discovery.agent_type,
                content=discovery.content,
                source=discovery.source,
                quality_score=max(base_quality, discovery.quality_score),
                references=discovery.references,
                metadata=new_metadata,
                timestamp=discovery.timestamp,
            )
            processed_discoveries.append(new_discovery)

        return processed_discoveries
