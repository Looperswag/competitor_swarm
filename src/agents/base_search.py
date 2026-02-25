"""Search execution mixin for BaseAgent."""

from __future__ import annotations

import concurrent.futures
import logging
import time
from typing import Any

from src.error_types import ErrorType

logger = logging.getLogger(__name__)


class BaseAgentSearchMixin:
    """Search helpers with resilient fallbacks."""

    def search_context(
        self,
        query: str,
        max_results: int = 10,
        check_freshness: bool = True,
        max_age_hours: int = 24,
        timeout: float = 45.0,
    ) -> str:
        if not self._search_tool:
            msg = f"[{self.agent_type.value}] Search tool not available for query: {query[:50]}..."
            logger.warning(msg)
            self._record_runtime_warning(
                message=msg,
                error_type=ErrorType.SEARCH_FAILURE.value,
                recoverable=True,
                hint="Configure search provider or API key",
            )
            return ""

        search_start = time.time()

        try:
            from src.search.base import SearchTimeRange

            def _do_search():
                return self._search_tool.search(
                    query=query,
                    time_range=SearchTimeRange.ONE_YEAR,
                    max_results=max_results,
                )

            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(_do_search)
            try:
                results = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                elapsed = time.time() - search_start
                future.cancel()
                msg = (
                    f"[{self.agent_type.value}] Search '{query[:40]}...' "
                    f"timed out after {elapsed:.2f}s (limit: {timeout}s)"
                )
                logger.warning(msg)
                self._record_runtime_warning(
                    message=msg,
                    error_type=ErrorType.UPSTREAM_TIMEOUT.value,
                    recoverable=True,
                    hint="Consider lower max_results or increase timeout",
                )
                return ""
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            if check_freshness:
                results = [
                    r for r in results
                    if self._is_result_fresh(r, max_age_hours)
                ]

            formatted = []
            for i, result in enumerate(results, 1):
                formatted.append(f"{i}. {result.title}")
                formatted.append(f"   来源: {result.site_name or result.url}")
                formatted.append(f"   摘要: {result.summary}")
                formatted.append(f"   链接: {result.url}")
                formatted.append("")

            elapsed = time.time() - search_start
            logger.info(
                "[%s] Search '%s...' completed in %.2fs, %s results",
                self.agent_type.value,
                query[:40],
                elapsed,
                len(results),
            )
            return "\n".join(formatted)

        except Exception as exc:
            elapsed = time.time() - search_start
            msg = (
                f"[{self.agent_type.value}] Search '{query[:40]}...' "
                f"failed after {elapsed:.2f}s: {exc}"
            )
            logger.error(msg)
            self._record_runtime_warning(
                message=msg,
                error_type=ErrorType.SEARCH_FAILURE.value,
                recoverable=True,
                hint="Check upstream search provider status",
            )
            return ""

    def search_context_async(
        self,
        queries: list[str],
        max_results: int = 10,
        timeout: float = 45.0,
    ) -> dict[str, str]:
        if not self._search_tool:
            logger.warning("[%s] Search tool not available", self.agent_type.value)
            self._record_runtime_warning(
                message=f"[{self.agent_type.value}] Search tool not available",
                error_type=ErrorType.SEARCH_FAILURE.value,
                recoverable=True,
                hint="Configure search provider or API key",
            )
            return {}

        results: dict[str, str] = {}

        def search_one(query: str) -> tuple[str, str]:
            result = self.search_context(
                query=query,
                max_results=max_results,
                timeout=timeout,
            )
            return query, result

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(queries) or 1))
        future_to_query = {
            executor.submit(search_one, query): query
            for query in queries
        }

        try:
            for future in concurrent.futures.as_completed(
                future_to_query,
                timeout=max(timeout, 1.0) * max(len(queries), 1),
            ):
                query = future_to_query[future]
                try:
                    result_query, result_text = future.result()
                    if result_text:
                        results[result_query] = result_text
                except Exception as exc:
                    logger.warning(
                        "[%s] Parallel search '%s...' failed: %s",
                        self.agent_type.value,
                        query[:30],
                        exc,
                    )
                    self._record_runtime_warning(
                        message=f"Parallel search failed for query '{query[:50]}'",
                        error_type=ErrorType.SEARCH_FAILURE.value,
                        recoverable=True,
                        hint=str(exc),
                    )
        except concurrent.futures.TimeoutError:
            for future, query in future_to_query.items():
                if future.done():
                    continue
                future.cancel()
                self._record_runtime_warning(
                    message=f"Parallel search timed out for query '{query[:50]}'",
                    error_type=ErrorType.UPSTREAM_TIMEOUT.value,
                    recoverable=True,
                    hint="Reduce query count or timeout per query",
                )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        logger.info(
            "[%s] Parallel search: %s/%s queries succeeded",
            self.agent_type.value,
            len(results),
            len(queries),
        )
        return results

    def _is_result_fresh(self, result: Any, max_age_hours: int) -> bool:
        return True
