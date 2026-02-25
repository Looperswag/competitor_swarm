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

    name: str = "glm-4.7"  # 默认模型
    temperature: float = 1.0  # glm-4.7 默认值
    max_tokens: int = 4096
    thinking_mode: bool = True  # 默认开启深度思考
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
    sync_timeout_seconds: int = 300
    async_job_workers: int = 2
    async_job_ttl_seconds: int = 3600


class RecurringJobConfig(BaseModel):
    """单个定时任务配置。"""

    target: str
    competitors: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)
    interval_hours: int = 24
    alert_webhook: str | None = None
    alert_threshold: float = 0.2
    enabled: bool = True


class RecurringJobsConfig(BaseModel):
    """定时任务配置。"""

    enabled: bool = False
    storage_path: str = "data/scheduled_jobs.json"
    max_concurrent: int = 2
    jobs: list[RecurringJobConfig] = Field(default_factory=list)


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


class EnvironmentConfig(BaseModel):
    """运行环境治理配置。"""

    signal_ttl_hours: int = 24
    discovery_ttl_hours: int = 24
    max_signals: int = 5000
    max_discoveries: int = 1000
    run_isolation: bool = True
    discovery_migration_deadline: str = "2026-06-30"
    pheromone_decay_lambda: float = 0.08
    pheromone_reference_weight: float = 0.20
    pheromone_validation_weight: float = 0.15
    pheromone_debate_weight: float = 0.25
    pheromone_freshness_weight: float = 0.05
    pheromone_diffusion_weight: float = 0.10
    semantic_link_threshold: float = 0.30
    semantic_link_max_edges: int = 8


class ValidationPhaseConfig(BaseModel):
    """交叉验证阶段策略配置。"""

    min_confidence: float = 0.3
    min_strength: float = 0.0
    confidence_weight: float = 0.7
    strength_weight: float = 0.3
    min_weighted_score: float = 0.35
    max_signals_per_dimension: int = 20
    verification_boost: float = 0.03
    enable_quantitative_validation: bool = True
    quantitative_tolerance_threshold: float = 0.2


class DebatePhaseConfig(BaseModel):
    """对抗辩论阶段策略配置。"""

    rounds: int = 3
    strength_step: float = 0.05
    round_decay: float = 0.85
    max_adjustment: float = 0.2
    max_points_per_round: int = 10
    verified_only: bool = True
    rule_score_threshold: float = 0.35
    llm_uncertainty_threshold: float = 0.15
    llm_adjudication: bool = True
    llm_batch_size: int = 10
    llm_max_tokens: int = 128
    llm_temperature: float = 0.0


class PhaseExecutorConfig(BaseModel):
    """四阶段执行引擎策略配置。"""

    validation: ValidationPhaseConfig = Field(default_factory=ValidationPhaseConfig)
    debate: DebatePhaseConfig = Field(default_factory=DebatePhaseConfig)


class Config(BaseModel):
    """主配置类。"""

    model: ModelConfig = Field(default_factory=ModelConfig)
    agents: AgentsConfig
    cache: CacheConfig = Field(default_factory=CacheConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    discovery_limits: DiscoveryLimitsConfig = Field(default_factory=DiscoveryLimitsConfig)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    phase_executor: PhaseExecutorConfig = Field(default_factory=PhaseExecutorConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    recurring_jobs: RecurringJobsConfig = Field(default_factory=RecurringJobsConfig)


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
