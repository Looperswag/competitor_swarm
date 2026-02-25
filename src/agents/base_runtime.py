"""Runtime/initialization mixin for BaseAgent."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from src.agents.base_types import AGENT_DIMENSION_MAP, AgentType, SIGNALS_AVAILABLE
from src.environment import StigmergyEnvironment, get_environment
from src.handoff import HandoffManager, get_handoff_manager
from src.llm import LLMClient, get_client
from src.utils.config import get_config as _default_get_config

if TYPE_CHECKING:
    from src.search.base import SearchTool

logger = logging.getLogger(__name__)


class BaseAgentRuntimeMixin:
    """Runtime state and setup behavior shared by agents."""

    MIN_DISCOVERIES: int = 15
    TARGET_DISCOVERIES: int = 30
    MAX_DISCOVERIES: int = 50

    USE_SIGNALS: bool = True
    SIGNAL_DISCOVERY_COMPAT_ENV: str = "COMPETITOR_SWARM_SYNC_DISCOVERY_COMPAT"

    def __init__(
        self,
        agent_type: AgentType,
        name: str,
        system_prompt: str | None = None,
        llm_client: LLMClient | None = None,
        environment: StigmergyEnvironment | None = None,
        handoff_manager: HandoffManager | None = None,
        search_tool: "SearchTool | None" = None,
    ) -> None:
        self.agent_type = agent_type
        self.name = name

        config = self._get_config()
        if system_prompt is None:
            agent_key = agent_type.value
            if hasattr(config.agents, agent_key):
                agent_config = getattr(config.agents, agent_key)
                self._system_prompt = agent_config.system_prompt
                self.MIN_DISCOVERIES = getattr(agent_config, "min_discoveries", self.MIN_DISCOVERIES)
                self.TARGET_DISCOVERIES = getattr(agent_config, "target_discoveries", self.TARGET_DISCOVERIES)
                self.MAX_DISCOVERIES = getattr(agent_config, "max_discoveries", self.MAX_DISCOVERIES)
            else:
                self._system_prompt = f"You are a {name} analyzing competitors."
        else:
            self._system_prompt = system_prompt

        self._llm_client = llm_client or get_client()
        self._environment = environment or get_environment()
        self._handoff_manager = handoff_manager or get_handoff_manager()

        if search_tool is None:
            self._search_tool = self._init_search_tool(config)
        else:
            self._search_tool = search_tool

        self._dimension = AGENT_DIMENSION_MAP.get(agent_type)
        if self._dimension is None and SIGNALS_AVAILABLE:
            from src.schemas.signals import Dimension

            self._dimension = Dimension.PRODUCT

        self._sync_discovery_compat = os.getenv(self.SIGNAL_DISCOVERY_COMPAT_ENV, "0").strip() == "1"
        self._runtime_warnings: list[dict[str, Any]] = []
        self._runtime_last_error_type: str | None = None
        self._runtime_retry_count: int = 0

    def _init_search_tool(self, config: Any) -> "SearchTool | None":
        from src.search import SearchProviderType, get_search_tool

        search_config = config.search
        provider = search_config.provider

        try:
            if provider == "multi":
                agent_key = self.agent_type.value
                agent_profile = None

                if hasattr(search_config, "agent_profiles") and agent_key in search_config.agent_profiles:
                    agent_profile = search_config.agent_profiles[agent_key]

                preferred_providers = None
                if agent_profile and agent_profile.preferred_providers:
                    try:
                        preferred_providers = [
                            SearchProviderType(p) for p in agent_profile.preferred_providers
                        ]
                    except ValueError:
                        preferred_providers = None

                aggregation_mode = search_config.multi_source.aggregation_mode
                if agent_profile and agent_profile.aggregation_mode:
                    aggregation_mode = agent_profile.aggregation_mode

                return get_search_tool(
                    provider="multi",
                    agent_type=agent_key,
                    preferred_providers=preferred_providers,
                    cache_enabled=search_config.multi_source.cache_enabled,
                    cache_ttl=search_config.multi_source.cache_ttl,
                    quota_enabled=search_config.multi_source.quota_enabled,
                    aggregation_mode=aggregation_mode,
                    max_parallel_providers=search_config.multi_source.max_parallel_providers,
                )

            return get_search_tool(
                provider=provider,
                api_key=search_config.api_key or None,
            )
        except Exception as exc:
            logger.warning("Failed to initialize search tool: %s", exc)
            return None

    @staticmethod
    def _get_config() -> Any:
        """Resolve config loader with backward-compatible patch hook."""
        try:
            from src.agents import base as base_entry

            config_loader = getattr(base_entry, "get_config", _default_get_config)
            return config_loader()
        except Exception:
            return _default_get_config()

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def dimension(self) -> Any:
        return self._dimension

    def _reset_runtime_diagnostics(self) -> None:
        self._runtime_warnings = []
        self._runtime_last_error_type = None
        self._runtime_retry_count = 0

    def _record_runtime_warning(
        self,
        *,
        message: str,
        error_type: str,
        recoverable: bool = True,
        hint: str = "",
        retry_count: int = 0,
    ) -> None:
        warning = {
            "message": message,
            "error_type": error_type,
            "recoverable": recoverable,
            "hint": hint,
            "retry_count": max(0, retry_count),
            "run_id": self._environment.current_run_id,
        }
        self._runtime_warnings.append(warning)
        self._runtime_last_error_type = error_type
        self._runtime_retry_count = max(self._runtime_retry_count, warning["retry_count"])

    def _augment_metadata(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        enriched = dict(metadata or {})
        if self._runtime_warnings:
            enriched["warnings"] = list(self._runtime_warnings)
        if self._runtime_last_error_type:
            enriched["error_type"] = self._runtime_last_error_type
        if self._runtime_retry_count > 0:
            enriched["retry_count"] = self._runtime_retry_count
        if self._environment.current_run_id:
            enriched["run_id"] = self._environment.current_run_id
        return enriched

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(type={self.agent_type.value}, name={self.name})"
