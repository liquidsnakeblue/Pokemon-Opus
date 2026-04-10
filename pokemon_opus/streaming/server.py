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

# Tile-grid polling config — decoupled from agent turns so the map
# updates in real time even while the agent is thinking.
TILE_POLL_HZ = 5
TILE_POLL_INTERVAL = 1.0 / TILE_POLL_HZ


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

        # Cached tile snapshot, updated by the background poll loop. Used
        # to deliver tile data to newly-connected viewers immediately.
        self._latest_tiles: Optional[Dict[str, Any]] = None
        self._tile_poll_task: Optional[asyncio.Task] = None

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
                # Send cached state so new viewers immediately see current game state
                if self._latest_state:
                    await ws.send_json({
                        "type": "turn_complete",
                        "turn": self._latest_state.get("turn", 0),
                        "mode": self._latest_state.get("mode", "explore"),
                        "actions": [],
                        "state": self._latest_state,
                        "screenshot": "",
                        "reasoning": self._latest_state.get("last_reasoning", ""),
                        "deltas": {},
                    })
                # Send cached tiles so the map appears immediately, even
                # if the next poll/turn hasn't fired yet.
                if self._latest_tiles:
                    await ws.send_json({
                        "type": "tile_update",
                        "tile_grid": self._latest_tiles.get("grid", []),
                        "full_grid": self._latest_tiles.get("full_grid", []),
                        "player_y": self._latest_tiles.get("player_y", 0),
                        "player_x": self._latest_tiles.get("player_x", 0),
                        "map_height_cells": self._latest_tiles.get("map_height_cells", 0),
                        "map_width_cells": self._latest_tiles.get("map_width_cells", 0),
                        "sprites": self._latest_tiles.get("sprites", []),
                    })
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

    # ── Tile Polling ─────────────────────────────────────────────────
    # The map data updates in real time, independent of agent turns.
    # We poll the emulator's /tiles endpoint at TILE_POLL_HZ and
    # broadcast a `tile_update` event each time. The viewer's MapView
    # subscribes to these so the on-screen map matches the live game
    # even while the LLM is deciding the next move.

    async def _tile_poll_loop(self) -> None:
        """Poll the emulator for tile data and broadcast updates forever."""
        if self._game_client is None:
            logger.warning("StreamServer: no game_client; tile poll loop will idle")
            return
        logger.info(f"StreamServer: starting tile poll loop at {TILE_POLL_HZ} Hz")
        consecutive_errors = 0
        while True:
            loop_start = time.monotonic()
            try:
                tiles = await self._game_client.get_tiles()
                self._latest_tiles = tiles
                # Broadcast a compact tile_update with everything the
                # viewer needs to render the map. Keep the payload lean —
                # this fires 5x/second.
                await self.broadcast("tile_update", {
                    "tile_grid": tiles.get("grid", []),
                    "full_grid": tiles.get("full_grid", []),
                    "player_y": tiles.get("player_y", 0),
                    "player_x": tiles.get("player_x", 0),
                    "map_height_cells": tiles.get("map_height_cells", 0),
                    "map_width_cells": tiles.get("map_width_cells", 0),
                    "sprites": tiles.get("sprites", []),
                })
                consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors <= 3 or consecutive_errors % 50 == 0:
                    logger.debug(f"tile poll error #{consecutive_errors}: {e}")
            elapsed = time.monotonic() - loop_start
            await asyncio.sleep(max(0.0, TILE_POLL_INTERVAL - elapsed))

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

        # Kick off the background tile poller so the map stays in sync
        # with the live game independent of agent turn cadence.
        if self._game_client is not None and self._tile_poll_task is None:
            self._tile_poll_task = asyncio.create_task(
                self._tile_poll_loop(), name="tile-poll-loop"
            )

        config = uvicorn.Config(
            app=self._app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        try:
            await server.serve()
        finally:
            if self._tile_poll_task is not None:
                self._tile_poll_task.cancel()
                try:
                    await self._tile_poll_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._tile_poll_task = None
