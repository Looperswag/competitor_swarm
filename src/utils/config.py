"""配置加载模块。

从 YAML 文件和环境变量加载配置。
"""

import os
from functools import lru_cache
from typing import Any
from pathlib import Path
import yaml

from dotenv import load_dotenv
from pydantic import BaseModel, Field


# 加载 .env 文件
load_dotenv()

# 提示词目录路径
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


@lru_cache(maxsize=None)
def load_agent_prompt(agent_type: str) -> str | None:
    """加载 Agent 系统提示词文件。

    Args:
        agent_type: Agent 类型（如 "scout", "experience" 等）

    Returns:
        提示词内容，文件不存在时返回 None
    """
    prompt_file = PROMPTS_DIR / f"{agent_type}.md"
    if not prompt_file.exists():
        return None

    content = prompt_file.read_text(encoding="utf-8")
    # 移除可能的 YAML frontmatter
    lines = content.split("\n")
    if len(lines) > 0 and lines[0].startswith("---"):
        try:
            idx = lines.index("---", 1)
            content = "\n".join(lines[idx + 1:])
        except ValueError:
            pass
    return content.strip()


class ModelConfig(BaseModel):
    """模型配置。"""

    name: str = "glm-4.7"
    temperature: float = 0.7
    max_tokens: int = 4096
    thinking_mode: bool = True
    timeout: float = 120.0  # LLM 请求超时时间（秒）


class AgentConfig(BaseModel):
    """单个 Agent 配置。"""

    name: str
    system_prompt: str | None = None  # 可选，默认从文件加载
    min_discoveries: int = 15
    target_discoveries: int = 30
    max_discoveries: int = 50


class AgentsConfig(BaseModel):
    """所有 Agent 配置。"""

    scout: AgentConfig
    experience: AgentConfig
    technical: AgentConfig
    market: AgentConfig
    red_team: AgentConfig
    blue_team: AgentConfig
    elite: AgentConfig


class CacheConfig(BaseModel):
    """缓存配置。"""

    enabled: bool = True
    ttl: int = 3600
    path: str = "data/cache"


class SchedulerConfig(BaseModel):
    """调度器配置。"""

    max_concurrent: int = 4
    timeout: int = 300


class OutputConfig(BaseModel):
    """输出配置。"""

    path: str = "output"
    format: str = "markdown"
    include_metadata: bool = True
    include_appendix: bool = False
    html_enabled: bool = True
    json_enabled: bool = False


class WebConfig(BaseModel):
    """Web 服务器配置。"""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False


class SearchProviderConfig(BaseModel):
    """单个搜索源配置。"""

    enabled: bool = True
    priority: int = 10
    daily_quota: int | None = None
    rate_limit: int | None = None
    api_key_env: str | None = None


class MultiSourceConfig(BaseModel):
    """多源搜索配置。"""

    aggregation_mode: str = "priority"  # priority/parallel/all
    max_parallel_providers: int = 2
    deduplication_enabled: bool = True
    cache_enabled: bool = True
    cache_ttl: int = 3600
    quota_enabled: bool = True


class AgentSearchProfile(BaseModel):
    """Agent 搜索配置。"""

    preferred_providers: list[str] = Field(default_factory=lambda: ["tavily", "duckduckgo"])
    max_results: int = 10
    aggregation_mode: str | None = None  # 覆盖全局配置


class SearchConfig(BaseModel):
    """搜索配置。"""

    provider: str = "multi"  # 更改默认为 multi
    api_key: str = ""
    default_time_range: str = "oneYear"
    max_results: int = 10
    # 多源搜索配置
    multi_source: MultiSourceConfig = Field(default_factory=MultiSourceConfig)
    # 各搜索源配置
    providers: dict[str, SearchProviderConfig] = Field(default_factory=dict)
    # Agent 特定搜索配置
    agent_profiles: dict[str, AgentSearchProfile] = Field(default_factory=dict)


class DiscoveryLimitsConfig(BaseModel):
    """发现数量限制配置。"""

    min_per_agent: int = 15
    target_per_agent: int = 30
    max_per_agent: int = 50


class Config(BaseModel):
    """主配置类。"""

    model: ModelConfig = Field(default_factory=ModelConfig)
    agents: AgentsConfig
    cache: CacheConfig = Field(default_factory=CacheConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    discovery_limits: DiscoveryLimitsConfig = Field(default_factory=DiscoveryLimitsConfig)
    web: WebConfig = Field(default_factory=WebConfig)


def get_env(key: str, default: str | None = None) -> str:
    """从环境变量获取配置值。

    Args:
        key: 环境变量名
        default: 默认值

    Returns:
        环境变量值

    Raises:
        ValueError: 环境变量不存在且未提供默认值
    """
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"Environment variable '{key}' not set and no default provided")
    return value


def load_config(config_path: str | None = None) -> Config:
    """从 YAML 文件加载配置。

    Args:
        config_path: 配置文件路径，默认为项目根目录的 config.yaml

    Returns:
        配置对象

    Raises:
        FileNotFoundError: 配置文件不存在
        ValueError: 配置格式错误
    """
    if config_path is None:
        # 默认从项目根目录加载
        project_root = Path(__file__).parent.parent.parent
        config_path = str(project_root / "config.yaml")

    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError(f"Config file is empty: {config_path}")

    config = Config(**data)

    # 为每个 agent 注入提示词（如果未在配置中指定）
    agent_types = ["scout", "experience", "technical", "market", "red_team", "blue_team", "elite"]
    for agent_type in agent_types:
        agent_config = getattr(config.agents, agent_type)
        if agent_config.system_prompt is None:
            agent_config.system_prompt = load_agent_prompt(agent_type) or f"You are a {agent_config.name}."

    return config


# 全局配置实例（延迟加载）
_config: Config | None = None


def get_config() -> Config:
    """获取全局配置实例。

    Returns:
        配置对象
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config
