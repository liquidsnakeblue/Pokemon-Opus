"""
Streaming Server — FastAPI + WebSocket for real-time viewer updates.
Broadcasts game events, AI reasoning, and state snapshots to connected clients.
Includes MJPEG endpoint for real-time frame streaming from the emulator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Set, TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from pokemon_opus.game_client import GameClient

logger = logging.getLogger(__name__)

# Frame streaming config
STREAM_TARGET_FPS = 30
STREAM_FRAME_INTERVAL = 1.0 / STREAM_TARGET_FPS


class StreamServer:
    """WebSocket broadcast server for the Pokemon-Opus viewer."""

    def __init__(self, host: str = "0.0.0.0", port: int = 3000, enable_cors: bool = True):
        self.host = host
        self.port = port
        self._clients: Set[WebSocket] = set()
        self._stream_clients: int = 0
        self._app = FastAPI(title="Pokemon-Opus Viewer API")
        self._event_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._game_client: Optional[GameClient] = None

        # Frame cache to avoid redundant emulator polls when multiple viewers connect
        self._frame_cache: bytes = b""
        self._frame_cache_time: float = 0.0

        if enable_cors:
            self._app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        self._register_routes()

    def set_game_client(self, client: GameClient) -> None:
        """Set the game client for frame streaming."""
        self._game_client = client

    @property
    def app(self) -> FastAPI:
        return self._app

    def _register_routes(self) -> None:
        @self._app.websocket("/ws")
        async def websocket_handler(ws: WebSocket):
            await ws.accept()
            self._clients.add(ws)
            logger.info(f"Viewer connected ({len(self._clients)} total)")
            try:
                # Send current state on connect
                await ws.send_json({"type": "connected", "viewers": len(self._clients)})
                # Keep alive — client doesn't send data, just receives
                while True:
                    try:
                        await asyncio.wait_for(ws.receive_text(), timeout=60.0)
                    except asyncio.TimeoutError:
                        # Send heartbeat to detect dead connections
                        await ws.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.debug(f"WebSocket error: {e}")
            finally:
                self._clients.discard(ws)
                logger.info(f"Viewer disconnected ({len(self._clients)} remaining)")

        @self._app.get("/api/health")
        async def health():
            return {"status": "ok", "viewers": len(self._clients)}

        @self._app.get("/api/state")
        async def get_state():
            """Return the latest cached state (set by orchestrator)."""
            return self._latest_state or {"error": "No state available yet"}

        @self._app.get("/stream")
        async def mjpeg_stream():
            """MJPEG stream of emulator frames at ~30fps."""
            return StreamingResponse(
                self._generate_frames(),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

    # ── Frame Streaming ──────────────────────────────────────────────

    async def _get_frame(self) -> bytes:
        """Get a frame, using cache if fresh enough to avoid hammering the emulator."""
        now = time.monotonic()
        if now - self._frame_cache_time < STREAM_FRAME_INTERVAL * 0.5 and self._frame_cache:
            return self._frame_cache

        if not self._game_client:
            return self._frame_cache or b""

        try:
            frame = await self._game_client.screenshot()
            self._frame_cache = frame
            self._frame_cache_time = now
            return frame
        except Exception:
            return self._frame_cache or b""

    async def _generate_frames(self):
        """Async generator yielding MJPEG frames."""
        self._stream_clients += 1
        logger.info(f"MJPEG stream client connected ({self._stream_clients} active)")
        try:
            while True:
                frame_start = time.monotonic()
                png_bytes = await self._get_frame()
                if png_bytes:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/png\r\n"
                        b"Content-Length: " + str(len(png_bytes)).encode() + b"\r\n"
                        b"\r\n" + png_bytes + b"\r\n"
                    )
                # Sleep to maintain target FPS, accounting for fetch time
                elapsed = time.monotonic() - frame_start
                sleep_time = max(0.001, STREAM_FRAME_INTERVAL - elapsed)
                await asyncio.sleep(sleep_time)
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            self._stream_clients -= 1
            logger.info(f"MJPEG stream client disconnected ({self._stream_clients} active)")

    # ── State Cache ────────────────────────────────────────────────────

    _latest_state: Dict[str, Any] | None = None

    def cache_state(self, state: Dict[str, Any]) -> None:
        """Cache latest state for new viewer connections and REST polling."""
        self._latest_state = state

    # ── Broadcasting ───────────────────────────────────────────────────

    async def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast an event to all connected viewers."""
        message = json.dumps({"type": event_type, **data})
        dead: list[WebSocket] = []
        for client in self._clients:
            try:
                await client.send_text(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)

    def broadcast_sync(self, event_type: str, data: Dict[str, Any]) -> None:
        """Fire-and-forget broadcast from synchronous code."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event_type, data))
        except RuntimeError:
            # No event loop running — drop the event
            pass

    # ── Convenience Broadcasts ─────────────────────────────────────────

    async def broadcast_turn_start(self, turn: int, mode: str, map_name: str) -> None:
        await self.broadcast("turn_start", {
            "turn": turn, "mode": mode, "map_name": map_name,
        })

    async def broadcast_turn_complete(
        self,
        turn: int,
        mode: str,
        actions: list[str],
        state: Dict[str, Any],
        screenshot: str,
        reasoning: str,
        deltas: Dict[str, Any],
    ) -> None:
        self.cache_state(state)
        await self.broadcast("turn_complete", {
            "turn": turn,
            "mode": mode,
            "actions": actions,
            "state": state,
            "screenshot": screenshot,
            "reasoning": reasoning,
            "deltas": deltas,
        })

    async def broadcast_reasoning_chunk(self, turn: int, text: str) -> None:
        await self.broadcast("reasoning_chunk", {"turn": turn, "text": text})

    async def broadcast_mode_change(self, from_mode: str, to_mode: str) -> None:
        await self.broadcast("mode_change", {"from": from_mode, "to": to_mode})

    async def broadcast_battle_start(self, enemy: Dict[str, Any], battle_type: str) -> None:
        await self.broadcast("battle_start", {"enemy": enemy, "battle_type": battle_type})

    async def broadcast_battle_end(self, result: str) -> None:
        await self.broadcast("battle_end", {"result": result})

    async def broadcast_milestone(self, name: str, turn: int, details: str = "") -> None:
        await self.broadcast("milestone", {"name": name, "turn": turn, "details": details})

    async def broadcast_objective_update(self, objectives: list[Dict[str, Any]]) -> None:
        await self.broadcast("objective_update", {"objectives": objectives})

    async def broadcast_memory_created(
        self, location: str, category: str, text: str
    ) -> None:
        await self.broadcast("memory_created", {
            "location": location, "category": category, "text": text,
        })

    async def broadcast_map_update(
        self, map_id: int, position: tuple[int, int], connections: list[Dict[str, Any]]
    ) -> None:
        await self.broadcast("map_update", {
            "map_id": map_id, "position": list(position), "connections": connections,
        })

    async def broadcast_episode_start(self, episode_id: str) -> None:
        await self.broadcast("episode_start", {"episode_id": episode_id})

    async def broadcast_episode_end(
        self, badges: int, pokedex: int, turns: int
    ) -> None:
        await self.broadcast("episode_end", {
            "badges": badges, "pokedex": pokedex, "turns": turns,
        })

    async def broadcast_error(self, message: str) -> None:
        await self.broadcast("error", {"message": message})

    # ── Server Lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Start the uvicorn server (call from async context)."""
        import uvicorn

        config = uvicorn.Config(
            app=self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        await server.serve()
