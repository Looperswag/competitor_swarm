"""Thinking and context composition mixin for BaseAgent."""

from __future__ import annotations

import asyncio
from typing import Any

from src.agents.base_types import AGENT_DIMENSION_MAP, AgentType, SIGNALS_AVAILABLE
from src.error_types import ErrorType
from src.llm import Message


class BaseAgentThinkingMixin:
    """LLM thinking helpers."""

    def think(
        self,
        user_message: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        messages = [Message(role="user", content=user_message)]

        if context:
            context_str = self._format_context(context)
            if context_str:
                messages[0] = Message(
                    role="user",
                    content=f"Context:\n{context_str}\n\nTask:\n{user_message}",
                )

        response = self._llm_client.chat(
            messages=messages,
            system_prompt=self._system_prompt,
        )
        content = response.content
        if not str(content).strip():
            self._record_runtime_warning(
                message="LLM returned empty content",
                error_type=ErrorType.EMPTY_OUTPUT.value,
                recoverable=True,
                hint="Check upstream model stability and prompt constraints",
            )
        return content

    async def think_async(
        self,
        user_message: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        messages = [Message(role="user", content=user_message)]

        if context:
            context_str = self._format_context(context)
            if context_str:
                messages[0] = Message(
                    role="user",
                    content=f"Context:\n{context_str}\n\nTask:\n{user_message}",
                )

        response = await self._llm_client.chat_async(
            messages=messages,
            system_prompt=self._system_prompt,
        )
        content = response.content
        if not str(content).strip():
            self._record_runtime_warning(
                message="LLM returned empty content",
                error_type=ErrorType.EMPTY_OUTPUT.value,
                recoverable=True,
                hint="Check upstream model stability and prompt constraints",
            )
        return content

    def think_with_signals(
        self,
        user_message: str,
        dimensions: list[Any] | None = None,
        min_confidence: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> str:
        if not SIGNALS_AVAILABLE or not self.USE_SIGNALS:
            return self.think_with_discoveries(
                user_message,
                [d.value for d in dimensions] if dimensions else None,
                context,
            )

        signals = []
        if dimensions:
            for dim in dimensions:
                dim_signals = self._environment.get_signals_by_dimension(
                    dimension=dim,
                    min_confidence=min_confidence,
                    limit=10,
                )
                signals.extend(dim_signals)
        else:
            signals = self._environment.get_fresh_signals(limit=20)

        signal_context = ""
        if signals:
            signal_context = "\n\n".join([
                f"[{s.dimension.value}] {s.evidence}"
                for s in signals[:20]
            ])

        full_context = {**(context or {})}
        if signal_context:
            full_context["_signals"] = signal_context

        return self.think(user_message, full_context)

    async def think_with_signals_async(
        self,
        user_message: str,
        dimensions: list[Any] | None = None,
        min_confidence: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> str:
        if not SIGNALS_AVAILABLE or not self.USE_SIGNALS:
            return await self.think_with_discoveries_async(
                user_message,
                [d.value for d in dimensions] if dimensions else None,
                context,
            )

        signals = []
        if dimensions:
            for dim in dimensions:
                dim_signals = self._environment.get_signals_by_dimension(
                    dimension=dim,
                    min_confidence=min_confidence,
                    limit=10,
                )
                signals.extend(dim_signals)
        else:
            signals = self._environment.get_fresh_signals(limit=20)

        signal_context = ""
        if signals:
            signal_context = "\n\n".join([
                f"[{s.dimension.value}] {s.evidence}"
                for s in signals[:20]
            ])

        full_context = {**(context or {})}
        if signal_context:
            full_context["_signals"] = signal_context

        return await self.think_async(user_message, full_context)

    def think_with_discoveries(
        self,
        user_message: str,
        agent_types: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        if SIGNALS_AVAILABLE and self.USE_SIGNALS and getattr(self._environment, "signal_count", 0) > 0:
            dimensions = self._resolve_dimensions_from_agent_types(agent_types)
            return self.think_with_signals(
                user_message,
                dimensions=dimensions or None,
                context=context,
            )

        discoveries = self._environment.get_relevant_discoveries(
            agent_type=agent_types[0] if agent_types and len(agent_types) == 1 else None,
            limit=20,
        )

        discovery_context = ""
        if discoveries:
            discovery_context = "\n\n".join([
                f"[{d.agent_type}] {d.content}"
                for d in discoveries
            ])

        full_context = {**(context or {})}
        if discovery_context:
            full_context["_discoveries"] = discovery_context

        return self.think(user_message, full_context)

    async def think_with_discoveries_async(
        self,
        user_message: str,
        agent_types: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        if SIGNALS_AVAILABLE and self.USE_SIGNALS and getattr(self._environment, "signal_count", 0) > 0:
            dimensions = self._resolve_dimensions_from_agent_types(agent_types)
            return await self.think_with_signals_async(
                user_message,
                dimensions=dimensions or None,
                context=context,
            )

        discoveries = self._environment.get_relevant_discoveries(
            agent_type=agent_types[0] if agent_types and len(agent_types) == 1 else None,
            limit=20,
        )

        discovery_context = ""
        if discoveries:
            discovery_context = "\n\n".join([
                f"[{d.agent_type}] {d.content}"
                for d in discoveries
            ])

        full_context = {**(context or {})}
        if discovery_context:
            full_context["_discoveries"] = discovery_context

        return await self.think_async(user_message, full_context)

    def _resolve_dimensions_from_agent_types(self, agent_types: list[str] | None) -> list[Any]:
        if not agent_types or not SIGNALS_AVAILABLE:
            return []

        dimensions: list[Any] = []
        seen: set[str] = set()

        for agent_type in agent_types:
            try:
                enum_value = AgentType(agent_type)
            except ValueError:
                continue
            dim = AGENT_DIMENSION_MAP.get(enum_value)
            if dim is None:
                continue
            dim_key = getattr(dim, "value", str(dim))
            if dim_key in seen:
                continue
            seen.add(dim_key)
            dimensions.append(dim)

        return dimensions

    def _format_context(self, context: dict[str, Any]) -> str:
        if not context:
            return ""

        parts = []
        for key, value in context.items():
            if key.startswith("_"):
                if key == "_discoveries":
                    parts.append(f"Previous Discoveries:\n{value}")
                elif key == "_signals":
                    parts.append(f"Previous Signals:\n{value}")
                elif key == "_handoff":
                    parts.append(f"Handoff Context:\n{value.get('reasoning', '')}")
                elif key == "_search_context":
                    parts.append(f"Web Search Results:\n{value}")
            else:
                parts.append(f"{key}: {value}")

        return "\n\n".join(parts)
