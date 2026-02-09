"""测试 Handoff 机制模块。"""

import pytest

from src.handoff import (
    Handoff,
    HandoffContext,
    HandoffManager,
    HandoffStatus,
    HandoffPriority,
)


class TestHandoffContext:
    """测试 HandoffContext 类。"""

    def test_create_context(self):
        """测试创建上下文。"""
        context = HandoffContext(
            source_discovery_id="discovery-1",
            reasoning="需要深入分析",
            relevant_data={"key": "value"},
            suggested_actions=["action1", "action2"],
        )

        assert context.source_discovery_id == "discovery-1"
        assert context.reasoning == "需要深入分析"
        assert context.relevant_data == {"key": "value"}
        assert len(context.suggested_actions) == 2

    def test_create_empty_context(self):
        """测试创建空上下文。"""
        context = HandoffContext()

        assert context.source_discovery_id is None
        assert context.reasoning == ""
        assert context.relevant_data == {}
        assert context.suggested_actions == []


class TestHandoff:
    """测试 Handoff 类。"""

    def test_create_handoff(self):
        """测试创建交接。"""
        context = HandoffContext(reasoning="测试")
        handoff = Handoff(
            id="handoff-1",
            from_agent="scout",
            to_agent="technical",
            context=context,
            priority=HandoffPriority.HIGH,
            status=HandoffStatus.PENDING,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )

        assert handoff.id == "handoff-1"
        assert handoff.from_agent == "scout"
        assert handoff.to_agent == "technical"
        assert handoff.priority == HandoffPriority.HIGH
        assert handoff.status == HandoffStatus.PENDING

    def test_handoff_to_dict(self):
        """测试转换为字典。"""
        context = HandoffContext(reasoning="测试")
        handoff = Handoff(
            id="handoff-1",
            from_agent="scout",
            to_agent="technical",
            context=context,
            priority=HandoffPriority.MEDIUM,
            status=HandoffStatus.PENDING,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )

        data = handoff.to_dict()

        assert data["id"] == "handoff-1"
        assert data["from_agent"] == "scout"
        assert data["to_agent"] == "technical"
        assert data["priority"] == "medium"
        assert data["status"] == "pending"
        assert "context" in data

    def test_handoff_from_dict(self):
        """测试从字典创建。"""
        data = {
            "id": "handoff-1",
            "from_agent": "scout",
            "to_agent": "technical",
            "context": {
                "source_discovery_id": "discovery-1",
                "reasoning": "测试",
                "relevant_data": {},
                "suggested_actions": [],
            },
            "priority": "high",
            "status": "pending",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }

        handoff = Handoff.from_dict(data)

        assert handoff.id == "handoff-1"
        assert handoff.from_agent == "scout"
        assert handoff.to_agent == "technical"
        assert handoff.priority == HandoffPriority.HIGH
        assert handoff.status == HandoffStatus.PENDING


class TestHandoffManager:
    """测试 HandoffManager 类。"""

    def setup_method(self):
        """每个测试方法前的设置。"""
        self.manager = HandoffManager()

    def test_create_handoff(self):
        """测试创建交接。"""
        context = HandoffContext(reasoning="需要技术分析")

        handoff = self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context,
            priority=HandoffPriority.MEDIUM,
        )

        assert handoff.id is not None
        assert handoff.from_agent == "scout"
        assert handoff.to_agent == "technical"
        assert handoff.status == HandoffStatus.PENDING

    def test_get_handoff(self):
        """测试获取交接。"""
        context = HandoffContext()
        handoff = self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context,
        )

        retrieved = self.manager.get_handoff(handoff.id)

        assert retrieved is not None
        assert retrieved.id == handoff.id

    def test_get_handoff_not_found(self):
        """测试获取不存在的交接。"""
        result = self.manager.get_handoff("non-existent")
        assert result is None

    def test_get_pending_handoffs(self):
        """测试获取待处理交接。"""
        # 创建多个交接
        context1 = HandoffContext(reasoning="优先级高")
        self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context1,
            priority=HandoffPriority.HIGH,
        )

        context2 = HandoffContext(reasoning="优先级低")
        self.manager.create_handoff(
            from_agent="scout",
            to_agent="market",
            context=context2,
            priority=HandoffPriority.LOW,
        )

        pending = self.manager.get_pending_handoffs()

        assert len(pending) == 2
        # 高优先级应该排在前面
        assert pending[0].priority == HandoffPriority.HIGH

    def test_get_pending_handoffs_by_agent(self):
        """测试按目标 Agent 获取待处理交接。"""
        context1 = HandoffContext()
        self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context1,
        )

        context2 = HandoffContext()
        self.manager.create_handoff(
            from_agent="scout",
            to_agent="market",
            context=context2,
        )

        tech_handoffs = self.manager.get_pending_handoffs(to_agent="technical")

        assert len(tech_handoffs) == 1
        assert tech_handoffs[0].to_agent == "technical"

    def test_update_status(self):
        """测试更新状态。"""
        context = HandoffContext()
        handoff = self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context,
        )

        success = self.manager.update_status(
            handoff.id,
            HandoffStatus.COMPLETED,
            result="分析完成",
        )

        assert success is True

        updated = self.manager.get_handoff(handoff.id)
        assert updated.status == HandoffStatus.COMPLETED
        assert updated.result == "分析完成"

    def test_update_status_not_found(self):
        """测试更新不存在的交接状态。"""
        success = self.manager.update_status(
            "non-existent",
            HandoffStatus.COMPLETED,
        )
        assert success is False

    def test_get_context_for_agent(self):
        """测试获取特定 Agent 的上下文。"""
        context1 = HandoffContext(reasoning="上下文 1")
        self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context1,
        )

        context2 = HandoffContext(reasoning="上下文 2")
        self.manager.create_handoff(
            from_agent="experience",
            to_agent="technical",
            context=context2,
        )

        tech_contexts = self.manager.get_context_for_agent("technical")

        assert len(tech_contexts) == 2
        contexts_text = [c.reasoning for c in tech_contexts]
        assert "上下文 1" in contexts_text
        assert "上下文 2" in contexts_text

    def test_cancel_handoff(self):
        """测试取消交接。"""
        context = HandoffContext()
        handoff = self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context,
        )

        success = self.manager.cancel_handoff(handoff.id)

        assert success is True

        cancelled = self.manager.get_handoff(handoff.id)
        assert cancelled.status == HandoffStatus.CANCELLED

    def test_clear(self):
        """测试清空。"""
        context = HandoffContext()
        self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context,
        )

        assert self.manager.pending_count == 1

        self.manager.clear()

        assert self.manager.pending_count == 0

    def test_pending_count(self):
        """测试待处理计数。"""
        assert self.manager.pending_count == 0

        context = HandoffContext()
        self.manager.create_handoff(
            from_agent="scout",
            to_agent="technical",
            context=context,
        )

        assert self.manager.pending_count == 1

        handoff = self.manager.all_handoffs[0]
        self.manager.update_status(handoff.id, HandoffStatus.COMPLETED)

        assert self.manager.pending_count == 0
