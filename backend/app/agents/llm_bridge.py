"""
LLM Bridge: adapts addition.py's LLMClient interface to the Gemini 2.5 Flash API.

Uses the same rate-limiting, retry, and 429-handling pattern as
call_openai_structured in services/external_apis.py, but returns raw
dict/str instead of a Pydantic model — matching what addition.py expects.
"""

import json
import logging
import asyncio
import time
import re
from typing import Any

import httpx

from backend.app.config import settings
from backend.app.agents.addition import LLMClient, MockLLMClient

logger = logging.getLogger("aura.llm_bridge")

# Rate limiting globals (shared across all GeminiLLMClient instances)
_GEMINI_LOCK: asyncio.Lock | None = None
_LAST_REQ_TIME: float = 0.0

# Constants
_MIN_REQUEST_INTERVAL = 13.0  # 5 RPM ≈ 12s gap; 13s for safety
_MAX_RETRIES = 10
_HTTP_TIMEOUT = 45.0


class GeminiLLMClient(LLMClient):
    """
    Bridges addition.py's LLMClient to the Gemini 2.5 Flash API.

    generate_json  → returns parsed dict
    generate_text  → returns raw text string
    """

    def _get_url(self) -> str:
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
        )

    async def _ensure_lock(self) -> asyncio.Lock:
        global _GEMINI_LOCK
        if _GEMINI_LOCK is None:
            _GEMINI_LOCK = asyncio.Lock()
        return _GEMINI_LOCK

    async def _rate_limit(self) -> None:
        """Enforce minimum gap between Gemini requests (5 RPM limit)."""
        global _LAST_REQ_TIME
        lock = await self._ensure_lock()
        async with lock:
            now = time.time()
            elapsed = now - _LAST_REQ_TIME
            if elapsed < _MIN_REQUEST_INTERVAL:
                sleep_time = _MIN_REQUEST_INTERVAL - elapsed
                logger.info(
                    "LLM Bridge rate limiter: sleeping %.2fs to respect 5 RPM limit...",
                    sleep_time,
                )
                await asyncio.sleep(sleep_time)
            _LAST_REQ_TIME = time.time()

    async def _call_gemini(
        self, prompt_text: str, *, json_mode: bool = True
    ) -> str:
        """
        Low-level Gemini call with retries, 429 handling, and rate limiting.
        Returns the raw text from the model response.
        """
        url = self._get_url()
        headers = {"Content-Type": "application/json"}

        gen_config: dict[str, Any] = {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        }
        if json_mode:
            gen_config["responseMimeType"] = "application/json"

        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": gen_config,
        }

        for attempt in range(_MAX_RETRIES):
            await self._rate_limit()

            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                    logger.info(
                        "LLM Bridge: POST attempt %d/%d (json_mode=%s, prompt_len=%d)",
                        attempt + 1,
                        _MAX_RETRIES,
                        json_mode,
                        len(prompt_text),
                    )
                    res = await client.post(url, json=payload, headers=headers)

                # Handle 429 (rate limit)
                if res.status_code == 429:
                    delay = 30.0
                    try:
                        err_data = res.json()
                        for detail in err_data.get("error", {}).get("details", []):
                            if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                                delay_str = detail.get("retryDelay")
                                if delay_str and delay_str.endswith("s"):
                                    delay = float(delay_str[:-1])
                                break
                        if delay == 30.0:
                            msg = err_data.get("error", {}).get("message", "")
                            match = re.search(r"retry in ([\d\.]+)s", msg)
                            if match:
                                delay = float(match.group(1))
                    except Exception:
                        pass
                    delay = max(delay + 1.0, 5.0)
                    logger.warning(
                        "LLM Bridge: 429 rate limited. Retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                # Handle other non-200
                if res.status_code != 200:
                    logger.error(
                        "LLM Bridge: Gemini returned %d: %s",
                        res.status_code,
                        res.text[:500],
                    )
                    if attempt < _MAX_RETRIES - 1:
                        backoff = 2 ** attempt
                        await asyncio.sleep(backoff)
                        continue
                    raise RuntimeError(
                        f"Gemini API returned status {res.status_code} after {_MAX_RETRIES} attempts"
                    )

                data = res.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    logger.error("LLM Bridge: Gemini returned empty candidates")
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise RuntimeError("Gemini returned empty candidates list")

                text = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if not text:
                    logger.error("LLM Bridge: Gemini returned empty text")
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise RuntimeError("Gemini returned empty text content")

                return text.strip()

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.error(
                    "LLM Bridge: network error (attempt %d/%d): %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    e,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

        raise RuntimeError(f"LLM Bridge: exhausted {_MAX_RETRIES} retries")

    # ── LLMClient interface ──────────────────────────────────────────────

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Combine system + user prompts, call Gemini in JSON mode, return parsed dict."""
        combined = (
            f"System Instruction: {system_prompt}\n\n"
            f"{user_prompt}\n\n"
            "CRITICAL: Return ONLY valid JSON, no markdown fences."
        )
        raw_text = await self._call_gemini(combined, json_mode=True)
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            logger.error(
                "LLM Bridge: JSON parse failed: %s — raw text: %s",
                e,
                raw_text[:500],
            )
            raise ValueError(f"Gemini returned invalid JSON: {e}") from e

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Combine system + user prompts, call Gemini in text mode, return raw string."""
        combined = f"System Instruction: {system_prompt}\n\n{user_prompt}"
        return await self._call_gemini(combined, json_mode=False)


def get_llm_client() -> LLMClient:
    """Factory: returns MockLLMClient in MOCK_MODE, GeminiLLMClient otherwise."""
    if settings.MOCK_MODE:
        logger.info("LLM Bridge: MOCK_MODE=True → using MockLLMClient")
        return MockLLMClient()
    if not settings.GEMINI_API_KEY:
        logger.warning(
            "LLM Bridge: GEMINI_API_KEY not set, falling back to MockLLMClient"
        )
        return MockLLMClient()
    logger.info("LLM Bridge: using GeminiLLMClient")
    return GeminiLLMClient()
