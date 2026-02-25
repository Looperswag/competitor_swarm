"""Agent base public entrypoint.

This module keeps backward-compatible exports while delegating implementation
across smaller focused mixins.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from src.agents.base_memory import BaseAgentMemoryMixin
from src.agents.base_parsing import BaseAgentParsingMixin
from src.agents.base_relevance import BaseAgentRelevanceMixin
from src.agents.base_runtime import BaseAgentRuntimeMixin
from src.agents.base_search import BaseAgentSearchMixin
from src.agents.base_thinking import BaseAgentThinkingMixin
from src.agents.base_types import (
    AGENT_DIMENSION_MAP,
    SIGNALS_AVAILABLE,
    AgentProtocol,
    AgentResult,
    AgentType,
)
from src.environment import DiscoverySource
from src.utils.config import get_config


class BaseAgent(
    BaseAgentRuntimeMixin,
    BaseAgentThinkingMixin,
    BaseAgentMemoryMixin,
    BaseAgentSearchMixin,
    BaseAgentParsingMixin,
    BaseAgentRelevanceMixin,
    ABC,
):
    """Abstract base class for all concrete agents."""

    @abstractmethod
    def execute(self, **context: Any) -> AgentResult:
        """Execute agent task and return structured result."""

    async def execute_async(self, **context: Any) -> AgentResult:
        """Default async entrypoint wrapping sync execution."""
        return await asyncio.to_thread(self.execute, **context)


__all__ = [
    "AGENT_DIMENSION_MAP",
    "SIGNALS_AVAILABLE",
    "AgentProtocol",
    "AgentResult",
    "AgentType",
    "BaseAgent",
    "DiscoverySource",
    "get_config",
]
