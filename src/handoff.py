"""Handoff 机制模块。

实现 Agent 之间的任务交接。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class HandoffStatus(str, Enum):
    """交接状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HandoffPriority(str, Enum):
    """交接优先级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HandoffContext:
    """交接上下文。

    包含交接所需的全部信息。
    """

    source_discovery_id: str | None = None
    reasoning: str = ""
    relevant_data: dict[str, Any] = field(default_factory=dict)
    suggested_actions: list[str] = field(default_factory=list)


@dataclass
class Handoff:
    """任务交接。

    当一个 Agent 发现需要另一个 Agent 深入分析时创建。
    """

    id: str
    from_agent: str
    to_agent: str
    context: HandoffContext
    priority: HandoffPriority
    status: HandoffStatus
    created_at: str
    updated_at: str
    result: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "context": {
                "source_discovery_id": self.context.source_discovery_id,
                "reasoning": self.context.reasoning,
                "relevant_data": self.context.relevant_data,
                "suggested_actions": self.context.suggested_actions,
            },
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Handoff":
        """从字典创建。"""
        context_data = data["context"]
        context = HandoffContext(
            source_discovery_id=context_data.get("source_discovery_id"),
            reasoning=context_data.get("reasoning", ""),
            relevant_data=context_data.get("relevant_data", {}),
            suggested_actions=context_data.get("suggested_actions", []),
        )

        return cls(
            id=data["id"],
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            context=context,
            priority=HandoffPriority(data["priority"]),
            status=HandoffStatus(data["status"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            result=data.get("result"),
            error=data.get("error"),
        )


class HandoffManager:
    """Handoff 管理器。

    管理 Agent 之间的任务交接。
    """

    def __init__(self) -> None:
        """初始化管理器。"""
        self._handoffs: dict[str, Handoff] = {}

    def create_handoff(
        self,
        from_agent: str,
        to_agent: str,
        context: HandoffContext,
        priority: HandoffPriority = HandoffPriority.MEDIUM,
    ) -> Handoff:
        """创建新的交接。

        Args:
            from_agent: 发起 Agent 类型
            to_agent: 目标 Agent 类型
            context: 交接上下文
            priority: 优先级

        Returns:
            创建的交接对象
        """
        now = datetime.now().isoformat()

        handoff = Handoff(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            context=context,
            priority=priority,
            status=HandoffStatus.PENDING,
            created_at=now,
            updated_at=now,
        )

        self._handoffs[handoff.id] = handoff
        return handoff

    def get_handoff(self, handoff_id: str) -> Handoff | None:
        """获取交接。

        Args:
            handoff_id: 交接 ID

        Returns:
            交接对象，如果不存在返回 None
        """
        return self._handoffs.get(handoff_id)

    def get_pending_handoffs(
        self,
        to_agent: str | None = None,
        min_priority: HandoffPriority = HandoffPriority.MEDIUM,
    ) -> list[Handoff]:
        """获取待处理的交接。

        Args:
            to_agent: 目标 Agent 类型，None 表示全部
            min_priority: 最低优先级

        Returns:
            待处理交接列表，按优先级排序
        """
        pending = [
            h for h in self._handoffs.values()
            if h.status == HandoffStatus.PENDING
        ]

        if to_agent:
            pending = [h for h in pending if h.to_agent == to_agent]

        # 按优先级排序
        priority_order = {
            HandoffPriority.CRITICAL: 0,
            HandoffPriority.HIGH: 1,
            HandoffPriority.MEDIUM: 2,
            HandoffPriority.LOW: 3,
        }

        pending.sort(key=lambda h: priority_order[h.priority])
        return pending

    def update_status(
        self,
        handoff_id: str,
        status: HandoffStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> bool:
        """更新交接状态。

        Args:
            handoff_id: 交接 ID
            status: 新状态
            result: 结果（可选）
            error: 错误信息（可选）

        Returns:
            是否成功更新
        """
        handoff = self._handoffs.get(handoff_id)
        if not handoff:
            return False

        handoff.status = status
        handoff.updated_at = datetime.now().isoformat()

        if result is not None:
            handoff.result = result
        if error is not None:
            handoff.error = error

        return True

    def get_context_for_agent(self, agent_type: str) -> list[HandoffContext]:
        """获取特定 Agent 的所有交接上下文。

        Args:
            agent_type: Agent 类型

        Returns:
            交接上下文列表
        """
        handoffs = self.get_pending_handoffs(to_agent=agent_type)
        return [h.context for h in handoffs]

    def get_handoffs_by_agents(
        self,
        from_agent: str | None = None,
        to_agent: str | None = None,
    ) -> list[Handoff]:
        """按 Agent 筛选交接。

        Args:
            from_agent: 发起 Agent 类型
            to_agent: 目标 Agent 类型

        Returns:
            交接列表
        """
        handoffs = list(self._handoffs.values())

        if from_agent:
            handoffs = [h for h in handoffs if h.from_agent == from_agent]
        if to_agent:
            handoffs = [h for h in handoffs if h.to_agent == to_agent]

        return handoffs

    def cancel_handoff(self, handoff_id: str) -> bool:
        """取消交接。

        Args:
            handoff_id: 交接 ID

        Returns:
            是否成功取消
        """
        return self.update_status(handoff_id, HandoffStatus.CANCELLED)

    def clear(self) -> None:
        """清空所有交接。"""
        self._handoffs.clear()

    @property
    def pending_count(self) -> int:
        """待处理交接数量。"""
        return len([
            h for h in self._handoffs.values()
            if h.status == HandoffStatus.PENDING
        ])

    @property
    def all_handoffs(self) -> list[Handoff]:
        """所有交接。"""
        return list(self._handoffs.values())


# 全局管理器实例（延迟加载）
_manager: HandoffManager | None = None


def get_handoff_manager() -> HandoffManager:
    """获取全局交接管理器实例。

    Returns:
        交接管理器
    """
    global _manager
    if _manager is None:
        _manager = HandoffManager()
    return _manager


def reset_handoff_manager() -> None:
    """重置全局交接管理器。"""
    global _manager
    _manager = None
