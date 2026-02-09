"""Pytest 配置和共享 fixtures。"""

import pytest
from unittest.mock import MagicMock, Mock
from typing import Any

from src.environment import StigmergyEnvironment, Discovery, DiscoverySource
from src.llm import LLMClient, LLMResponse
from src.agents.base import AgentType


@pytest.fixture
def mock_llm_response():
    """Mock LLM 响应。"""
    return LLMResponse(
        content="这是一个测试响应。",
        model="glm-4.7",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        thinking_content=None,
    )


@pytest.fixture
def mock_llm_client(mock_llm_response):
    """Mock LLM 客户端。"""
    client = MagicMock(spec=LLMClient)
    client.chat.return_value = mock_llm_response
    client.stats = MagicMock()
    client.stats.total_input_tokens = 0
    client.stats.total_output_tokens = 0
    client.stats.total_requests = 0
    return client


@pytest.fixture
def sample_discovery():
    """示例发现。"""
    return Discovery(
        id="test-discovery-1",
        agent_type="scout",
        content="这是一个测试发现",
        source=DiscoverySource.WEBSITE,
        quality_score=0.7,
        timestamp="2024-01-01T00:00:00",
        references=[],
        metadata={"target": "test"},
    )


@pytest.fixture
def sample_environment(sample_discovery):
    """示例环境（包含一些数据）。"""
    env = StigmergyEnvironment(cache_path="test_cache")
    env.add_discovery(
        agent_type="scout",
        content="Notion 是一款笔记和协作工具",
        source=DiscoverySource.WEBSITE,
        quality_score=0.8,
        metadata={"target": "Notion"},
    )
    return env


@pytest.fixture
def empty_environment():
    """空环境。"""
    return StigmergyEnvironment(cache_path="test_cache")


@pytest.fixture
def sample_config():
    """示例配置数据。"""
    from src.utils.config import Config, ModelConfig, AgentConfig, AgentsConfig, CacheConfig, SchedulerConfig, OutputConfig
    return Config(
        model=ModelConfig(
            name="glm-4.7",
            temperature=0.7,
            max_tokens=4096,
            thinking_mode=True,
        ),
        agents=AgentsConfig(
            scout=AgentConfig(
                name="侦察专家",
                system_prompt="你是侦察专家",
            ),
            experience=AgentConfig(
                name="体验专家",
                system_prompt="你是体验专家",
            ),
            technical=AgentConfig(
                name="技术分析专家",
                system_prompt="你是技术分析专家",
            ),
            market=AgentConfig(
                name="市场分析专家",
                system_prompt="你是市场分析专家",
            ),
            red_team=AgentConfig(
                name="红队专家",
                system_prompt="你是红队专家",
            ),
            blue_team=AgentConfig(
                name="蓝队专家",
                system_prompt="你是蓝队专家",
            ),
            elite=AgentConfig(
                name="综合分析专家",
                system_prompt="你是综合分析专家",
            ),
        ),
        cache=CacheConfig(
            enabled=True,
            ttl=3600,
            path="data/cache",
        ),
        scheduler=SchedulerConfig(
            max_concurrent=4,
            timeout=300,
        ),
        output=OutputConfig(
            path="output",
            format="markdown",
            include_metadata=True,
        ),
    )


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic 客户端。"""
    mock = MagicMock()
    mock.messages.create.return_value = MagicMock(
        content=[MagicMock(text="测试响应")],
        model="glm-4.7",
        usage=MagicMock(
            input_tokens=100,
            output_tokens=50,
        ),
    )
    return mock
