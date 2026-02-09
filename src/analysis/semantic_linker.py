"""语义关联模块。

通过语义相似度识别跨 Agent/维度的关联，替代显式引用机制。

核心思想：
- 不依赖 Agent 主动引用其他发现 ID
- 通过 LLM 评估语义相似度自动识别关联
- 为 Elite Agent 提供丰富的跨维度关联数据
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 尝试导入环境相关模块
from src.environment import Discovery


@dataclass
class CrossDimensionLink:
    """跨维度关联。

    表示来自不同维度的两个发现之间存在语义关联。

    Attributes:
        discovery_a: 第一个发现（来自维度 A）
        discovery_b: 第二个发现（来自维度 B）
        agent_a: Agent A 类型
        agent_b: Agent B 类型
        similarity: 相似度分数 (0.0-1.0)
        connection_type: 关联类型（complementary, conflicting, reinforcing, causal）
        rationale: 关联理由
    """

    discovery_a: Discovery
    discovery_b: Discovery
    agent_a: str
    agent_b: str
    similarity: float
    connection_type: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "discovery_a_id": self.discovery_a.id,
            "discovery_b_id": self.discovery_b.id,
            "discovery_a_content": self.discovery_a.content[:200],
            "discovery_b_content": self.discovery_b.content[:200],
            "agent_a": self.agent_a,
            "agent_b": self.agent_b,
            "similarity": self.similarity,
            "connection_type": self.connection_type,
            "rationale": self.rationale,
        }


class SemanticLinker:
    """语义关联器。

    通过 LLM 评估跨维度发现之间的语义相似度和关联类型。
    """

    # 连接类型定义
    CONNECTION_TYPES = [
        "complementary",  # 互补：两者相互补充
        "conflicting",    # 冲突：两者存在矛盾
        "reinforcing",    # 强化：两者相互支持
        "causal",         # 因果：两者存在因果关系
    ]

    # 默认配置（降低阈值以获得更多关联）
    DEFAULT_MIN_SIMILARITY = 0.2
    DEFAULT_MAX_CANDIDATES_PER_PAIR = 5  # 每对 Agent 最多 5 个关联
    DEFAULT_TOP_DISCOVERIES_PER_AGENT = 10  # 每个 Agent 取前 10 个发现

    def __init__(self, llm_client: Any, system_prompt: str = ""):
        """初始化语义关联器。

        Args:
            llm_client: LLM 客户端
            system_prompt: 系统提示词（用于评估相似度）
        """
        self._llm_client = llm_client
        self._system_prompt = system_prompt or self._default_system_prompt()

    def _default_system_prompt(self) -> str:
        """获取默认系统提示词。"""
        return """你是一个专业的竞品分析专家，擅长识别不同分析维度之间的关联。

你的任务是评估两个来自不同维度的发现之间是否存在有意义的关联。

关联类型：
- complementary (互补): 两者相互补充，共同构成更完整的图景
- conflicting (冲突): 两者存在矛盾或对立
- reinforcing (强化): 两者相互支持，增强同一结论
- causal (因果): 两者存在因果关系（一个导致另一个）

请以 JSON 格式返回评估结果，包含：
- similarity: 相似度分数 (0.0-1.0)
- connection_type: 关联类型
- rationale: 简短理由说明"""

    def find_cross_dimension_links(
        self,
        discoveries: list[Discovery],
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        max_links_per_agent_pair: int = DEFAULT_MAX_CANDIDATES_PER_PAIR,
        top_per_agent: int = DEFAULT_TOP_DISCOVERIES_PER_AGENT,
    ) -> list[CrossDimensionLink]:
        """找出跨维度的语义关联。

        使用混合策略：
        1. 关键词匹配（快速，低成本）
        2. LLM 语义评估（深度，高质量）

        Args:
            discoveries: 所有发现列表
            min_similarity: 最低相似度阈值
            max_links_per_agent_pair: 每对 Agent 最多返回的关联数
            top_per_agent: 每个 Agent 考虑的高质量发现数量

        Returns:
            跨维度关联列表
        """
        # 1. 按 Agent 分组并筛选高质量发现
        agent_discoveries = self._group_and_filter_discoveries(
            discoveries, top_per_agent
        )

        # 2. 获取所有 Agent 类型
        agent_types = list(agent_discoveries.keys())

        # 3. 如果少于 2 个 Agent，无法形成跨维度关联
        if len(agent_types) < 2:
            return []

        # 4. 生成所有 Agent 对的组合
        from itertools import combinations

        links = []
        for agent_a, agent_b in combinations(agent_types, 2):
            # 找出这对 Agent 之间的关联（混合策略）
            pair_links = self._find_links_between_agents_hybrid(
                agent_discoveries[agent_a],
                agent_discoveries[agent_b],
                agent_a,
                agent_b,
                min_similarity,
                max_links_per_agent_pair,
            )
            links.extend(pair_links)

        # 5. 按相似度排序
        links.sort(key=lambda x: x.similarity, reverse=True)

        return links

    def _group_and_filter_discoveries(
        self,
        discoveries: list[Discovery],
        top_per_agent: int,
    ) -> dict[str, list[Discovery]]:
        """按 Agent 分组并筛选高质量发现。

        Args:
            discoveries: 所有发现
            top_per_agent: 每个 Agent 保留的发现数量

        Returns:
            分组的发现字典
        """
        grouped: dict[str, list[Discovery]] = {}

        for discovery in discoveries:
            agent_type = discovery.agent_type
            if agent_type not in grouped:
                grouped[agent_type] = []
            grouped[agent_type].append(discovery)

        # 每个 Agent 只保留高质量的发现
        for agent_type in grouped:
            # 按质量评分排序
            grouped[agent_type].sort(
                key=lambda d: d.quality_score, reverse=True
            )
            # 只保留前 N 个
            grouped[agent_type] = grouped[agent_type][:top_per_agent]

        return grouped

    def _find_links_between_agents_hybrid(
        self,
        discoveries_a: list[Discovery],
        discoveries_b: list[Discovery],
        agent_a: str,
        agent_b: str,
        min_similarity: float,
        max_links: int,
    ) -> list[CrossDimensionLink]:
        """使用混合策略找出两个 Agent 之间的关联。

        混合策略：
        1. 先用关键词匹配快速筛选（低成本）
        2. 对匹配结果进行 LLM 深度评估（高质量）

        Args:
            discoveries_a: Agent A 的发现列表
            discoveries_b: Agent B 的发现列表
            agent_a: Agent A 类型
            agent_b: Agent B 类型
            min_similarity: 最低相似度
            max_links: 最大关联数

        Returns:
            跨维度关联列表
        """
        links = []

        if not discoveries_a or not discoveries_b:
            return links

        # 第一步：关键词匹配快速筛选
        candidate_pairs = self._keyword_match_pairs(
            discoveries_a, discoveries_b
        )

        if not candidate_pairs:
            # 如果没有关键词匹配，使用高质量发现进行 LLM 评估
            top_a = discoveries_a[:min(5, len(discoveries_a))]
            top_b = discoveries_b[:min(5, len(discoveries_b))]
            # 创建配对：(idx_a, idx_b, match_score)
            from itertools import product
            candidate_pairs = [(i, j, 0.3) for i, _ in enumerate(top_a) for j, _ in enumerate(top_b)]

        # 第二步：对候选配对进行 LLM 深度评估
        batch_result = self._batch_evaluate_similarity(
            [discoveries_a[idx_a] for idx_a, idx_b, _ in candidate_pairs],
            [discoveries_b[idx_b] for idx_a, idx_b, _ in candidate_pairs],
            agent_a,
            agent_b,
            min_similarity,
        )

        # 筛选高于阈值的关联
        valid_links = [r for r in batch_result if r["similarity"] >= min_similarity]

        # 按相似度排序并限制数量
        valid_links.sort(key=lambda x: x["similarity"], reverse=True)
        valid_links = valid_links[:max_links]

        # 转换为 CrossDimensionLink 对象
        for i, result in enumerate(valid_links):
            if i < len(candidate_pairs):
                idx_a, idx_b, _ = candidate_pairs[i]
                links.append(CrossDimensionLink(
                    discovery_a=discoveries_a[idx_a],
                    discovery_b=discoveries_b[idx_b],
                    agent_a=agent_a,
                    agent_b=agent_b,
                    similarity=result["similarity"],
                    connection_type=result["connection_type"],
                    rationale=result["rationale"],
                ))

        return links

    def _keyword_match_pairs(
        self,
        discoveries_a: list[Discovery],
        discoveries_b: list[Discovery],
    ) -> list[tuple[int, int, float]]:
        """通过关键词匹配发现候选关联配对。

        Args:
            discoveries_a: Agent A 的发现列表
            discoveries_b: Agent B 的发现列表

        Returns:
            候选配对列表，每个元素为 (idx_a, idx_b, match_score)
        """
        import re
        from collections import Counter
        from itertools import product

        # 提取关键词（中文词语和英文单词）
        def extract_keywords(text: str) -> list[str]:
            # 英文单词（3个字母以上）
            english = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
            # 中文词汇（简单分词：连续的汉字）
            chinese = re.findall(r'[\u4e00-\u9fff]{2,}', text)
            return english + chinese

        # 为每个发现构建关键词集
        keywords_a = [
            (i, set(extract_keywords(d.content)))
            for i, d in enumerate(discoveries_a)
        ]
        keywords_b = [
            (j, set(extract_keywords(d.content)))
            for j, d in enumerate(discoveries_b)
        ]

        # 计算关键词重叠度
        candidate_pairs = []
        for (i, kw_a), (j, kw_b) in product(keywords_a, keywords_b):
            if not kw_a or not kw_b:
                continue

            # Jaccard 相似度
            intersection = len(kw_a & kw_b)
            union = len(kw_a | kw_b)

            if intersection > 0:
                match_score = intersection / union if union > 0 else 0
                # 至少要有一定程度的重叠
                if match_score >= 0.15 or intersection >= 2:
                    candidate_pairs.append((i, j, match_score))

        # 按匹配度排序
        candidate_pairs.sort(key=lambda x: x[2], reverse=True)

        # 只保留前 20 个候选配对
        return candidate_pairs[:20]

    def _find_links_between_agents(
        self,
        discoveries_a: list[Discovery],
        discoveries_b: list[Discovery],
        agent_a: str,
        agent_b: str,
        min_similarity: float,
        max_links: int,
    ) -> list[CrossDimensionLink]:
        """找出两个 Agent 之间的关联。

        Args:
            discoveries_a: Agent A 的发现列表
            discoveries_b: Agent B 的发现列表
            agent_a: Agent A 类型
            agent_b: Agent B 类型
            min_similarity: 最低相似度
            max_links: 最大关联数

        Returns:
            跨维度关联列表
        """
        links = []

        # 如果任一列表为空，直接返回
        if not discoveries_a or not discoveries_b:
            return links

        # 构建批量评估请求
        batch_result = self._batch_evaluate_similarity(
            discoveries_a, discoveries_b, agent_a, agent_b, min_similarity
        )

        # 筛选高于阈值的关联
        valid_links = [r for r in batch_result if r["similarity"] >= min_similarity]

        # 按相似度排序并限制数量
        valid_links.sort(key=lambda x: x["similarity"], reverse=True)
        valid_links = valid_links[:max_links]

        # 转换为 CrossDimensionLink 对象
        for result in valid_links:
            links.append(CrossDimensionLink(
                discovery_a=discoveries_a[result["idx_a"]],
                discovery_b=discoveries_b[result["idx_b"]],
                agent_a=agent_a,
                agent_b=agent_b,
                similarity=result["similarity"],
                connection_type=result["connection_type"],
                rationale=result["rationale"],
            ))

        return links

    def _batch_evaluate_similarity(
        self,
        discoveries_a: list[Discovery],
        discoveries_b: list[Discovery],
        agent_a: str,
        agent_b: str,
        min_similarity: float,
    ) -> list[dict[str, Any]]:
        """批量评估两组发现之间的相似度。

        Args:
            discoveries_a: Agent A 的发现列表
            discoveries_b: Agent B 的发现列表
            agent_a: Agent A 类型
            agent_b: Agent B 类型
            min_similarity: 最低相似度（用于早期筛选）

        Returns:
            评估结果列表
        """
        results = []

        # 限制每次评估的配对数量（避免 token 消耗过大）
        max_pairs_per_request = 10

        # 生成所有配对
        from itertools import product

        all_pairs = list(product(enumerate(discoveries_a), enumerate(discoveries_b)))

        # 分批处理
        for batch_start in range(0, len(all_pairs), max_pairs_per_request):
            batch = all_pairs[batch_start:batch_start + max_pairs_per_request]
            batch_results = self._evaluate_pairs_batch(batch, agent_a, agent_b)
            results.extend(batch_results)

        return results

    def _evaluate_pairs_batch(
        self,
        pairs: list[tuple[tuple[int, Discovery], tuple[int, Discovery]]],
        agent_a: str,
        agent_b: str,
    ) -> list[dict[str, Any]]:
        """评估一批配对的相似度。

        Args:
            pairs: 配对列表，每个元素是 ((idx_a, discovery_a), (idx_b, discovery_b))
            agent_a: Agent A 类型
            agent_b: Agent B 类型

        Returns:
            评估结果列表
        """
        # 构建评估提示
        prompt = self._build_evaluation_prompt(pairs, agent_a, agent_b)

        try:
            # 调用 LLM
            from src.llm import Message

            response = self._llm_client.chat(
                messages=[Message(role="user", content=prompt)],
                system_prompt=self._system_prompt,
            )

            # 解析响应
            return self._parse_evaluation_response(response.content, len(pairs))

        except Exception as e:
            # 评估失败时返回低相似度结果
            logger.warning(f"Semantic evaluation failed: {e}")
            return [{
                "idx_a": pair[0][0],
                "idx_b": pair[1][0],
                "similarity": 0.0,
                "connection_type": "complementary",
                "rationale": f"Evaluation failed: {e}",
            } for pair in pairs]

    def _build_evaluation_prompt(
        self,
        pairs: list[tuple[tuple[int, Discovery], tuple[int, Discovery]]],
        agent_a: str,
        agent_b: str,
    ) -> str:
        """构建评估提示词。

        Args:
            pairs: 配对列表
            agent_a: Agent A 类型
            agent_b: Agent B 类型

        Returns:
            提示词
        """
        lines = [
            f"请评估以下来自「{agent_a}」和「{agent_b}」两个维度的发现之间的关联。",
            "",
            f"对于每一对发现，请以 JSON 数组格式返回评估结果：",
            "[",
            '  {"index": 0, "similarity": 0.0-1.0, "connection_type": "类型", "rationale": "理由"},',
            "  ...",
            "]",
            "",
            "发现配对：",
            "",
        ]

        for i, ((idx_a, disc_a), (idx_b, disc_b)) in enumerate(pairs):
            # 截断过长的内容
            content_a = disc_a.content[:150] + "..." if len(disc_a.content) > 150 else disc_a.content
            content_b = disc_b.content[:150] + "..." if len(disc_b.content) > 150 else disc_b.content

            lines.extend([
                f"【配对 {i}】",
                f"  {agent_a}: {content_a}",
                f"  {agent_b}: {content_b}",
                "",
            ])

        lines.append("请返回 JSON 数组格式的评估结果。")

        return "\n".join(lines)

    def _parse_evaluation_response(
        self,
        response: str,
        expected_count: int,
    ) -> list[dict[str, Any]]:
        """解析评估响应。

        Args:
            response: LLM 响应
            expected_count: 预期的结果数量

        Returns:
            解析后的结果列表
        """
        import json
        import re

        # 尝试提取 JSON 代码块
        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response, re.DOTALL)
        if json_match:
            try:
                results = json.loads(json_match.group(1))
                return self._normalize_results(results, expected_count)
            except json.JSONDecodeError:
                pass

        # 尝试直接解析 JSON
        try:
            stripped = response.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                results = json.loads(stripped)
                return self._normalize_results(results, expected_count)
        except json.JSONDecodeError:
            pass

        # 解析失败，返回空结果
        return []

    def _normalize_results(
        self,
        results: list[Any],
        expected_count: int,
    ) -> list[dict[str, Any]]:
        """标准化结果格式。

        Args:
            results: 解析后的结果
            expected_count: 预期的数量

        Returns:
            标准化的结果列表
        """
        normalized = []

        for i, result in enumerate(results):
            if not isinstance(result, dict):
                continue

            normalized.append({
                "idx_a": result.get("index", i),  # 使用配对索引
                "idx_b": result.get("index", i),
                "similarity": float(result.get("similarity", 0.0)),
                "connection_type": result.get("connection_type", "complementary"),
                "rationale": result.get("rationale", "")[:200],  # 限制理由长度
            })

        return normalized[:expected_count]

    def format_links_for_prompt(
        self,
        links: list[CrossDimensionLink],
        max_links: int = 10,
    ) -> str:
        """格式化关联为提示词字符串。

        Args:
            links: 跨维度关联列表
            max_links: 最多显示的关联数

        Returns:
            格式化的字符串
        """
        if not links:
            return "暂无跨维度语义关联。"

        lines = [
            "## 跨维度语义关联（按相似度排序）",
            "",
            f"基于语义分析发现 {len(links)} 个跨维度关联：",
            "",
        ]

        for i, link in enumerate(links[:max_links], 1):
            # 截断内容
            content_a = link.discovery_a.content[:100] + "..." if len(link.discovery_a.content) > 100 else link.discovery_a.content
            content_b = link.discovery_b.content[:100] + "..." if len(link.discovery_b.content) > 100 else link.discovery_b.content

            # 连接类型中文映射
            type_map = {
                "complementary": "互补",
                "conflicting": "冲突",
                "reinforcing": "强化",
                "causal": "因果",
            }
            type_zh = type_map.get(link.connection_type, link.connection_type)

            lines.extend([
                f"### 关联 {i}（相似度: {link.similarity:.2f}，{type_zh}）",
                f"",
                f"**[{link.agent_a}]** {content_a}",
                f"",
                f"**[{link.agent_b}]** {content_b}",
                f"",
                f"**关联理由**: {link.rationale}",
                "",
            ])

        if len(links) > max_links:
            lines.append(f"*（还有 {len(links) - max_links} 个关联未显示）*")

        return "\n".join(lines)
