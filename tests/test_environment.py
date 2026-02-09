"""测试共享环境模块。"""

import pytest
import tempfile
import shutil
from pathlib import Path

from src.environment import StigmergyEnvironment, Discovery, DiscoverySource


class TestStigmergyEnvironment:
    """测试 StigmergyEnvironment 类。"""

    def setup_method(self):
        """每个测试方法前的设置。"""
        self.temp_dir = tempfile.mkdtemp()
        self.env = StigmergyEnvironment(cache_path=self.temp_dir)

    def teardown_method(self):
        """每个测试方法后的清理。"""
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_add_discovery(self):
        """测试添加发现。"""
        discovery = self.env.add_discovery(
            agent_type="scout",
            content="Notion 是一款笔记工具",
            source=DiscoverySource.WEBSITE,
            quality_score=0.8,
        )

        assert discovery.id is not None
        assert discovery.agent_type == "scout"
        assert discovery.content == "Notion 是一款笔记工具"
        assert discovery.source == DiscoverySource.WEBSITE
        assert discovery.quality_score == 0.8

    def test_get_discovery(self):
        """测试获取发现。"""
        discovery = self.env.add_discovery(
            agent_type="scout",
            content="测试内容",
            source=DiscoverySource.WEBSITE,
            quality_score=0.5,
        )

        retrieved = self.env.get_discovery(discovery.id)

        assert retrieved is not None
        assert retrieved.id == discovery.id
        assert retrieved.content == "测试内容"

    def test_get_discovery_not_found(self):
        """测试获取不存在的发现。"""
        result = self.env.get_discovery("non-existent-id")
        assert result is None

    def test_get_discoveries_by_agent(self):
        """测试按 Agent 类型获取发现。"""
        self.env.add_discovery(
            agent_type="scout",
            content="侦察发现 1",
            source=DiscoverySource.WEBSITE,
            quality_score=0.5,
        )
        self.env.add_discovery(
            agent_type="scout",
            content="侦察发现 2",
            source=DiscoverySource.WEBSITE,
            quality_score=0.5,
        )
        self.env.add_discovery(
            agent_type="technical",
            content="技术发现 1",
            source=DiscoverySource.INFERENCE,
            quality_score=0.5,
        )

        scout_discoveries = self.env.get_discoveries_by_agent("scout")
        tech_discoveries = self.env.get_discoveries_by_agent("technical")

        assert len(scout_discoveries) == 2
        assert len(tech_discoveries) == 1

    def test_get_relevant_discoveries(self):
        """测试获取相关发现。"""
        # 添加不同质量的发现
        self.env.add_discovery(
            agent_type="scout",
            content="高质量发现",
            source=DiscoverySource.WEBSITE,
            quality_score=0.9,
        )
        self.env.add_discovery(
            agent_type="scout",
            content="低质量发现",
            source=DiscoverySource.WEBSITE,
            quality_score=0.3,
        )

        relevant = self.env.get_relevant_discoveries(min_quality=0.5)

        assert len(relevant) == 1
        assert "高质量" in relevant[0].content

    def test_virtual_pheromone(self):
        """测试虚拟信息素机制。"""
        # 添加第一个发现
        discovery1 = self.env.add_discovery(
            agent_type="scout",
            content="发现 1",
            source=DiscoverySource.WEBSITE,
            quality_score=0.5,
        )

        # 添加引用第一个发现的发现
        discovery2 = self.env.add_discovery(
            agent_type="technical",
            content="基于发现 1 的分析",
            source=DiscoverySource.ANALYSIS,
            quality_score=0.5,
            references=[discovery1.id],
        )

        # 获取热门发现
        hot = self.env.get_hot_discoveries()

        assert len(hot) >= 1
        # 发现 1 应该被引用，所以应该更热门
        hot_ids = [d.id for d in hot]
        assert discovery1.id in hot_ids

    def test_cross_agent_insights(self):
        """测试跨 Agent 洞察。"""
        # 添加被引用的发现
        discovery1 = self.env.add_discovery(
            agent_type="scout",
            content="重要发现",
            source=DiscoverySource.WEBSITE,
            quality_score=0.8,
        )

        # 其他 Agent 引用
        self.env.add_discovery(
            agent_type="technical",
            content="技术分析",
            source=DiscoverySource.ANALYSIS,
            quality_score=0.5,
            references=[discovery1.id],
        )
        self.env.add_discovery(
            agent_type="market",
            content="市场分析",
            source=DiscoverySource.ANALYSIS,
            quality_score=0.5,
            references=[discovery1.id],
        )

        insights = self.env.get_cross_agent_insights()

        assert len(insights) >= 1
        assert discovery1.id in [i["discovery_id"] for i in insights]

    def test_save_and_load(self):
        """测试保存和加载。"""
        # 添加数据
        self.env.add_discovery(
            agent_type="scout",
            content="测试发现",
            source=DiscoverySource.WEBSITE,
            quality_score=0.7,
        )

        # 保存
        self.env.save("test_env.json")

        # 创建新环境并加载
        new_env = StigmergyEnvironment(cache_path=self.temp_dir)
        success = new_env.load("test_env.json")

        assert success is True
        assert new_env.discovery_count == 1

    def test_clear(self):
        """测试清空环境。"""
        self.env.add_discovery(
            agent_type="scout",
            content="测试",
            source=DiscoverySource.WEBSITE,
            quality_score=0.5,
        )

        assert self.env.discovery_count == 1

        self.env.clear()

        assert self.env.discovery_count == 0

    def test_discovery_count(self):
        """测试发现计数。"""
        assert self.env.discovery_count == 0

        self.env.add_discovery(
            agent_type="scout",
            content="测试 1",
            source=DiscoverySource.WEBSITE,
            quality_score=0.5,
        )
        self.env.add_discovery(
            agent_type="scout",
            content="测试 2",
            source=DiscoverySource.WEBSITE,
            quality_score=0.5,
        )

        assert self.env.discovery_count == 2
