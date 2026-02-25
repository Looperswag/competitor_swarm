"""Parsing and minimum-result mixin for BaseAgent."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from src.environment import Discovery, DiscoverySource
from src.error_types import ErrorType


class BaseAgentParsingMixin:
    """Discovery/signal parsing and fill-up logic."""

    MAX_PARSED_DISCOVERIES_PER_RESPONSE = 60

    def _ensure_min_discoveries(
        self,
        discoveries: list[Any],
        target: str,
        context: dict[str, Any],
        prompt_builder: "Callable[[str, int], str] | None" = None,
    ) -> list[Any]:
        if len(discoveries) >= self.MIN_DISCOVERIES:
            return discoveries

        additional_count = min(
            self.TARGET_DISCOVERIES - len(discoveries),
            max(self.MAX_DISCOVERIES - len(discoveries), 0),
        )
        if additional_count <= 0:
            return discoveries

        if prompt_builder:
            deep_prompt = prompt_builder(target, additional_count)
        else:
            deep_prompt = self._build_deep_search_prompt(target, additional_count)

        deep_response = self.think_with_discoveries(
            deep_prompt,
            agent_types=[self.agent_type.value],
            context=context,
        )

        additional = self._parse_and_store_discoveries_from_text(deep_response, target)
        return (discoveries + additional)[: self.MAX_DISCOVERIES]

    async def _ensure_min_discoveries_async(
        self,
        discoveries: list[Any],
        target: str,
        context: dict[str, Any],
        prompt_builder: "Callable[[str, int], str] | None" = None,
    ) -> list[Any]:
        if len(discoveries) >= self.MIN_DISCOVERIES:
            return discoveries

        additional_count = min(
            self.TARGET_DISCOVERIES - len(discoveries),
            max(self.MAX_DISCOVERIES - len(discoveries), 0),
        )
        if additional_count <= 0:
            return discoveries

        if prompt_builder:
            deep_prompt = prompt_builder(target, additional_count)
        else:
            deep_prompt = self._build_deep_search_prompt(target, additional_count)

        deep_response = await self.think_with_discoveries_async(
            deep_prompt,
            agent_types=[self.agent_type.value],
            context=context,
        )
        additional = self._parse_and_store_discoveries_from_text(deep_response, target)
        return (discoveries + additional)[: self.MAX_DISCOVERIES]

    def _ensure_min_signals(
        self,
        signal_dicts: list[dict[str, Any]],
        target: str,
        context: dict[str, Any],
        prompt_builder: "Callable[[str, int], str] | None" = None,
    ) -> list[dict[str, Any]]:
        if len(signal_dicts) >= self.MIN_DISCOVERIES:
            return signal_dicts

        additional_count = min(
            self.TARGET_DISCOVERIES - len(signal_dicts),
            max(self.MAX_DISCOVERIES - len(signal_dicts), 0),
        )
        if additional_count <= 0:
            return signal_dicts

        if prompt_builder:
            deep_prompt = prompt_builder(target, additional_count)
        else:
            deep_prompt = self._build_deep_search_prompt(target, additional_count)

        dimensions = [self._dimension] if self._dimension is not None else None
        deep_response = self.think_with_signals(
            deep_prompt,
            dimensions=dimensions,
            context=context,
        )

        parser = getattr(self, "_parse_and_store_signals", None)
        if not callable(parser):
            return signal_dicts

        try:
            parsed_items = parser(deep_response, target) or []
        except Exception as exc:
            self._record_runtime_warning(
                message=f"Signal parser failed during fill-up: {exc}",
                error_type=ErrorType.PARSE_FAILURE.value,
                recoverable=True,
                hint="Inspect signal parser implementation",
            )
            return signal_dicts

        additional_dicts: list[dict[str, Any]] = []
        for item in parsed_items:
            if isinstance(item, dict):
                additional_dicts.append(item)
            elif hasattr(item, "to_dict"):
                additional_dicts.append(item.to_dict())

        return (signal_dicts + additional_dicts)[: self.MAX_DISCOVERIES]

    async def _ensure_min_signals_async(
        self,
        signal_dicts: list[dict[str, Any]],
        target: str,
        context: dict[str, Any],
        prompt_builder: "Callable[[str, int], str] | None" = None,
    ) -> list[dict[str, Any]]:
        if len(signal_dicts) >= self.MIN_DISCOVERIES:
            return signal_dicts

        additional_count = min(
            self.TARGET_DISCOVERIES - len(signal_dicts),
            max(self.MAX_DISCOVERIES - len(signal_dicts), 0),
        )
        if additional_count <= 0:
            return signal_dicts

        if prompt_builder:
            deep_prompt = prompt_builder(target, additional_count)
        else:
            deep_prompt = self._build_deep_search_prompt(target, additional_count)

        dimensions = [self._dimension] if self._dimension is not None else None
        deep_response = await self.think_with_signals_async(
            deep_prompt,
            dimensions=dimensions,
            context=context,
        )

        parser = getattr(self, "_parse_and_store_signals", None)
        if not callable(parser):
            return signal_dicts

        try:
            parsed_items = parser(deep_response, target) or []
        except Exception as exc:
            self._record_runtime_warning(
                message=f"Signal parser failed during async fill-up: {exc}",
                error_type=ErrorType.PARSE_FAILURE.value,
                recoverable=True,
                hint="Inspect signal parser implementation",
            )
            return signal_dicts

        additional_dicts: list[dict[str, Any]] = []
        for item in parsed_items:
            if isinstance(item, dict):
                additional_dicts.append(item)
            elif hasattr(item, "to_dict"):
                additional_dicts.append(item.to_dict())

        return (signal_dicts + additional_dicts)[: self.MAX_DISCOVERIES]

    def _build_deep_search_prompt(self, target: str, count: int) -> str:
        return f"""请继续对「{target}」进行深入分析，再提供至少 {count} 条新的发现。

请从以下角度补充：
1. 之前未覆盖的细节
2. 更深入的分析
3. 更具体的案例或数据

每条发现单独一行，以「- 」开头。
"""

    def _parse_and_store_discoveries_from_text(
        self,
        text: str,
        target: str,
        source: DiscoverySource = DiscoverySource.ANALYSIS,
    ) -> list[Any]:
        json_discoveries = self._try_parse_json_discoveries(text, target, source)
        if json_discoveries:
            return json_discoveries[: self.MAX_PARSED_DISCOVERIES_PER_RESPONSE]

        list_discoveries = self._try_parse_list_discoveries(text, target, source)
        if list_discoveries:
            return list_discoveries[: self.MAX_PARSED_DISCOVERIES_PER_RESPONSE]

        paragraph_discoveries = self._try_parse_paragraph_discoveries(text, target, source)
        if paragraph_discoveries:
            return paragraph_discoveries[: self.MAX_PARSED_DISCOVERIES_PER_RESPONSE]

        fallback = self._build_parse_fallback_discovery(text, target, source)
        if fallback is not None:
            return [fallback]

        return []

    def _try_parse_json_discoveries(
        self,
        text: str,
        target: str,
        source: DiscoverySource,
    ) -> list[Any] | None:
        patterns = [
            r"```json\s*(\[.*?\])\s*```",
            r"```\s*(\[.*?\])\s*```",
            r"\[\s*\{[^\]]*\}\s*\]",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if not match:
                continue
            try:
                json_str = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                data = json.loads(json_str)
            except (json.JSONDecodeError, ValueError):
                continue

            if not isinstance(data, list):
                continue

            discoveries = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                content = (
                    item.get("content")
                    or item.get("description")
                    or item.get("text")
                    or item.get("evidence")
                    or item.get("finding", "")
                )
                if not content or not self._is_valid_discovery(content):
                    continue
                quality = self._calculate_quality_score(item, content)
                discovery = self.add_discovery(
                    content=content,
                    source=source,
                    quality_score=quality,
                    metadata={
                        "target": target,
                        **{k: v for k, v in item.items() if k not in [
                            "content", "description", "text", "evidence", "finding",
                        ]},
                    },
                )
                discoveries.append(discovery)

            if discoveries:
                return discoveries
        return None

    def _try_parse_list_discoveries(
        self,
        text: str,
        target: str,
        source: DiscoverySource,
    ) -> list[Any] | None:
        discoveries = []
        lines = text.split("\n")

        list_marker_count = sum(
            1 for line in lines
            if line.strip() and any(
                line.strip().startswith(marker)
                for marker in ["- ", "• ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."]
            )
        )
        if list_marker_count < 3:
            return None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            list_patterns = [
                r"^[\-\•\*]\s+",
                r"^\d+\.\s+",
                r"^\d+\)\s+",
            ]

            content = None
            for pattern in list_patterns:
                if re.match(pattern, line):
                    content = re.sub(pattern, "", line, count=1)
                    break

            if content is None or not self._is_valid_discovery(content):
                continue

            quality = self._calculate_quality_score({}, content)
            discovery = self.add_discovery(
                content=content,
                source=source,
                quality_score=quality,
                metadata={"target": target},
            )
            discoveries.append(discovery)

        return discoveries if discoveries else None

    def _try_parse_paragraph_discoveries(
        self,
        text: str,
        target: str,
        source: DiscoverySource,
    ) -> list[Any]:
        discoveries = []

        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        paragraphs = re.split(r"\n\s*\n|(?<=[.!?。！？])\s*\n", text)

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            paragraph = re.sub(
                r"^(发现|结论|分析|要点|总结|note|discovery|conclusion)\s*[:：]?\s*",
                "",
                paragraph,
                flags=re.IGNORECASE,
            )
            if not self._is_valid_discovery(paragraph):
                continue
            quality = self._calculate_quality_score({}, paragraph)
            discovery = self.add_discovery(
                content=paragraph,
                source=source,
                quality_score=quality,
                metadata={"target": target},
            )
            discoveries.append(discovery)

        return discoveries

    def _build_parse_fallback_discovery(
        self,
        text: str,
        target: str,
        source: DiscoverySource,
    ) -> Discovery | None:
        cleaned = " ".join(str(text).split()).strip()
        if not cleaned:
            return None

        fallback_text = cleaned[:220]
        if len(cleaned) > 220:
            fallback_text += "..."

        self._record_runtime_warning(
            message="All discovery parsing strategies failed; fallback discovery created",
            error_type=ErrorType.PARSE_FAILURE.value,
            recoverable=True,
            hint="Inspect LLM output format drift",
        )

        return self.add_discovery(
            content=fallback_text,
            source=source,
            quality_score=0.3,
            metadata={
                "target": target,
                "parse_fallback": True,
                "raw_length": len(cleaned),
            },
        )

    def _is_valid_discovery(self, content: str) -> bool:
        content = content.strip()
        if len(content) < 15:
            return False

        invalid_patterns = [
            r"^暂无",
            r"^待补充",
            r"^to be determined",
            r"^tbd",
            r"^n/a",
            r"^无数据",
            r"^无发现",
            r"^没有找到",
            r"^以下是",
            r"^the following",
            r"^please note",
            r"^注意",
        ]
        for pattern in invalid_patterns:
            if re.match(pattern, content, re.IGNORECASE):
                return False

        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", content))
        has_english_words = bool(re.search(r"[a-zA-Z]{3,}", content))
        return has_chinese or has_english_words

    def _calculate_quality_score(self, item: dict[str, Any], content: str) -> float:
        if "quality_score" in item:
            try:
                return max(0.0, min(1.0, float(item["quality_score"])))
            except (ValueError, TypeError):
                pass

        score = 0.5
        score += min(0.3, len(content) / 500)
        if re.search(r"\d+%|\d+万|\d+亿|\d+\.\d+|\d+个|\d+项", content):
            score += 0.1
        if re.search(r"(根据|来自|引用|source|reference|官网|文档)", content, re.IGNORECASE):
            score += 0.1
        if re.search(r"[：:：]|、|，|；|;|-", content):
            score += 0.1

        return min(1.0, score)

    def _parse_discoveries_from_response(self, response: str) -> list[dict[str, Any]]:
        lines = response.strip().split("\n")

        discoveries = []
        current_discovery: dict[str, Any] = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("- ") or line.startswith("• "):
                if current_discovery:
                    discoveries.append(current_discovery)
                current_discovery = {"content": line[2:], "quality_score": 0.5}
            elif current_discovery:
                current_discovery["content"] += " " + line

        if current_discovery:
            discoveries.append(current_discovery)

        return discoveries
