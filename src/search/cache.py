"""搜索缓存管理。

基于文件系统的搜索结果缓存，支持自动过期清理。
"""

import hashlib
import json
import logging
import pickle
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from src.search.base import SearchResult, SearchTimeRange


@dataclass(frozen=True)
class CacheEntry:
    """缓存条目数据类。"""

    results: list[SearchResult]
    cached_at: float
    ttl: int


class SearchCache:
    """搜索缓存。

    基于文件系统的缓存，支持 TTL 过期和自动清理。
    """

    def __init__(
        self,
        cache_dir: str | Path = "data/cache/search",
        default_ttl: int = 3600,
        enabled: bool = True,
    ) -> None:
        """初始化搜索缓存。

        Args:
            cache_dir: 缓存目录路径
            default_ttl: 默认缓存过期时间（秒）
            enabled: 是否启用缓存
        """
        self._cache_dir = Path(cache_dir)
        self._default_ttl = default_ttl
        self._enabled = enabled
        self._lock = threading.RLock()

        if self._enabled:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get(
        self,
        query: str,
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
    ) -> list[SearchResult] | None:
        """获取缓存结果。

        Args:
            query: 搜索查询
            time_range: 时间范围
            max_results: 最大结果数

        Returns:
            缓存的结果，不存在或已过期时返回 None
        """
        if not self._enabled:
            return None

        cache_key = self._make_cache_key(query, time_range, max_results)
        cache_file = self._cache_dir / f"{cache_key}.pkl"

        with self._lock:
            if not cache_file.exists():
                return None

            try:
                with open(cache_file, "rb") as f:
                    entry: CacheEntry = pickle.load(f)

                # 检查是否过期
                if time.time() - entry.cached_at > entry.ttl:
                    cache_file.unlink(missing_ok=True)
                    return None

                return entry.results
            except Exception as e:
                logger.warning(f"Failed to read cache: {e}")
                return None

    def set(
        self,
        query: str,
        results: list[SearchResult],
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
        ttl: int | None = None,
    ) -> None:
        """设置缓存结果。

        Args:
            query: 搜索查询
            results: 搜索结果
            time_range: 时间范围
            max_results: 最大结果数
            ttl: 缓存过期时间（秒），默认使用 default_ttl
        """
        if not self._enabled:
            return

        cache_key = self._make_cache_key(query, time_range, max_results)
        cache_file = self._cache_dir / f"{cache_key}.pkl"

        entry = CacheEntry(
            results=results,
            cached_at=time.time(),
            ttl=ttl or self._default_ttl,
        )

        with self._lock:
            try:
                with open(cache_file, "wb") as f:
                    pickle.dump(entry, f)
            except Exception as e:
                logger.warning(f"Failed to write cache: {e}")

    def invalidate(
        self,
        query: str,
        time_range: SearchTimeRange = SearchTimeRange.ONE_YEAR,
        max_results: int = 10,
    ) -> None:
        """使缓存失效。

        Args:
            query: 搜索查询
            time_range: 时间范围
            max_results: 最大结果数
        """
        if not self._enabled:
            return

        cache_key = self._make_cache_key(query, time_range, max_results)
        cache_file = self._cache_dir / f"{cache_key}.pkl"

        with self._lock:
            cache_file.unlink(missing_ok=True)

    def clear(self) -> None:
        """清空所有缓存。"""
        if not self._enabled:
            return

        with self._lock:
            for cache_file in self._cache_dir.glob("*.pkl"):
                cache_file.unlink(missing_ok=True)

    def cleanup_expired(self) -> int:
        """清理过期的缓存文件。

        Returns:
            清理的文件数量
        """
        if not self._enabled:
            return 0

        count = 0
        current_time = time.time()

        with self._lock:
            for cache_file in self._cache_dir.glob("*.pkl"):
                try:
                    with open(cache_file, "rb") as f:
                        entry: CacheEntry = pickle.load(f)

                    if current_time - entry.cached_at > entry.ttl:
                        cache_file.unlink()
                        count += 1
                except Exception:
                    # 损坏的缓存文件也删除
                    cache_file.unlink(missing_ok=True)
                    count += 1

        return count

    @staticmethod
    def _make_cache_key(
        query: str,
        time_range: SearchTimeRange,
        max_results: int,
    ) -> str:
        """生成缓存键。

        Args:
            query: 搜索查询
            time_range: 时间范围
            max_results: 最大结果数

        Returns:
            缓存键（MD5 哈希）
        """
        key_data = f"{query}:{time_range.value}:{max_results}"
        return hashlib.md5(key_data.encode()).hexdigest()[:16]

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息。

        Returns:
            包含缓存统计的字典
        """
        if not self._enabled:
            return {"enabled": False}

        total_files = 0
        total_size = 0
        expired_files = 0
        current_time = time.time()

        with self._lock:
            for cache_file in self._cache_dir.glob("*.pkl"):
                total_files += 1
                total_size += cache_file.stat().st_size

                try:
                    with open(cache_file, "rb") as f:
                        entry: CacheEntry = pickle.load(f)

                    if current_time - entry.cached_at > entry.ttl:
                        expired_files += 1
                except Exception:
                    expired_files += 1

        return {
            "enabled": True,
            "total_files": total_files,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "expired_files": expired_files,
            "cache_dir": str(self._cache_dir),
        }
