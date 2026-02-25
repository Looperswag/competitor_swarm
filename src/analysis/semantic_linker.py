"""语义关联模块。

通过文本相似度识别跨 Agent/维度的关联，替代显式引用机制。

核心思想：
- 不依赖 Agent 主动引用其他发现 ID
- 通过关键词重叠度 + 情感极性启发式规则自动识别关联
- 为 Elite Agent 提供丰富的跨维度关联数据
- 无 LLM 调用，纯算法实现，耗时 < 0.1s
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass
from itertools import combinations, product
from typing import Any

logger = logging.getLogger(__name__)

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


# ---- 情感/冲突信号词表 ----

_NEGATIVE_MARKERS = frozenset({
    "缺点", "不足", "问题", "风险", "劣势", "弱点", "差", "落后", "困难", "缺乏",
    "投诉", "差评", "难以", "不够", "瓶颈", "威胁", "下降", "不佳", "薄弱",
    "weakness", "risk", "issue", "problem", "lack", "poor", "decline", "threat",
    "negative", "disadvantage", "complaint", "difficult",
})

_POSITIVE_MARKERS = frozenset({
    "优势", "优点", "强项", "领先", "创新", "增长", "突破", "高效", "满意",
    "好评", "提升", "机会", "潜力", "成功", "出色", "卓越", "便捷",
    "strength", "advantage", "growth", "innovation", "leading", "opportunity",
    "excellent", "efficient", "success", "positive", "impressive",
})

_CAUSAL_MARKERS = frozenset({
    "导致", "因此", "所以", "因为", "由于", "引起", "造成", "促使", "推动",
    "影响", "带来", "结果", "原因",
    "cause", "result", "therefore", "because", "lead", "driven", "impact",
    "consequence", "effect",
})

# 通用停用词，计算相似度时排除
_STOP_WORDS = frozenset({
    "产品", "功能", "用户", "可以", "应该", "可能", "需要", "我们", "他们",
    "进行", "使用", "提供", "方面", "目前", "通过", "其中", "以及", "对于",
    "the", "this", "that", "with", "from", "have", "will", "would", "could",
    "should", "feature", "product", "market", "analysis", "also", "very",
    "more", "some", "about", "which", "their", "there", "these", "other",
})

# 关键词提取正则
_KW_PATTERN = re.compile(r'\b[a-zA-Z]{3,}\b|[\u4e00-\u9fff]{2,}')


def _extract_keywords(text: str) -> set[str]:
    """提取有效关键词（排除停用词）。"""
    raw = _KW_PATTERN.findall(text.lower())
    return {w for w in raw if w not in _STOP_WORDS}


def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard 相似度。"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _overlap_coefficient(set_a: set[str], set_b: set[str]) -> float:
    """重叠系数（Szymkiewicz–Simpson），对长度不对称的文本更公平。"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    return intersection / min(len(set_a), len(set_b))


def _combined_similarity(set_a: set[str], set_b: set[str]) -> float:
    """综合相似度 = 0.5 × Jaccard + 0.5 × Overlap，兼顾严格匹配与短文本场景。"""
    return 0.5 * _jaccard_similarity(set_a, set_b) + 0.5 * _overlap_coefficient(set_a, set_b)


def _has_marker(keywords: set[str], markers: frozenset[str]) -> bool:
    """检查关键词集是否包含指定标记词。"""
    return bool(keywords & markers)


def _infer_connection_type(
    kw_a: set[str],
    kw_b: set[str],
    shared: set[str],
) -> tuple[str, str]:
    """基于关键词启发式推断关联类型和理由。

    Returns:
        (connection_type, rationale)
    """
    neg_a = _has_marker(kw_a, _NEGATIVE_MARKERS)
    neg_b = _has_marker(kw_b, _NEGATIVE_MARKERS)
    pos_a = _has_marker(kw_a, _POSITIVE_MARKERS)
    pos_b = _has_marker(kw_b, _POSITIVE_MARKERS)
    causal_a = _has_marker(kw_a, _CAUSAL_MARKERS)
    causal_b = _has_marker(kw_b, _CAUSAL_MARKERS)

    shared_sample = ", ".join(sorted(shared)[:5])

    # 一正一负 → 冲突
    if (pos_a and neg_b) or (neg_a and pos_b):
        return "conflicting", f"正负观点在共同主题「{shared_sample}」上存在矛盾"

    # 都正或都负 → 强化
    if (pos_a and pos_b) or (neg_a and neg_b):
        return "reinforcing", f"多维度在「{shared_sample}」上的判断一致"

    # 因果信号
    if causal_a or causal_b:
        return "causal", f"存在因果推理链条，关键词交集：{shared_sample}"

    # 默认：互补
    return "complementary", f"不同维度在「{shared_sample}」上提供互补视角"


class SemanticLinker:
    """语义关联器（纯算法版本，无 LLM 调用）。

    通过关键词 Jaccard + Overlap 混合相似度自动识别关联，
    并用情感极性启发式推断关联类型。整体耗时 < 0.1s。
    """

    DEFAULT_MIN_SIMILARITY = 0.15
    DEFAULT_MAX_CANDIDATES_PER_PAIR = 5
    DEFAULT_TOP_DISCOVERIES_PER_AGENT = 10

    def __init__(self, llm_client: Any = None, system_prompt: str = ""):
        """初始化语义关联器。

        Args:
            llm_client: 保留参数以兼容旧调用方，但不再使用
            system_prompt: 保留参数以兼容旧调用方，但不再使用
        """
        # llm_client 和 system_prompt 保留签名兼容性，不再使用
        self._llm_client = llm_client

    def find_cross_dimension_links(
        self,
        discoveries: list[Discovery],
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        max_links_per_agent_pair: int = DEFAULT_MAX_CANDIDATES_PER_PAIR,
        top_per_agent: int = DEFAULT_TOP_DISCOVERIES_PER_AGENT,
    ) -> list[CrossDimensionLink]:
        """找出跨维度的语义关联（纯算法，无 LLM 调用）。

        策略：
        1. 按 Agent 分组，筛选高质量发现
        2. 对每对 Agent 组合，用关键词相似度匹配
        3. 用启发式规则推断关联类型

        Args:
            discoveries: 所有发现列表
            min_similarity: 最低相似度阈值
            max_links_per_agent_pair: 每对 Agent 最多返回的关联数
            top_per_agent: 每个 Agent 考虑的高质量发现数量

        Returns:
            跨维度关联列表
        """
        agent_discoveries = self._group_and_filter_discoveries(
            discoveries, top_per_agent
        )

        agent_types = list(agent_discoveries.keys())
        if len(agent_types) < 2:
            return []

        # 预计算所有发现的关键词集（避免重复提取）
        kw_cache: dict[str, set[str]] = {}
        for agent_type, discs in agent_discoveries.items():
            for disc in discs:
                kw_cache[disc.id] = _extract_keywords(disc.content)

        links: list[CrossDimensionLink] = []
        for agent_a, agent_b in combinations(agent_types, 2):
            pair_links = self._find_links_for_pair(
                agent_discoveries[agent_a],
                agent_discoveries[agent_b],
                agent_a,
                agent_b,
                kw_cache,
                min_similarity,
                max_links_per_agent_pair,
            )
            links.extend(pair_links)

        links.sort(key=lambda x: x.similarity, reverse=True)
        return links

    def _group_and_filter_discoveries(
        self,
        discoveries: list[Discovery],
        top_per_agent: int,
    ) -> dict[str, list[Discovery]]:
        """按 Agent 分组并筛选高质量发现。"""
        grouped: dict[str, list[Discovery]] = {}
        for discovery in discoveries:
            grouped.setdefault(discovery.agent_type, []).append(discovery)

        for agent_type in grouped:
            grouped[agent_type].sort(
                key=lambda d: d.quality_score, reverse=True
            )
            grouped[agent_type] = grouped[agent_type][:top_per_agent]

        return grouped

    def _find_links_for_pair(
        self,
        discoveries_a: list[Discovery],
        discoveries_b: list[Discovery],
        agent_a: str,
        agent_b: str,
        kw_cache: dict[str, set[str]],
        min_similarity: float,
        max_links: int,
    ) -> list[CrossDimensionLink]:
        """计算一对 Agent 之间的跨维度关联（纯算法）。"""
        if not discoveries_a or not discoveries_b:
            return []

        scored: list[tuple[Discovery, Discovery, float, set[str]]] = []

        for disc_a in discoveries_a:
            kw_a = kw_cache.get(disc_a.id, set())
            if not kw_a:
                continue
            for disc_b in discoveries_b:
                kw_b = kw_cache.get(disc_b.id, set())
                if not kw_b:
                    continue

                sim = _combined_similarity(kw_a, kw_b)
                if sim >= min_similarity:
                    shared = kw_a & kw_b
                    scored.append((disc_a, disc_b, sim, shared))

        # 按相似度降序，取 top-N
        scored.sort(key=lambda x: x[2], reverse=True)
        scored = scored[:max_links]

        links: list[CrossDimensionLink] = []
        for disc_a, disc_b, sim, shared in scored:
            kw_a = kw_cache.get(disc_a.id, set())
            kw_b = kw_cache.get(disc_b.id, set())
            conn_type, rationale = _infer_connection_type(kw_a, kw_b, shared)
            links.append(CrossDimensionLink(
                discovery_a=disc_a,
                discovery_b=disc_b,
                agent_a=agent_a,
                agent_b=agent_b,
                similarity=round(sim, 4),
                connection_type=conn_type,
                rationale=rationale,
            ))

        return links

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

        type_map = {
            "complementary": "互补",
            "conflicting": "冲突",
            "reinforcing": "强化",
            "causal": "因果",
        }

        for i, link in enumerate(links[:max_links], 1):
            content_a = link.discovery_a.content[:100] + "..." if len(link.discovery_a.content) > 100 else link.discovery_a.content
            content_b = link.discovery_b.content[:100] + "..." if len(link.discovery_b.content) > 100 else link.discovery_b.content
            type_zh = type_map.get(link.connection_type, link.connection_type)

            lines.extend([
                f"### 关联 {i}（相似度: {link.similarity:.2f}，{type_zh}）",
                "",
                f"**[{link.agent_a}]** {content_a}",
                "",
                f"**[{link.agent_b}]** {content_b}",
                "",
                f"**关联理由**: {link.rationale}",
                "",
            ])

        if len(links) > max_links:
            lines.append(f"*（还有 {len(links) - max_links} 个关联未显示）*")

        return "\n".join(lines)
