"""
LLM Client — HTTP client with retry, circuit breaker, and multi-model support.
Adapted from Zork-Opus llm_client.py for Pokemon-Opus.
"""

from __future__ import annotations

import json
import logging
import time
import random
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class CircuitBreakerOpen(Exception):
    """Raised when too many consecutive failures have occurred."""


class LLMClient:
    """HTTP client for LLM APIs with retry logic and circuit breaker.

    Supports Anthropic, OpenRouter, and local LLM endpoints.
    Each call specifies a role (agent, battle, strategist, memory) which
    maps to a (base_url, api_key, model, sampling) tuple via config.
    """

    def __init__(self, config):
        self.config = config
        self._retry = config.retry

        # Circuit breaker state
        self._consecutive_failures: int = 0
        self._circuit_open_until: float = 0.0

    def _check_circuit_breaker(self) -> None:
        if self._consecutive_failures >= self._retry["circuit_breaker_failure_threshold"]:
            if time.time() < self._circuit_open_until:
                raise CircuitBreakerOpen(
                    f"Circuit breaker open: {self._consecutive_failures} consecutive failures. "
                    f"Recovery in {self._circuit_open_until - time.time():.0f}s"
                )
            # Recovery period elapsed — half-open, allow one attempt
            logger.info("Circuit breaker half-open, allowing probe request")

    def _record_success(self) -> None:
        self._consecutive_failures = 0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._retry["circuit_breaker_failure_threshold"]:
            self._circuit_open_until = time.time() + self._retry["circuit_breaker_recovery_timeout"]
            logger.error(
                f"Circuit breaker OPEN after {self._consecutive_failures} failures. "
                f"Blocking requests for {self._retry['circuit_breaker_recovery_timeout']}s"
            )

    def _build_headers(self, role: str) -> Dict[str, str]:
        api_key = self.config.api_key_for(role)
        base_url = self.config.base_url_for(role)
        headers = {"Content-Type": "application/json"}

        if "anthropic" in base_url.lower():
            headers["x-api-key"] = api_key or ""
            headers["anthropic-version"] = "2023-06-01"
        else:
            # OpenAI-compatible (OpenRouter, local LLMs)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        return headers

    def _build_request_body(
        self, role: str, messages: List[Dict[str, str]], system: Optional[str] = None
    ) -> Dict[str, Any]:
        base_url = self.config.base_url_for(role)
        model = self.config.model_for(role)
        sampling = self.config.sampling_for(role)

        if "anthropic" in base_url.lower():
            # Anthropic Messages API format
            body: Dict[str, Any] = {
                "model": model,
                "max_tokens": sampling.get("max_tokens", 4096),
                "messages": messages,
            }
            if system:
                body["system"] = system
            if "temperature" in sampling:
                body["temperature"] = sampling["temperature"]
            return body
        else:
            # OpenAI-compatible format
            oai_messages: List[Dict[str, str]] = []
            if system:
                oai_messages.append({"role": "system", "content": system})
            oai_messages.extend(messages)
            body = {
                "model": model,
                "messages": oai_messages,
                "max_tokens": sampling.get("max_tokens", 4096),
            }
            if "temperature" in sampling:
                body["temperature"] = sampling["temperature"]
            if "top_p" in sampling:
                body["top_p"] = sampling["top_p"]
            return body

    def _get_endpoint(self, role: str) -> str:
        base_url = self.config.base_url_for(role).rstrip("/")
        if "anthropic" in base_url.lower():
            return f"{base_url}/messages"
        else:
            return f"{base_url}/chat/completions"

    def _extract_content(self, response_data: Dict[str, Any], base_url: str) -> str:
        """Extract text content from API response."""
        if "anthropic" in base_url.lower():
            # Anthropic response format
            content_blocks = response_data.get("content", [])
            texts = [b["text"] for b in content_blocks if b.get("type") == "text"]
            return "\n".join(texts)
        else:
            # OpenAI-compatible format
            choices = response_data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""

    def _extract_usage(self, response_data: Dict[str, Any], base_url: str) -> Dict[str, int]:
        """Extract token usage from API response."""
        usage = response_data.get("usage", {})
        if "anthropic" in base_url.lower():
            return {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }
        else:
            return {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }

    async def chat(
        self,
        role: str,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a chat completion request with retry logic.

        Args:
            role: Model role (agent, battle, strategist, memory)
            messages: List of {role, content} messages
            system: Optional system prompt

        Returns:
            Dict with 'content' (str), 'usage' (dict), 'model' (str)
        """
        self._check_circuit_breaker()

        endpoint = self._get_endpoint(role)
        headers = self._build_headers(role)
        body = self._build_request_body(role, messages, system)
        base_url = self.config.base_url_for(role)

        max_retries = self._retry["max_retries"]
        delay = self._retry["initial_delay"]

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._retry["timeout_seconds"]) as client:
                    resp = await client.post(endpoint, json=body, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()

                content = self._extract_content(data, base_url)
                usage = self._extract_usage(data, base_url)

                self._record_success()
                logger.debug(
                    f"LLM {role} response: {len(content)} chars, "
                    f"{usage.get('input_tokens', 0)}+{usage.get('output_tokens', 0)} tokens"
                )
                return {
                    "content": content,
                    "usage": usage,
                    "model": self.config.model_for(role),
                }

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                # Don't retry auth errors or bad requests
                if status in (401, 403, 400):
                    self._record_failure()
                    raise
                # Rate limit — respect Retry-After if present
                if status == 429:
                    retry_after = e.response.headers.get("retry-after")
                    wait = float(retry_after) if retry_after else delay
                    logger.warning(f"Rate limited, waiting {wait:.1f}s (attempt {attempt + 1})")
                    await _async_sleep(wait)
                    continue
                # Server error — retry
                logger.warning(f"HTTP {status} from {role} (attempt {attempt + 1}): {e}")

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                logger.warning(f"Connection error for {role} (attempt {attempt + 1}): {e}")

            except Exception as e:
                logger.error(f"Unexpected error for {role} (attempt {attempt + 1}): {e}")

            # Exponential backoff with jitter
            if attempt < max_retries:
                jitter = random.uniform(0, self._retry["jitter_factor"] * delay)
                sleep_time = min(delay + jitter, self._retry["max_delay"])
                logger.info(f"Retrying {role} in {sleep_time:.1f}s")
                await _async_sleep(sleep_time)
                delay *= self._retry["exponential_base"]

        self._record_failure()
        raise RuntimeError(f"LLM {role} failed after {max_retries + 1} attempts")

    async def chat_json(
        self,
        role: str,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Chat and parse the response as JSON. Returns parsed dict plus usage."""
        result = await self.chat(role, messages, system)
        content = result["content"]

        # Extract JSON from markdown code fences if present
        if "```json" in content:
            start = content.index("```json") + 7
            end = content.index("```", start)
            content = content[start:end].strip()
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start)
            content = content[start:end].strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse failed for {role}: {e}\nContent: {content[:500]}")
            raise

        return {"parsed": parsed, "usage": result["usage"], "model": result["model"]}


async def _async_sleep(seconds: float) -> None:
    """Async sleep wrapper for testability."""
    import asyncio
    await asyncio.sleep(seconds)
