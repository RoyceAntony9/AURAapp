import redis
import json
import logging
from typing import Any, Optional
from backend.app.config import settings

logger = logging.getLogger("aura.redis")

class RedisClient:
    def __init__(self):
        self.enabled = False
        self._fallback_store = {}
        try:
            # Parse Redis URL and configure client
            self.client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            # Test connection
            self.client.ping()
            self.enabled = True
            logger.info("Connected to Redis successfully.")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory store.")
            self.client = None

    def get(self, key: str) -> Optional[str]:
        if self.enabled and self.client:
            try:
                return self.client.get(key)
            except Exception as e:
                logger.error(f"Redis GET error: {e}")
        return self._fallback_store.get(key)

    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        if self.enabled and self.client:
            try:
                self.client.set(key, value, ex=ex)
                return True
            except Exception as e:
                logger.error(f"Redis SET error: {e}")
        self._fallback_store[key] = value
        # In-memory simple TTL simulation is not needed for mock/fallback run, but we can store it.
        return True

    def get_json(self, key: str) -> Optional[Any]:
        val = self.get(key)
        if val:
            try:
                return json.loads(val)
            except Exception:
                return None
        return None

    def set_json(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        try:
            return self.set(key, json.dumps(value), ex=ex)
        except Exception as e:
            logger.error(f"Failed to serialize JSON for Redis: {e}")
            return False

    def delete(self, key: str) -> bool:
        if self.enabled and self.client:
            try:
                self.client.delete(key)
                return True
            except Exception as e:
                logger.error(f"Redis DELETE error: {e}")
        if key in self._fallback_store:
            del self._fallback_store[key]
            return True
        return False

redis_client = RedisClient()
