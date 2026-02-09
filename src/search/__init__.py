"""搜索模块。

提供 Web 搜索能力，支持多个搜索服务提供商和降级机制。
"""

# 基础接口
from src.search.base import (
    ProviderMetadata,
    SearchProviderType,
    SearchResult,
    SearchTimeRange,
    SearchTool,
)

# 多源搜索
from src.search.multi_source import MultiSourceSearchTool

# 注册表
from src.search.registry import registry as provider_registry

# 向后兼容 - 保留原有类
from src.search.tavily_mcp import TavilyMCPTool, MCPHybridSearchTool

# 搜索源实现
from src.search.providers import (
    TavilySearchTool,
    DuckDuckGoSearchTool,
    WikipediaSearchTool,
    SkillFallbackSearchTool,
)

__all__ = [
    # 基础接口
    "ProviderMetadata",
    "SearchProviderType",
    "SearchResult",
    "SearchTimeRange",
    "SearchTool",
    # 多源搜索
    "MultiSourceSearchTool",
    # 注册表
    "provider_registry",
    # 搜索源
    "TavilySearchTool",
    "DuckDuckGoSearchTool",
    "WikipediaSearchTool",
    "SkillFallbackSearchTool",
    # 向后兼容
    "TavilyMCPTool",
    "MCPHybridSearchTool",
    # 工厂函数
    "get_search_tool",
]


def get_search_tool(
    provider: str = "multi",
    api_key: str | None = None,
    enable_fallback: bool = True,
    agent_type: str | None = None,
    preferred_providers: list[str] | None = None,
    **kwargs,
) -> SearchTool:
    """获取搜索工具实例。

    Args:
        provider: 搜索服务提供商
            - "multi": 多源搜索（推荐）
            - "mcp": 仅使用 Tavily MCP（向后兼容）
            - "mcp_hybrid": 优先 Tavily MCP，失败时降级到 skill（向后兼容）
            - "tavily": Tavily 搜索源
            - "duckduckgo": DuckDuckGo 搜索源
            - "wikipedia": Wikipedia 搜索源
        api_key: API 密钥（向后兼容）
        enable_fallback: 是否启用降级机制（向后兼容）
        agent_type: Agent 类型，用于选择默认搜索源
        preferred_providers: 首选搜索源列表
        **kwargs: 其他参数传递给 MultiSourceSearchTool

    Returns:
        搜索工具实例
    """
    # 多源搜索模式
    if provider == "multi":
        # 转换字符串为 SearchProviderType
        provider_types = None
        if preferred_providers:
            provider_types = [
                SearchProviderType(p) if isinstance(p, str) else p
                for p in preferred_providers
            ]

        return MultiSourceSearchTool(
            preferred_providers=provider_types,
            agent_type=agent_type,
            **kwargs,
        )

    # 向后兼容
    if provider == "mcp":
        return TavilyMCPTool(api_key=api_key)
    elif provider == "mcp_hybrid":
        return MCPHybridSearchTool(tavily_api_key=api_key)

    # 单个搜索源
    try:
        provider_type = SearchProviderType(provider)
        tool = provider_registry.get_provider(provider_type)
        if tool:
            return tool
    except ValueError:
        pass

    raise ValueError(f"Unsupported search provider: {provider}")
