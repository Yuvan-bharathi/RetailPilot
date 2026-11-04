"""Cache service: Redis cache-aside with fail-open semantics (SD-01, SD-11, D-35).

Stores versioned dashboard summaries (`dash:{run_id}:{store_id}:{period}`), handles cache invalidation
via key scanning, and manages latest run tracking.
"""

from __future__ import annotations

import logging
from uuid import UUID

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class CacheService:
    client: redis.Redis | None

    def __init__(self, client: redis.Redis | None = None) -> None:
        if client is not None:
            self.client = client
        else:
            try:
                settings = get_settings()
                self.client = redis.Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                )
            except Exception as e:
                logger.warning("Failed to initialize Redis client: %s", e)
                self.client = None

    def get(self, key: str) -> str | None:
        if self.client is None:
            return None
        try:
            val = self.client.get(key)
            return str(val) if val is not None else None
        except redis.RedisError as e:
            logger.warning("Redis error on GET %s (failing open): %s", key, e)
            return None

    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        if self.client is None:
            return False
        try:
            if ttl is not None:
                self.client.set(key, value, ex=ttl)
            else:
                self.client.set(key, value)
            return True
        except redis.RedisError as e:
            logger.warning("Redis error on SET %s: %s", key, e)
            return False

    def get_latest_run_id(self) -> UUID | None:
        val = self.get("latest_run_id")
        if val:
            try:
                return UUID(val)
            except ValueError:
                return None
        return None

    def set_latest_run_id(self, run_id: UUID) -> None:
        self.set("latest_run_id", str(run_id))

    def warm(self, run_id: UUID, store_ids: list[UUID]) -> int:
        """Warms cache for latest run (placeholder for precomputed dashboard slices)."""
        # Store latest run indicator
        self.set_latest_run_id(run_id)
        return len(store_ids)

    def invalidate_run(self, run_id: UUID) -> int:
        """Deletes keys matching *:{run_id}:* via SCAN."""
        if self.client is None:
            return 0
        deleted = 0
        try:
            pattern = f"*:{run_id}:*"
            cursor = 0
            while True:
                cursor, keys = self.client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    self.client.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
        except redis.RedisError as e:
            logger.warning("Redis error on invalidate_run: %s", e)
        return deleted

    def invalidate_store_keys(self, store_ids: list[UUID], prefixes: list[str]) -> int:
        """Invalidates cache keys matching {prefix}:*:{store_id}:* (SD-10, SD-12)."""
        if self.client is None or not store_ids:
            return 0
        deleted = 0
        try:
            for store_id in store_ids:
                for prefix in prefixes:
                    pattern = f"{prefix}:*:{store_id}:*"
                    cursor = 0
                    while True:
                        cursor, keys = self.client.scan(cursor=cursor, match=pattern, count=100)
                        if keys:
                            self.client.delete(*keys)
                            deleted += len(keys)
                        if cursor == 0:
                            break
        except redis.RedisError as e:
            logger.warning("Redis error on invalidate_store_keys: %s", e)
        return deleted
