"""Core types and constants for agent base abstractions."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class AgentType(str, Enum):
    """Agent type enumeration."""

    SCOUT = "scout"
    EXPERIENCE = "experience"
    TECHNICAL = "technical"
    MARKET = "market"
    RED_TEAM = "red_team"
    BLUE_TEAM = "blue_team"
    ELITE = "elite"


try:
    from src.schemas.signals import Dimension

    SIGNALS_AVAILABLE = True
except ImportError:
    SIGNALS_AVAILABLE = False
    Dimension = None  # type: ignore[assignment]


def _get_dimension_mapping() -> dict[AgentType, Any]:
    """Map agent type to signal dimension."""
    if SIGNALS_AVAILABLE and Dimension is not None:
        return {
            AgentType.SCOUT: Dimension.PRODUCT,
            AgentType.EXPERIENCE: Dimension.UX,
            AgentType.TECHNICAL: Dimension.TECHNICAL,
            AgentType.MARKET: Dimension.MARKET,
        }
    return {}


AGENT_DIMENSION_MAP = _get_dimension_mapping()


class AgentProtocol(Protocol):
    """Agent protocol."""

    agent_type: AgentType
    name: str

    def execute(self, **context: Any) -> Any:
        ...


@dataclass
class AgentResult:
    """Unified agent execution result."""

    agent_type: str
    agent_name: str
    discoveries: list[dict[str, Any]]
    handoffs_created: int
    thinking_process: str | None = None
    metadata: dict[str, Any] | None = None
