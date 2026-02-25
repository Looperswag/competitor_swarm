"""Relevance scoring and citation helper mixin for BaseAgent."""

from __future__ import annotations

import json
import re
from typing import Any

from src.environment import Discovery
from src.llm import Message


class BaseAgentRelevanceMixin:
    """Relevance and retrieval helper methods."""

    def find_relevant_discoveries(
        self,
        query: str,
        exclude_own: bool = True,
        limit: int = 5,
    ) -> list[Discovery]:
        all_discoveries = self._environment.all_discoveries

        if exclude_own:
            all_discoveries = [
                discovery for discovery in all_discoveries
                if discovery.agent_type != self.agent_type.value
            ]

        if not all_discoveries:
            return []

        scored = self._evaluate_relevance_batch(query, all_discoveries)
        scored.sort(key=lambda item: item[1], reverse=True)

        return [discovery for discovery, _ in scored[:limit]]

    def _evaluate_relevance_batch(
        self,
        query: str,
        discoveries: list[Discovery],
    ) -> list[tuple[Discovery, float]]:
        max_eval = 20
        candidates = discoveries[:max_eval]

        prompt = self._build_relevance_prompt(query, candidates)

        try:
            response = self._llm_client.chat(
                messages=[Message(role="user", content=prompt)],
                system_prompt="你是一个相关性评估专家。请评估每个发现与查询的相关性，返回 JSON 数组格式的评分。",
            )
            return self._parse_relevance_response(response.content, candidates)
        except Exception:
            return self._fallback_text_matching(query, candidates)

    def _build_relevance_prompt(self, query: str, discoveries: list[Discovery]) -> str:
        lines = [
            "请评估以下发现与查询的相关性。",
            "",
            f"查询：{query[:200]}",
            "",
            "请对每个发现评分（0.0-1.0），以 JSON 数组格式返回：",
            "[",
            '  {"index": 0, "score": 0.8, "reason": "相关原因"},',
            "  ...",
            "]",
            "",
            "发现列表：",
            "",
        ]

        for idx, discovery in enumerate(discoveries):
            content = discovery.content[:150] + "..." if len(discovery.content) > 150 else discovery.content
            lines.append(f"{idx}. [{discovery.agent_type}] {content}")

        return "\n".join(lines)

    def _parse_relevance_response(
        self,
        response: str,
        discoveries: list[Discovery],
    ) -> list[tuple[Discovery, float]]:
        json_match = re.search(r"\[\s*\{[^\]]*\}\s*\]", response, re.DOTALL)
        if json_match:
            try:
                results = json.loads(json_match.group(0))
                scored = []
                for result in results:
                    idx = result.get("index", 0)
                    score = float(result.get("score", 0.0))
                    if 0 <= idx < len(discoveries):
                        scored.append((discoveries[idx], score))
                return scored
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        return self._fallback_text_matching("", discoveries)

    def _fallback_text_matching(
        self,
        query: str,
        discoveries: list[Discovery],
    ) -> list[tuple[Discovery, float]]:
        scored = []
        query_lower = query.lower() if query else ""

        for discovery in discoveries:
            score = discovery.quality_score
            if query_lower:
                content_lower = discovery.content.lower()
                if query_lower in content_lower:
                    score = min(1.0, score + 0.2)
            scored.append((discovery, score))

        return scored
