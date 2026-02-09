"""Agent 基类模块。

定义所有 Agent 的基础接口和通用功能。
支持 Discovery（旧版本）和 Signal（新版本）两种数据结构。
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, TYPE_CHECKING

logger = logging.getLogger(__name__)

from src.llm import LLMClient, Message, get_client
from src.environment import StigmergyEnvironment, Discovery, DiscoverySource, get_environment
from src.handoff import HandoffContext, HandoffManager, HandoffPriority, get_handoff_manager
from src.utils.config import get_config

# 尝试导入 Signal 结构
try:
    from src.schemas.signals import (
        Signal,
        SignalType,
        Dimension,
        Sentiment,
        Actionability,
    )
    SIGNALS_AVAILABLE = True
except ImportError:
    SIGNALS_AVAILABLE = False

if TYPE_CHECKING:
    from src.search.base import SearchTool, SearchTimeRange


class AgentType(str, Enum):
    """Agent 类型枚举。"""

    SCOUT = "scout"
    EXPERIENCE = "experience"
    TECHNICAL = "technical"
    MARKET = "market"
    RED_TEAM = "red_team"
    BLUE_TEAM = "blue_team"
    ELITE = "elite"


# Agent 类型到维度的映射（延迟初始化）
def _get_dimension_mapping() -> dict[AgentType, Any]:
    """获取 Agent 类型到维度的映射。"""
    if SIGNALS_AVAILABLE:
        return {
            AgentType.SCOUT: Dimension.PRODUCT,
            AgentType.EXPERIENCE: Dimension.UX,
            AgentType.TECHNICAL: Dimension.TECHNICAL,
            AgentType.MARKET: Dimension.MARKET,
        }
    return {}


AGENT_DIMENSION_MAP = _get_dimension_mapping()


class AgentProtocol(Protocol):
    """Agent 接口协议。"""

    agent_type: AgentType
    name: str

    def execute(self, **context: Any) -> Any:
        """执行 Agent 任务。"""
        ...


@dataclass
class AgentResult:
    """Agent 执行结果。"""

    agent_type: str
    agent_name: str
    discoveries: list[dict[str, Any]]
    handoffs_created: int
    thinking_process: str | None = None
    metadata: dict[str, Any] | None = None


class BaseAgent(ABC):
    """Agent 抽象基类。

    所有具体 Agent 都应该继承这个类。
    支持 Discovery（旧版本）和 Signal（新版本）两种数据结构。
    """

    # 默认结果数量限制
    MIN_DISCOVERIES: int = 15
    TARGET_DISCOVERIES: int = 30
    MAX_DISCOVERIES: int = 50

    # 默认配置
    USE_SIGNALS: bool = True  # 是否使用 Signal（新版本）

    def __init__(
        self,
        agent_type: AgentType,
        name: str,
        system_prompt: str | None = None,
        llm_client: LLMClient | None = None,
        environment: StigmergyEnvironment | None = None,
        handoff_manager: HandoffManager | None = None,
        search_tool: "SearchTool | None" = None,
    ) -> None:
        """初始化 Agent。

        Args:
            agent_type: Agent 类型
            name: Agent 名称
            system_prompt: 系统提示词
            llm_client: LLM 客户端
            environment: 共享环境
            handoff_manager: Handoff 管理器
            search_tool: 搜索工具（可选，未提供时自动初始化）
        """
        self.agent_type = agent_type
        self.name = name

        # 从配置获取 system_prompt（如果未提供）
        config = get_config()
        if system_prompt is None:
            agent_key = agent_type.value
            if hasattr(config.agents, agent_key):
                agent_config = getattr(config.agents, agent_key)
                self._system_prompt = agent_config.system_prompt
                # 从配置获取结果数量限制
                self.MIN_DISCOVERIES = getattr(agent_config, "min_discoveries", self.MIN_DISCOVERIES)
                self.TARGET_DISCOVERIES = getattr(agent_config, "target_discoveries", self.TARGET_DISCOVERIES)
                self.MAX_DISCOVERIES = getattr(agent_config, "max_discoveries", self.MAX_DISCOVERIES)
            else:
                self._system_prompt = f"You are a {name} analyzing competitors."
        else:
            self._system_prompt = system_prompt

        self._llm_client = llm_client or get_client()
        self._environment = environment or get_environment()
        self._handoff_manager = handoff_manager or get_handoff_manager()

        # 初始化搜索工具
        if search_tool is None:
            self._search_tool = self._init_search_tool(config)
        else:
            self._search_tool = search_tool

        # 获取 Agent 对应的维度
        self._dimension = AGENT_DIMENSION_MAP.get(agent_type)
        if self._dimension is None and SIGNALS_AVAILABLE:
            self._dimension = Dimension.PRODUCT

    def _init_search_tool(self, config: Any) -> "SearchTool | None":
        """根据配置初始化搜索工具。

        Args:
            config: 配置对象

        Returns:
            搜索工具实例，失败时返回 None
        """
        from src.search import get_search_tool, SearchProviderType

        search_config = config.search
        provider = search_config.provider

        try:
            # 多源搜索模式
            if provider == "multi":
                # 获取 Agent 特定的搜索配置
                agent_key = self.agent_type.value
                agent_profile = None

                if hasattr(search_config, "agent_profiles") and agent_key in search_config.agent_profiles:
                    agent_profile = search_config.agent_profiles[agent_key]

                # 获取首选搜索源
                preferred_providers = None
                if agent_profile and agent_profile.preferred_providers:
                    try:
                        preferred_providers = [
                            SearchProviderType(p) for p in agent_profile.preferred_providers
                        ]
                    except ValueError:
                        preferred_providers = None

                # 获取聚合模式
                aggregation_mode = search_config.multi_source.aggregation_mode
                if agent_profile and agent_profile.aggregation_mode:
                    aggregation_mode = agent_profile.aggregation_mode

                return get_search_tool(
                    provider="multi",
                    agent_type=agent_key,
                    preferred_providers=preferred_providers,
                    cache_enabled=search_config.multi_source.cache_enabled,
                    cache_ttl=search_config.multi_source.cache_ttl,
                    quota_enabled=search_config.multi_source.quota_enabled,
                    aggregation_mode=aggregation_mode,
                    max_parallel_providers=search_config.multi_source.max_parallel_providers,
                )

            # 单一搜索源模式（向后兼容）
            return get_search_tool(
                provider=provider,
                api_key=search_config.api_key or None,
            )

        except Exception as e:
            logger.warning(f"Failed to initialize search tool: {e}")
            return None

    @property
    def system_prompt(self) -> str:
        """获取系统提示词。"""
        return self._system_prompt

    @property
    def dimension(self) -> Any:
        """获取 Agent 对应的维度。"""
        return self._dimension

    @abstractmethod
    def execute(self, **context: Any) -> AgentResult:
        """执行 Agent 任务。

        子类必须实现此方法。

        Args:
            **context: 执行上下文

        Returns:
            Agent 执行结果
        """
        ...

    def think(
        self,
        user_message: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """通过 LLM 进行思考。

        Args:
            user_message: 用户消息
            context: 额外上下文

        Returns:
            LLM 响应内容
        """
        # 构建消息
        messages = [Message(role="user", content=user_message)]

        # 添加上下文信息
        if context:
            context_str = self._format_context(context)
            if context_str:
                messages[0] = Message(
                    role="user",
                    content=f"Context:\n{context_str}\n\nTask:\n{user_message}"
                )

        response = self._llm_client.chat(
            messages=messages,
            system_prompt=self._system_prompt,
        )

        return response.content

    def think_with_signals(
        self,
        user_message: str,
        dimensions: list[Any] | None = None,
        min_confidence: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> str:
        """基于现有信号进行思考（新版本）。

        Args:
            user_message: 用户消息
            dimensions: 相关维度，None 表示全部
            min_confidence: 最低置信度
            context: 额外上下文

        Returns:
            LLM 响应内容
        """
        if not SIGNALS_AVAILABLE or not self.USE_SIGNALS:
            return self.think_with_discoveries(
                user_message,
                [d.value for d in dimensions] if dimensions else None,
                context,
            )

        # 获取相关信号
        signals = []
        if dimensions:
            for dim in dimensions:
                dim_signals = self._environment.get_signals_by_dimension(
                    dimension=dim,
                    min_confidence=min_confidence,
                    limit=10,
                )
                signals.extend(dim_signals)
        else:
            signals = self._environment.get_fresh_signals(limit=20)

        # 构建上下文
        signal_context = ""
        if signals:
            signal_context = "\n\n".join([
                f"[{s.dimension.value}] {s.evidence}"
                for s in signals[:20]
            ])

        # 合并上下文
        full_context = {**(context or {})}
        if signal_context:
            full_context["_signals"] = signal_context

        return self.think(user_message, full_context)

    def think_with_discoveries(
        self,
        user_message: str,
        agent_types: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """基于现有发现进行思考（旧版本，向后兼容）。

        Args:
            user_message: 用户消息
            agent_types: 相关 Agent 类型，None 表示全部
            context: 额外上下文

        Returns:
            LLM 响应内容
        """
        # 获取相关发现
        discoveries = self._environment.get_relevant_discoveries(
            agent_type=agent_types[0] if agent_types and len(agent_types) == 1 else None,
            limit=20,
        )

        # 构建上下文
        discovery_context = ""
        if discoveries:
            discovery_context = "\n\n".join([
                f"[{d.agent_type}] {d.content}"
                for d in discoveries
            ])

        # 合并上下文
        full_context = {**(context or {})}
        if discovery_context:
            full_context["_discoveries"] = discovery_context

        return self.think(user_message, full_context)

    # ========== Discovery 方法（向后兼容） ==========

    def add_discovery(
        self,
        content: str,
        source: DiscoverySource,
        quality_score: float = 0.5,
        references: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Discovery:
        """添加发现到环境（旧版本，向后兼容）。

        Args:
            content: 发现内容
            source: 发现来源
            quality_score: 质量评分
            references: 引用的其他发现 ID
            metadata: 额外元数据

        Returns:
            创建的发现对象
        """
        return self._environment.add_discovery(
            agent_type=self.agent_type.value,
            content=content,
            source=source,
            quality_score=quality_score,
            references=references,
            metadata=metadata or {},
        )

    # ========== Signal 方法（新版本） ==========

    def emit_signal(
        self,
        signal_type: SignalType,
        evidence: str,
        confidence: float = 0.5,
        strength: float = 0.5,
        sentiment: Sentiment = Sentiment.NEUTRAL,
        tags: list[str] | None = None,
        source: str = "",
        references: list[str] | None = None,
        actionability: Actionability = Actionability.INFORMATIONAL,
        metadata: dict[str, Any] | None = None,
    ) -> Any | None:
        """发射信号到环境（新版本）。

        Args:
            signal_type: 信号类型
            evidence: 支持证据
            confidence: 置信度 (0.0-1.0)
            strength: 信号强度 (0.0-1.0)
            sentiment: 情感倾向
            tags: 分类标签
            source: 数据来源
            references: 相关信号 ID
            actionability: 可行动性
            metadata: 额外元数据

        Returns:
            创建的 Signal 对象，如果 Signal 不可用返回 None
        """
        if not SIGNALS_AVAILABLE or not self.USE_SIGNALS:
            return None

        signal = Signal(
            id="",
            signal_type=signal_type,
            dimension=self._dimension,
            evidence=evidence,
            confidence=confidence,
            strength=strength,
            sentiment=sentiment,
            tags=tags or [],
            source=source,
            timestamp="",
            references=references or [],
            author_agent=self.agent_type.value,
            verified=False,
            debate_points=[],
            actionability=actionability,
            metadata=metadata or {},
        )

        stored_signal = self._environment.add_signal(signal)

        # 向后兼容：将 Signal 同步为 Discovery，确保旧流程可用
        try:
            if evidence:
                discovery_metadata = {
                    "signal_id": stored_signal.id,
                    "signal_type": stored_signal.signal_type.value
                    if hasattr(stored_signal, "signal_type") else "",
                    "signal_source": source,
                    **(metadata or {}),
                }
                self.add_discovery(
                    content=evidence,
                    source=DiscoverySource.ANALYSIS,
                    quality_score=confidence,
                    references=stored_signal.references,
                    metadata=discovery_metadata,
                )
        except Exception:
            # 兼容层失败不应影响主流程
            pass

        return stored_signal

    def get_signals_by_dimension(
        self,
        dimension: Any,
        min_confidence: float = 0.0,
        min_strength: float = 0.0,
        verified_only: bool = False,
        limit: int = 50,
    ) -> list[Any]:
        """根据维度获取信号（新版本）。

        Args:
            dimension: 维度枚举
            min_confidence: 最低置信度
            min_strength: 最低强度
            verified_only: 是否仅返回已验证信号
            limit: 最大返回数量

        Returns:
            信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        return self._environment.get_signals_by_dimension(
            dimension=dimension,
            min_confidence=min_confidence,
            min_strength=min_strength,
            verified_only=verified_only,
            limit=limit,
        )

    def get_signals_by_type(
        self,
        signal_type: Any,
        min_strength: float = 0.0,
        verified_only: bool = False,
        limit: int = 50,
    ) -> list[Any]:
        """根据类型获取信号（新版本）。

        Args:
            signal_type: 信号类型枚举
            min_strength: 最低强度
            verified_only: 是否仅返回已验证信号
            limit: 最大返回数量

        Returns:
            信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        return self._environment.get_signals_by_type(
            signal_type=signal_type,
            min_strength=min_strength,
            verified_only=verified_only,
            limit=limit,
        )

    def get_related_signals(
        self,
        signal_id: str,
        max_distance: int = 2,
        limit: int = 20,
    ) -> list[Any]:
        """获取相关信号（新版本）。

        Args:
            signal_id: 起始信号 ID
            max_distance: 最大关联距离
            limit: 最大返回数量

        Returns:
            相关信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        return self._environment.get_related_signals(
            signal_id=signal_id,
            max_distance=max_distance,
            limit=limit,
        )

    def get_fresh_signals(
        self,
        max_age_hours: int = 24,
        limit: int = 50,
    ) -> list[Any]:
        """获取新鲜信号（新版本）。

        Args:
            max_age_hours: 最大年龄（小时）
            limit: 最大返回数量

        Returns:
            新鲜信号列表
        """
        if not SIGNALS_AVAILABLE:
            return []

        return self._environment.get_fresh_signals(
            max_age_hours=max_age_hours,
            limit=limit,
        )

    # ========== Handoff 方法 ==========

    def create_handoff(
        self,
        to_agent: str,
        context: HandoffContext,
        priority: HandoffPriority = HandoffPriority.MEDIUM,
    ) -> None:
        """创建任务交接。

        Args:
            to_agent: 目标 Agent 类型
            context: 交接上下文
            priority: 优先级
        """
        self._handoff_manager.create_handoff(
            from_agent=self.agent_type.value,
            to_agent=to_agent,
            context=context,
            priority=priority,
        )

    def get_pending_handoffs(self) -> list[HandoffContext]:
        """获取待处理的交接。

        Returns:
            交接上下文列表
        """
        return self._handoff_manager.get_context_for_agent(self.agent_type.value)

    # ========== 搜索方法 ==========

    def search_context(
        self,
        query: str,
        max_results: int = 10,
        check_freshness: bool = True,
        max_age_hours: int = 24,
        timeout: float = 45.0,
    ) -> str:
        """搜索外部上下文，返回格式化的结果字符串。

        Args:
            query: 搜索查询
            max_results: 最大结果数
            check_freshness: 是否检查新鲜度
            max_age_hours: 最大允许年龄（小时）
            timeout: 单个搜索超时时间（秒）

        Returns:
            格式化的搜索结果字符串
        """
        import logging
        import time

        logger = logging.getLogger(__name__)

        if not self._search_tool:
            logger.warning(f"[{self.agent_type.value}] Search tool not available for query: {query[:50]}...")
            return ""

        search_start = time.time()

        try:
            from src.search.base import SearchTimeRange

            # 使用 concurrent.futures 实现超时（跨平台兼容）
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

            def _do_search():
                return self._search_tool.search(
                    query=query,
                    time_range=SearchTimeRange.ONE_YEAR,
                    max_results=max_results,
                )

            # 使用线程池执行搜索并设置超时
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_search)
                try:
                    results = future.result(timeout=timeout)
                except FuturesTimeoutError:
                    elapsed = time.time() - search_start
                    logger.warning(
                        f"[{self.agent_type.value}] Search '{query[:40]}...' "
                        f"timed out after {elapsed:.2f}s (limit: {timeout}s)"
                    )
                    return ""

            # 如果需要检查新鲜度
            if check_freshness:
                results = [
                    r for r in results
                    if self._is_result_fresh(r, max_age_hours)
                ]

            formatted = []
            for i, r in enumerate(results, 1):
                formatted.append(f"{i}. {r.title}")
                formatted.append(f"   来源: {r.site_name or r.url}")
                formatted.append(f"   摘要: {r.summary}")
                formatted.append(f"   链接: {r.url}")
                formatted.append("")

            elapsed = time.time() - search_start
            logger.info(
                f"[{self.agent_type.value}] Search '{query[:40]}...' "
                f"completed in {elapsed:.2f}s, {len(results)} results"
            )

            return "\n".join(formatted)

        except Exception as e:
            # 搜索失败不应阻断 Agent 执行
            elapsed = time.time() - search_start
            logger.error(
                f"[{self.agent_type.value}] Search '{query[:40]}...' "
                f"failed after {elapsed:.2f}s: {e}"
            )
            return ""  # 返回空字符串而非错误信息，避免污染 LLM 上下文

    def search_context_async(
        self,
        queries: list[str],
        max_results: int = 10,
        timeout: float = 45.0,
    ) -> dict[str, str]:
        """并行执行多个搜索查询。

        Args:
            queries: 搜索查询列表
            max_results: 每个查询的最大结果数
            timeout: 单个搜索超时时间（秒）

        Returns:
            查询到结果的映射字典
        """
        import concurrent.futures
        import logging

        logger = logging.getLogger(__name__)

        if not self._search_tool:
            logger.warning(f"[{self.agent_type.value}] Search tool not available")
            return {}

        results = {}

        def search_one(query: str) -> tuple[str, str]:
            """执行单个搜索。"""
            result = self.search_context(
                query=query,
                max_results=max_results,
                timeout=timeout,
            )
            return (query, result)

        # 使用线程池并行执行搜索
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(3, len(queries))
        ) as executor:
            future_to_query = {
                executor.submit(search_one, q): q
                for q in queries
            }

            for future in concurrent.futures.as_completed(
                future_to_query, timeout=timeout * len(queries)
            ):
                try:
                    query, result = future.result()
                    if result:
                        results[query] = result
                except Exception as e:
                    query = future_to_query[future]
                    logger.warning(
                        f"[{self.agent_type.value}] Parallel search '{query[:30]}...' "
                        f"failed: {e}"
                    )

        logger.info(
            f"[{self.agent_type.value}] Parallel search: {len(results)}/{len(queries)} "
            f"queries succeeded"
        )

        return results

    def _is_result_fresh(self, result: Any, max_age_hours: int) -> bool:
        """检查搜索结果是否新鲜。

        Args:
            result: 搜索结果
            max_age_hours: 最大年龄（小时）

        Returns:
            是否新鲜
        """
        # 简化实现：假设所有结果都是新鲜的
        # 实际应该检查结果的发布时间
        return True

    # ========== 辅助方法 ==========

    def _ensure_min_discoveries(
        self,
        discoveries: list[Any],
        target: str,
        context: dict[str, Any],
        prompt_builder: "Callable[[str, int], str] | None" = None,
    ) -> list[Any]:
        """确保满足最小发现数量。

        如果当前发现数量不足，进行深化搜索。

        Args:
            discoveries: 当前发现列表
            target: 目标产品
            context: 执行上下文
            prompt_builder: 自定义提示词构建函数

        Returns:
            发现列表（可能包含新增的发现）
        """
        if len(discoveries) >= self.MIN_DISCOVERIES:
            return discoveries

        # 数量不足，进行深化搜索
        additional_count = self.TARGET_DISCOVERIES - len(discoveries)

        if prompt_builder:
            deep_prompt = prompt_builder(target, additional_count)
        else:
            deep_prompt = self._build_deep_search_prompt(target, additional_count)

        # 执行深化分析
        deep_response = self.think_with_discoveries(
            deep_prompt,
            agent_types=[self.agent_type.value],
            context=context,
        )

        # 解析额外发现
        additional = self._parse_and_store_discoveries_from_text(deep_response, target)

        return discoveries + additional

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

每条发现单独一行，以「- 」开头。
"""

    def _parse_and_store_discoveries_from_text(
        self,
        text: str,
        target: str,
        source: DiscoverySource = DiscoverySource.ANALYSIS,
    ) -> list[Any]:
        """从文本中解析并存储发现。

        支持多种格式：
        - 列表格式（- 、• 、* 、数字.）
        - 段落格式（按空行分割）
        - JSON 格式（代码块或直接 JSON）
        - 代码块格式

        Args:
            text: LLM 响应文本
            target: 目标产品
            source: 发现来源

        Returns:
            Discovery 对象列表
        """
        import json
        import re

        # 策略 1: 尝试解析 JSON 格式
        json_discoveries = self._try_parse_json_discoveries(text, target, source)
        if json_discoveries:
            return json_discoveries

        # 策略 2: 尝试解析列表格式
        list_discoveries = self._try_parse_list_discoveries(text, target, source)
        if list_discoveries:
            return list_discoveries

        # 策略 3: 尝试解析段落格式（宽松模式）
        return self._try_parse_paragraph_discoveries(text, target, source)

    def _try_parse_json_discoveries(
        self,
        text: str,
        target: str,
        source: DiscoverySource,
    ) -> list[Any] | None:
        """尝试从 JSON 格式解析发现。

        Args:
            text: LLM 响应文本
            target: 目标产品
            source: 发现来源

        Returns:
            Discovery 对象列表，解析失败返回 None
        """
        import json
        import re

        # 尝试提取 JSON 代码块
        patterns = [
            r'```json\s*(\[.*?\])\s*```',
            r'```\s*(\[.*?\])\s*```',
            r'\[\s*\{[^\]]*\}\s*\]',  # 直接的 JSON 数组
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                    data = json.loads(json_str)

                    if isinstance(data, list):
                        discoveries = []
                        for item in data:
                            if isinstance(item, dict):
                                # 支持多种字段名
                                content = (
                                    item.get("content") or
                                    item.get("description") or
                                    item.get("text") or
                                    item.get("evidence") or
                                    item.get("finding", "")
                                )
                                if content and self._is_valid_discovery(content):
                                    quality = self._calculate_quality_score(item, content)
                                    discovery = self.add_discovery(
                                        content=content,
                                        source=source,
                                        quality_score=quality,
                                        metadata={
                                            "target": target,
                                            **{k: v for k, v in item.items() if k not in
                                               ["content", "description", "text", "evidence", "finding"]}
                                        },
                                    )
                                    discoveries.append(discovery)

                        if discoveries:
                            return discoveries
                except (json.JSONDecodeError, ValueError):
                    continue

        return None

    def _try_parse_list_discoveries(
        self,
        text: str,
        target: str,
        source: DiscoverySource,
    ) -> list[Any] | None:
        """尝试从列表格式解析发现。

        Args:
            text: LLM 响应文本
            target: 目标产品
            source: 发现来源

        Returns:
            Discovery 对象列表，解析失败返回 None
        """
        import re

        discoveries = []
        lines = text.split("\n")

        # 统计以列表标记开头的行数
        list_marker_count = sum(
            1 for line in lines
            if line.strip() and any(
                line.strip().startswith(marker)
                for marker in ["- ", "• ", "* ", "1.", "2.", "3.", "4.", "5.",
                               "6.", "7.", "8.", "9."]
            )
        )

        # 如果列表项少于 3 个，可能不是列表格式
        if list_marker_count < 3:
            return None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 支持多种列表格式
            list_patterns = [
                r'^[\-\•\*]\s+',  # - , •, *
                r'^\d+\.\s+',     # 数字.
                r'^\d+\)\s+',     # 数字)
            ]

            content = None
            for pattern in list_patterns:
                if re.match(pattern, line):
                    content = re.sub(pattern, '', line, count=1)
                    break

            if content is None:
                # 非列表行，跳过
                continue

            if self._is_valid_discovery(content):
                quality = self._calculate_quality_score({}, content)
                discovery = self.add_discovery(
                    content=content,
                    source=source,
                    quality_score=quality,
                    metadata={"target": target},
                )
                discoveries.append(discovery)

        return discoveries if discoveries else None

    def _try_parse_paragraph_discoveries(
        self,
        text: str,
        target: str,
        source: DiscoverySource,
    ) -> list[Any]:
        """尝试从段落格式解析发现（宽松模式）。

        Args:
            text: LLM 响应文本
            target: 目标产品
            source: 发现来源

        Returns:
            Discovery 对象列表
        """
        import re

        discoveries = []

        # 移除代码块
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

        # 按段落分割（双换行或单换行+句子结尾）
        paragraphs = re.split(r'\n\s*\n|(?<=[.!?。！？])\s*\n', text)

        for paragraph in paragraphs:
            paragraph = paragraph.strip()

            # 移除常见的前缀标记
            paragraph = re.sub(r'^(发现|结论|分析|要点|总结|note|discovery|conclusion)\s*[:：]?\s*', '', paragraph, flags=re.IGNORECASE)

            if self._is_valid_discovery(paragraph):
                quality = self._calculate_quality_score({}, paragraph)
                discovery = self.add_discovery(
                    content=paragraph,
                    source=source,
                    quality_score=quality,
                    metadata={"target": target},
                )
                discoveries.append(discovery)

        return discoveries

    def _is_valid_discovery(self, content: str) -> bool:
        """验证内容是否为有效发现。

        过滤条件：
        - 长度至少 15 个字符
        - 不包含常见的无效标记
        - 不是纯数字或符号
        - 不是重复的填充词

        Args:
            content: 待验证内容

        Returns:
            是否为有效发现
        """
        import re

        content = content.strip()

        # 长度检查
        if len(content) < 15:
            return False

        # 过滤无意义的内容
        invalid_patterns = [
            r'^暂无',
            r'^待补充',
            r'^to be determined',
            r'^tbd',
            r'^n/a',
            r'^无数据',
            r'^无发现',
            r'^没有找到',
            r'^以下是',
            r'^the following',
            r'^please note',
            r'^注意',
        ]

        for pattern in invalid_patterns:
            if re.match(pattern, content, re.IGNORECASE):
                return False

        # 检查是否有实际内容（至少包含一些中文字符或英文单词）
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', content))
        has_english_words = bool(re.search(r'[a-zA-Z]{3,}', content))

        if not (has_chinese or has_english_words):
            return False

        return True

    def _calculate_quality_score(self, item: dict[str, Any], content: str) -> float:
        """计算发现的质量评分。

        评分因素：
        - 内容长度（越长通常越详细）
        - 是否包含数据/数字
        - 是否包含引用来源
        - 是否有明确的结构

        Args:
            item: 原始数据项（可能包含质量相关字段）
            content: 发现内容

        Returns:
            质量评分 (0.0-1.0)
        """
        import re

        # 如果 item 中已有质量评分，优先使用
        if "quality_score" in item:
            try:
                return max(0.0, min(1.0, float(item["quality_score"])))
            except (ValueError, TypeError):
                pass

        score = 0.5  # 基础分

        # 长度加分（最多 0.3）
        length_bonus = min(0.3, len(content) / 500)
        score += length_bonus

        # 包含数据/数字加分（0.1）
        if re.search(r'\d+%|\d+万|\d+亿|\d+\.\d+|\d+个|\d+项', content):
            score += 0.1

        # 包含引用/来源加分（0.1）
        if re.search(r'(根据|来自|引用|source|reference|官网|文档)', content, re.IGNORECASE):
            score += 0.1

        # 结构化内容加分（0.1）
        if re.search(r'[：:：]|、|，|；|;|-', content):
            score += 0.1

        return min(1.0, score)

    def find_relevant_discoveries(
        self,
        query: str,
        exclude_own: bool = True,
        limit: int = 5,
    ) -> list[Discovery]:
        """查找相关的发现（用于智能引用）。

        基于语义相似度查找与查询相关的发现，支持跨 Agent 引用。

        Args:
            query: 查询内容
            exclude_own: 是否排除自己的发现
            limit: 最大返回数量

        Returns:
            相关发现列表
        """
        all_discoveries = self._environment.all_discoveries

        if exclude_own:
            all_discoveries = [
                d for d in all_discoveries
                if d.agent_type != self.agent_type.value
            ]

        if not all_discoveries:
            return []

        # 使用 LLM 评估相关性
        scored = self._evaluate_relevance_batch(query, all_discoveries)

        # 按相关性排序并限制数量
        scored.sort(key=lambda x: x[1], reverse=True)

        return [d for d, _ in scored[:limit]]

    def _evaluate_relevance_batch(
        self,
        query: str,
        discoveries: list[Discovery],
    ) -> list[tuple[Discovery, float]]:
        """批量评估发现与查询的相关性。

        Args:
            query: 查询内容
            discoveries: 发现列表

        Returns:
            (发现, 相关性分数) 列表
        """
        # 限制每次评估的数量（避免 token 消耗过大）
        max_eval = 20
        candidates = discoveries[:max_eval]

        # 构建评估提示
        prompt = self._build_relevance_prompt(query, candidates)

        try:
            from src.llm import Message

            response = self._llm_client.chat(
                messages=[Message(role="user", content=prompt)],
                system_prompt="你是一个相关性评估专家。请评估每个发现与查询的相关性，返回 JSON 数组格式的评分。",
            )

            return self._parse_relevance_response(response.content, candidates)

        except Exception:
            # 评估失败时，使用简单的文本匹配作为备用
            return self._fallback_text_matching(query, candidates)

    def _build_relevance_prompt(self, query: str, discoveries: list[Discovery]) -> str:
        """构建相关性评估提示词。

        Args:
            query: 查询内容
            discoveries: 发现列表

        Returns:
            提示词
        """
        lines = [
            f"请评估以下发现与查询的相关性。",
            f"",
            f"查询：{query[:200]}",
            f"",
            f"请对每个发现评分（0.0-1.0），以 JSON 数组格式返回：",
            "[",
            '  {"index": 0, "score": 0.8, "reason": "相关原因"},',
            "  ...",
            "]",
            "",
            "发现列表：",
            "",
        ]

        for i, discovery in enumerate(discoveries):
            content = discovery.content[:150] + "..." if len(discovery.content) > 150 else discovery.content
            lines.append(f"{i}. [{discovery.agent_type}] {content}")

        return "\n".join(lines)

    def _parse_relevance_response(
        self,
        response: str,
        discoveries: list[Discovery],
    ) -> list[tuple[Discovery, float]]:
        """解析相关性评估响应。

        Args:
            response: LLM 响应
            discoveries: 原始发现列表

        Returns:
            (发现, 相关性分数) 列表
        """
        import json
        import re

        # 尝试提取 JSON
        json_match = re.search(r'\[\s*\{[^\]]*\}\s*\]', response, re.DOTALL)
        if json_match:
            try:
                results = json.loads(json_match.group(0))
                scored = []
                for result in results:
                    idx = result.get("index", 0)
                    score = float(result.get("score", 0.0))
                    if 0 <= idx < len(discoveries):
                        scored.append((discoveries[idx], score))
                return scored
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        # 解析失败，使用备用方法
        return self._fallback_text_matching("", discoveries)

    def _fallback_text_matching(
        self,
        query: str,
        discoveries: list[Discovery],
    ) -> list[tuple[Discovery, float]]:
        """备用的文本匹配方法。

        Args:
            query: 查询内容（可为空）
            discoveries: 发现列表

        Returns:
            (发现, 相关性分数) 列表
        """
        scored = []
        query_lower = query.lower() if query else ""

        for discovery in discoveries:
            # 使用质量评分作为基础相关性
            score = discovery.quality_score

            # 如果提供了查询，进行简单的文本匹配
            if query_lower:
                content_lower = discovery.content.lower()
                if query_lower in content_lower:
                    score = min(1.0, score + 0.2)

            scored.append((discovery, score))

        return scored

    def _format_context(self, context: dict[str, Any]) -> str:
        """格式化上下文为字符串。

        Args:
            context: 上下文字典

        Returns:
            格式化的上下文字符串
        """
        if not context:
            return ""

        parts = []
        for key, value in context.items():
            if key.startswith("_"):  # 内部字段
                if key == "_discoveries":
                    parts.append(f"Previous Discoveries:\n{value}")
                elif key == "_signals":
                    parts.append(f"Previous Signals:\n{value}")
                elif key == "_handoff":
                    parts.append(f"Handoff Context:\n{value.get('reasoning', '')}")
                elif key == "_search_context":
                    parts.append(f"Web Search Results:\n{value}")
            else:
                parts.append(f"{key}: {value}")

        return "\n\n".join(parts)

    def _parse_discoveries_from_response(self, response: str) -> list[dict[str, Any]]:
        """从响应中解析发现列表。

        Args:
            response: LLM 响应

        Returns:
            发现列表
        """
        # 简单实现：按行分割
        # 实际应用中可以使用更复杂的解析（如 JSON 格式）
        lines = response.strip().split("\n")

        discoveries = []
        current_discovery: dict[str, Any] = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("- ") or line.startswith("• "):
                if current_discovery:
                    discoveries.append(current_discovery)
                current_discovery = {"content": line[2:], "quality_score": 0.5}
            elif current_discovery:
                current_discovery["content"] += " " + line

        if current_discovery:
            discoveries.append(current_discovery)

        return discoveries

    def __repr__(self) -> str:
        """字符串表示。"""
        return f"{self.__class__.__name__}(type={self.agent_type.value}, name={self.name})"
