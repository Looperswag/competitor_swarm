"""测试共享环境模块。"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from src.environment import StigmergyEnvironment, Discovery, DiscoverySource
from src.core import phase_executor as phase_executor_module

if phase_executor_module.SIGNALS_AVAILABLE:
    from src.schemas.signals import (
        Signal,
        SignalType,
        Dimension,
        Sentiment,
        Actionability,
    )


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

    def test_discovery_compat_metadata_contains_migration_deadline(self):
        """Discovery 兼容层应带迁移截止日期元数据。"""
        discovery = self.env.add_discovery(
            agent_type="scout",
            content="兼容层发现",
            source=DiscoverySource.ANALYSIS,
            quality_score=0.6,
        )

        assert discovery.metadata.get("_compat_layer") is True
        assert "migration_deadline" in discovery.metadata

    def test_run_isolation_filters_discoveries(self):
        """启用 run 隔离时，应只暴露当前 run 的数据。"""
        env = StigmergyEnvironment(cache_path=self.temp_dir, run_isolation=True)

        env.begin_run("run-a", clear=True)
        env.add_discovery(
            agent_type="scout",
            content="run-a 内容",
            source=DiscoverySource.WEBSITE,
            quality_score=0.8,
        )

        env.begin_run("run-b", clear=False)
        env.add_discovery(
            agent_type="scout",
            content="run-b 内容",
            source=DiscoverySource.WEBSITE,
            quality_score=0.8,
        )

        current = env.get_discoveries_by_agent("scout")
        assert len(current) == 1
        assert "run-b" in current[0].content

        env.begin_run("run-a", clear=False)
        run_a_items = env.get_discoveries_by_agent("scout")
        assert len(run_a_items) == 1
        assert "run-a" in run_a_items[0].content

    @pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
    def test_signal_ttl_eviction(self):
        """Signal TTL 到期后应被自动清理。"""
        env = StigmergyEnvironment(cache_path=self.temp_dir, signal_ttl_hours=1, max_signals=10)

        old_signal = Signal(
            id="old-signal",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.PRODUCT,
            evidence="old evidence",
            confidence=0.7,
            strength=0.6,
            sentiment=Sentiment.NEUTRAL,
            actionability=Actionability.INFORMATIONAL,
            author_agent="scout",
            timestamp=(datetime.now() - timedelta(hours=2)).isoformat(),
        )
        new_signal = Signal(
            id="new-signal",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.PRODUCT,
            evidence="new evidence",
            confidence=0.7,
            strength=0.6,
            sentiment=Sentiment.NEUTRAL,
            actionability=Actionability.INFORMATIONAL,
            author_agent="scout",
            timestamp=datetime.now().isoformat(),
        )

        env.add_signal(old_signal)
        env.add_signal(new_signal)

        assert env.signal_count == 1
        assert env.get_signal("old-signal") is None
        assert env.get_signal("new-signal") is not None

    @pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
    def test_signal_capacity_eviction(self):
        """Signal 超过最大容量时应淘汰最旧数据。"""
        env = StigmergyEnvironment(cache_path=self.temp_dir, signal_ttl_hours=24, max_signals=2)

        for idx in range(3):
            signal = Signal(
                id=f"signal-{idx}",
                signal_type=SignalType.INSIGHT,
                dimension=Dimension.PRODUCT,
                evidence=f"evidence-{idx}",
                confidence=0.7,
                strength=0.6,
                sentiment=Sentiment.NEUTRAL,
                actionability=Actionability.INFORMATIONAL,
                author_agent="scout",
                timestamp=(datetime.now() + timedelta(seconds=idx)).isoformat(),
            )
            env.add_signal(signal)

        assert env.signal_count == 2
        assert env.get_signal("signal-0") is None
        assert env.get_signal("signal-1") is not None
        assert env.get_signal("signal-2") is not None

    @pytest.mark.skipif(not phase_executor_module.SIGNALS_AVAILABLE, reason="Signal schema not available")
    def test_signal_graph_edge_queries_include_reference_and_debate_edges(self):
        """图边查询应返回引用边和辩论关系边。"""
        env = StigmergyEnvironment(cache_path=self.temp_dir, signal_ttl_hours=24, max_signals=20)

        base = Signal(
            id="sig-base",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.PRODUCT,
            evidence="base capability and onboarding",
            confidence=0.8,
            strength=0.7,
            sentiment=Sentiment.NEUTRAL,
            actionability=Actionability.INFORMATIONAL,
            author_agent="scout",
        )
        ref = Signal(
            id="sig-ref",
            signal_type=SignalType.INSIGHT,
            dimension=Dimension.TECHNICAL,
            evidence="technical scalability references onboarding baseline",
            confidence=0.75,
            strength=0.65,
            sentiment=Sentiment.NEUTRAL,
            actionability=Actionability.SHORT_TERM,
            author_agent="technical",
            references=["sig-base"],
        )
        env.add_signal(base)
        env.add_signal(ref)
        env.register_debate_relation("sig-ref", "sig-base", support=False, weight=0.6)

        edges = env.get_signal_graph_edges()
        neighbors = env.get_signal_neighbors("sig-base")

        assert any(edge.src == "sig-ref" and edge.dst == "sig-base" for edge in edges)
        assert any(edge.edge_type.value == "debate_attack" for edge in neighbors)
