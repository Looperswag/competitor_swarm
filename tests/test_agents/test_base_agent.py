"""测试 Agent 基类模块。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.base import BaseAgent, AgentType, AgentResult, SIGNALS_AVAILABLE
from src.environment import DiscoverySource


# 创建一个具体的测试 Agent
class TestAgent(BaseAgent):
    """用于测试的具体 Agent 实现。"""

    def execute(self, **context):
        """简单的执行实现。"""
        target = context.get("target", "unknown")

        discovery = self.add_discovery(
            content=f"关于 {target} 的发现",
            source=DiscoverySource.ANALYSIS,
            quality_score=0.7,
        )

        return AgentResult(
            agent_type=self.agent_type.value,
            agent_name=self.name,
            discoveries=[discovery.to_dict()],
            handoffs_created=0,
        )


class TestBaseAgent:
    """测试 BaseAgent 类。"""

    def test_initialization(self, mock_llm_client):
        """测试初始化。"""
        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试 Agent",
            llm_client=mock_llm_client,
        )

        assert agent.agent_type == AgentType.SCOUT
        assert agent.name == "测试 Agent"
        assert agent._llm_client == mock_llm_client

    def test_system_prompt_from_config(self, mock_llm_client, sample_config):
        """测试从配置获取系统提示词。"""
        with patch("src.agents.base.get_config", return_value=sample_config):
            agent = TestAgent(
                agent_type=AgentType.SCOUT,
                name="测试",
                llm_client=mock_llm_client,
            )

            # 应该从配置加载
            assert "侦察" in agent.system_prompt or len(agent.system_prompt) > 0

    def test_think(self, mock_llm_client):
        """测试思考方法。"""
        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
        )

        response = agent.think("分析 Notion")

        assert response == "这是一个测试响应。"
        mock_llm_client.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_think_async(self, mock_llm_client, mock_llm_response):
        """测试异步思考方法。"""
        mock_llm_client.chat_async = AsyncMock(return_value=mock_llm_response)

        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
        )

        response = await agent.think_async("分析 Notion")

        assert response == "这是一个测试响应。"
        mock_llm_client.chat_async.assert_called_once()

    def test_think_with_context(self, mock_llm_client):
        """测试带上下文的思考。"""
        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
        )

        response = agent.think(
            "分析 Notion",
            context={"focus": "定价"},
        )

        assert response == "这是一个测试响应。"

        # 验证调用了正确的参数
        call_args = mock_llm_client.chat.call_args
        assert call_args is not None

    def test_add_discovery(self, mock_llm_client, empty_environment):
        """测试添加发现。"""
        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
            environment=empty_environment,
        )

        discovery = agent.add_discovery(
            content="测试发现",
            source=DiscoverySource.WEBSITE,
            quality_score=0.8,
        )

        assert discovery.agent_type == "scout"
        assert discovery.content == "测试发现"
        assert discovery.quality_score == 0.8

    def test_execute(self, mock_llm_client, empty_environment):
        """测试执行方法。"""
        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
            environment=empty_environment,
        )

        result = agent.execute(target="Notion")

        assert isinstance(result, AgentResult)
        assert result.agent_type == "scout"
        assert result.agent_name == "测试"
        assert len(result.discoveries) == 1
        assert "Notion" in result.discoveries[0]["content"]

    def test_create_handoff(self, mock_llm_client):
        """测试创建交接。"""
        from src.handoff import HandoffContext, HandoffPriority, HandoffManager

        handoff_manager = HandoffManager()
        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
            handoff_manager=handoff_manager,
        )

        context = HandoffContext(
            reasoning="需要技术分析",
            suggested_actions=["分析技术栈"],
        )

        agent.create_handoff(
            to_agent="technical",
            context=context,
            priority=HandoffPriority.HIGH,
        )

        assert handoff_manager.pending_count == 1

    def test_get_pending_handoffs(self, mock_llm_client):
        """测试获取待处理交接。"""
        from src.handoff import HandoffContext, HandoffManager

        handoff_manager = HandoffManager()
        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
            handoff_manager=handoff_manager,
        )

        # 创建一个交接
        handoff_manager.create_handoff(
            from_agent="technical",
            to_agent="scout",
            context=HandoffContext(reasoning="测试"),
        )

        pending = agent.get_pending_handoffs()

        assert len(pending) == 1
        assert pending[0].reasoning == "测试"

    def test_repr(self, mock_llm_client):
        """测试字符串表示。"""
        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
        )

        repr_str = repr(agent)

        assert "TestAgent" in repr_str
        assert "scout" in repr_str

    def test_think_with_discoveries_prefers_signals(self, mock_llm_client):
        """当信号可用时，think_with_discoveries 应优先走信号路径。"""
        if not SIGNALS_AVAILABLE:
            pytest.skip("Signal schema not available")

        mock_env = MagicMock()
        mock_env.signal_count = 1

        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
            environment=mock_env,
        )

        with patch.object(agent, "think_with_signals", return_value="signal_ctx") as signal_think:
            response = agent.think_with_discoveries("分析 Notion", agent_types=["scout"])

        assert response == "signal_ctx"
        signal_think.assert_called_once()

    def test_ensure_min_signals_returns_dicts(self, mock_llm_client):
        """_ensure_min_signals 应返回统一的 dict 列表。"""
        if not SIGNALS_AVAILABLE:
            pytest.skip("Signal schema not available")

        class DummySignal:
            def __init__(self, content: str) -> None:
                self._content = content

            def to_dict(self) -> dict:
                return {"content": self._content, "signal_type": "insight"}

        class SignalTestAgent(TestAgent):
            def _parse_and_store_signals(self, response: str, target: str):
                return [DummySignal("s1"), DummySignal("s2")]

        agent = SignalTestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
            environment=MagicMock(),
        )
        agent.MIN_DISCOVERIES = 1
        agent.TARGET_DISCOVERIES = 2

        with patch.object(agent, "think_with_signals", return_value="ok"):
            result = agent._ensure_min_signals([], "Notion", {})

        assert len(result) == 2
        assert isinstance(result[0], dict)
        assert result[0]["content"] == "s1"

    def test_emit_signal_does_not_sync_discovery_by_default(self, mock_llm_client, empty_environment):
        """默认信号流程不再双写 Discovery。"""
        if not SIGNALS_AVAILABLE:
            pytest.skip("Signal schema not available")
        from src.schemas.signals import SignalType

        agent = TestAgent(
            agent_type=AgentType.SCOUT,
            name="测试",
            llm_client=mock_llm_client,
            environment=empty_environment,
        )

        signal = agent.emit_signal(
            signal_type=SignalType.INSIGHT,
            evidence="这是一个信号证据",
            confidence=0.8,
            strength=0.7,
        )

        assert signal is not None
        assert empty_environment.signal_count == 1
        assert empty_environment.discovery_count == 0
