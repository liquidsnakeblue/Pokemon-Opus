"""
Game Client — async HTTP wrapper for PokemonOpenClaude REST API.
Talks to the emulator server to read state, send actions, and capture screenshots.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class GameClientError(Exception):
    """Raised when the game server returns an error or is unreachable."""


class GameClient:
    """Async HTTP client for the PokemonOpenClaude game server."""

    def __init__(self, base_url: str = "http://localhost:8765", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ── Health ─────────────────────────────────────────────────────────

    async def health(self) -> bool:
        """Check if the game server is running and emulator is ready."""
        try:
            resp = await self._client.get("/health")
            data = resp.json()
            return data.get("emulator_ready", False)
        except (httpx.HTTPError, Exception) as e:
            logger.warning(f"Health check failed: {e}")
            return False

    async def wait_for_server(self, max_retries: int = 30, delay: float = 1.0) -> bool:
        """Wait for the game server to become available."""
        for attempt in range(max_retries):
            if await self.health():
                logger.info(f"Game server ready after {attempt + 1} attempt(s)")
                return True
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
        logger.error(f"Game server not ready after {max_retries} attempts")
        return False

    # ── State ──────────────────────────────────────────────────────────

    async def get_state(self) -> Dict[str, Any]:
        """Get full structured game state from RAM."""
        resp = await self._client.get("/state")
        resp.raise_for_status()
        return resp.json()

    # ── Screenshots ────────────────────────────────────────────────────

    async def screenshot(self) -> bytes:
        """Get current frame as raw PNG bytes."""
        resp = await self._client.get("/screenshot")
        resp.raise_for_status()
        return resp.content

    async def screenshot_base64(self) -> str:
        """Get current frame as base64-encoded string."""
        resp = await self._client.get("/screenshot/base64")
        resp.raise_for_status()
        data = resp.json()
        return data.get("image", data.get("screenshot", ""))

    # ── Actions ─────────────────────────────────────────────────────────

    async def act(self, actions: List[str]) -> Dict[str, Any]:
        """Execute a sequence of button presses / movements.

        Actions follow PokemonOpenClaude protocol:
        - press_a, press_b, press_start, press_select
        - walk_up, walk_down, walk_left, walk_right
        - hold_b_N (hold B for N frames)
        - wait_N (tick N frames)
        - a_until_dialog_end
        """
        resp = await self._client.post("/action", json={"actions": actions})
        resp.raise_for_status()
        return resp.json()

    # ── Save / Load ────────────────────────────────────────────────────

    async def save(self, name: str) -> Dict[str, Any]:
        """Save emulator state to disk."""
        resp = await self._client.post("/save", json={"name": name})
        resp.raise_for_status()
        return resp.json()

    async def load(self, name: str) -> Dict[str, Any]:
        """Load emulator state from disk."""
        resp = await self._client.post("/load", json={"name": name})
        resp.raise_for_status()
        return resp.json()

    async def list_saves(self) -> List[Dict[str, Any]]:
        """List all available save states."""
        resp = await self._client.get("/saves")
        resp.raise_for_status()
        data = resp.json()
        return data.get("saves", [])

    # ── Convenience ─────────────────────────────────────────────────────

    async def get_state_and_screenshot(self) -> tuple[Dict[str, Any], str]:
        """Get both state and screenshot in parallel."""
        state_task = asyncio.create_task(self.get_state())
        screenshot_task = asyncio.create_task(self.screenshot_base64())
        state = await state_task
        screenshot = await screenshot_task
        return state, screenshot
