"""
Pokemon Agent — FastAPI Game Server

Provides HTTP + WebSocket API for controlling a Game Boy / GBA emulator
running a Pokemon ROM, reading game state, and broadcasting events.

All emulator access is routed through an :class:`EmulatorRunner` that
owns the PyBoy instance on a dedicated thread and ticks it at a steady
60 FPS. HTTP handlers never touch the emulator directly — they submit
work to the runner and await it. This keeps the game running in real
time whether or not the agent is currently deciding what to do.
"""

import asyncio
import base64
import io
import json
import re
import time
from functools import partial
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .runner import EmulatorRunner

__version__ = "0.2.0"

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GameConfig(BaseModel):
    """Server configuration — set before startup."""
    rom_path: str
    game_type: str = "auto"       # "red", "firered", or "auto"
    port: int = 8765
    data_dir: str = "~/.pokemon-agent"
    load_state: Optional[str] = None  # Save-state name to auto-load on startup
    target_fps: int = 60              # Emulator wallclock pacing


class ActionRequest(BaseModel):
    """Body for POST /action."""
    actions: list[str]


class SaveRequest(BaseModel):
    """Body for POST /save and POST /load."""
    name: str


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_config: Optional[GameConfig] = None
_emulator = None          # Emulator instance (owned by _runner)
_runner: Optional[EmulatorRunner] = None
_reader = None            # GameMemoryReader subclass instance
_start_time: float = 0.0
_loop: Optional[asyncio.AbstractEventLoop] = None

# WebSocket clients
_ws_clients: Set[WebSocket] = set()

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Pokemon Agent Server",
    version=__version__,
    description="HTTP + WebSocket API for Pokemon emulator control",
)

# CORS — allow everything for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_game_type(rom_path: str) -> str:
    """Pick reader type based on file extension."""
    ext = Path(rom_path).suffix.lower()
    if ext in (".gb", ".gbc"):
        return "red"
    elif ext == ".gba":
        return "firered"
    raise ValueError(f"Unrecognised ROM extension: {ext}")


def _ensure_runner():
    """Raise 503 if the runner isn't ready."""
    if _runner is None or _emulator is None:
        raise HTTPException(status_code=503, detail="Emulator runner not initialised")


async def _run_in_executor(func, *args):
    """Run a blocking call in the default executor (keeps the event loop responsive)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args))


async def _with_emu(fn):
    """Shortcut: run `fn(emu)` on the runner thread from an async handler."""
    return await _run_in_executor(_runner.with_emu, fn)


async def broadcast(event: dict):
    """Send a JSON event to every connected WebSocket client."""
    dead: list[WebSocket] = []
    payload = json.dumps(event)
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


def _get_state_dict_sync() -> dict:
    """Build full game state from the memory reader (runs on runner thread)."""
    from pokemon_agent.state.builder import build_game_state
    return build_game_state(_reader)


# ---------------------------------------------------------------------------
# Action parser
# ---------------------------------------------------------------------------

_ACTION_RE = re.compile(
    r"^(?P<kind>press|walk|hold|wait|a_until_dialog_end)(?:_(?P<rest>.+))?$"
)


async def _execute_action(action_str: str) -> None:
    """Parse and execute a single action string via the runner.

    Supported formats:
        press_X       — press button X for 8 frames, wait 12 frames
        walk_X        — press direction for 8 frames, wait 12 frames
        hold_X_N      — hold button X for N frames
        wait_N        — tick N frames with no input
        a_until_dialog_end — press A every 30 frames until dialog clears (max 300)
    """
    action_str = action_str.strip().lower()

    if action_str == "a_until_dialog_end":
        for _ in range(10):  # max ≈ 10 iterations
            await _run_in_executor(_runner.press_button, "a", 8, 12)
            try:
                state = await _with_emu(lambda e: _get_state_dict_sync())
                if not state.get("dialog_active", False):
                    break
            except Exception:
                pass
        return

    parts = action_str.split("_")

    if parts[0] == "press" and len(parts) >= 2:
        button = "_".join(parts[1:])
        await _run_in_executor(_runner.press_button, button, 8, 12)
        return

    if parts[0] == "walk" and len(parts) >= 2:
        direction = parts[1]
        # Gen 1 timing: 8-frame hold + 12-frame wait = 20 frames total.
        # At real-time 60 FPS this is ~333 ms per step — matching real play.
        await _run_in_executor(_runner.press_button, direction, 8, 12)
        return

    if parts[0] == "hold" and len(parts) >= 3:
        button = "_".join(parts[1:-1])
        frames = int(parts[-1])
        await _run_in_executor(_runner.press_button, button, frames, 0)
        return

    if parts[0] == "wait" and len(parts) == 2:
        frames = int(parts[1])
        await _run_in_executor(_runner.tick, frames)
        return

    raise ValueError(f"Unknown action format: {action_str}")


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def configure(config: GameConfig):
    """Set server configuration (call before app startup)."""
    global _config
    _config = config


@app.on_event("startup")
async def _startup():
    global _emulator, _runner, _reader, _start_time, _config, _loop
    _loop = asyncio.get_running_loop()
    _start_time = time.time()

    if _config is None:
        print("[server] WARNING: No GameConfig set — emulator will NOT start.")
        print("[server] Call server.configure(GameConfig(...)) before startup.")
        return

    rom = Path(_config.rom_path).expanduser().resolve()
    if not rom.exists():
        print(f"[server] ERROR: ROM not found: {rom}")
        return

    # Auto-detect game type
    game_type = _config.game_type
    if game_type == "auto":
        game_type = _detect_game_type(str(rom))

    print(f"[server] Loading ROM: {rom}")
    print(f"[server] Detected game type: {game_type}")

    # Create emulator + runner
    from pokemon_agent.emulator import create_emulator
    _emulator = create_emulator(str(rom))
    _runner = EmulatorRunner(_emulator, target_fps=_config.target_fps)
    _runner.start()

    # Create memory reader
    if game_type == "red":
        from pokemon_agent.memory.red import PokemonRedReader
        _reader = PokemonRedReader(_emulator)
    elif game_type == "firered":
        from pokemon_agent.memory.firered import PokemonFireRedReader
        _reader = PokemonFireRedReader(_emulator)
    else:
        raise ValueError(f"Unknown game type: {game_type}")

    # Create data directories
    data_dir = Path(_config.data_dir).expanduser().resolve()
    (data_dir / "saves").mkdir(parents=True, exist_ok=True)

    # Try mounting dashboard
    try:
        import pokemon_agent.dashboard as dashboard_mod  # noqa: F401
        from fastapi.staticfiles import StaticFiles
        dash_dir = Path(dashboard_mod.__file__).parent / "static"
        if dash_dir.is_dir():
            app.mount("/dashboard", StaticFiles(directory=str(dash_dir), html=True), name="dashboard")
            print(f"[server] Dashboard mounted at /dashboard")
        else:
            print("[server] Dashboard module found but no static/ directory")
    except ImportError:
        print("[server] Dashboard not installed — /dashboard unavailable")

    # Auto-load a save state if specified
    if _config.load_state:
        saves_dir = data_dir / "saves"
        state_path = saves_dir / f"{_config.load_state}.state"
        if state_path.exists():
            try:
                _runner.with_emu(lambda e: e.load_state(str(state_path)))
                print(f"[server] Loaded save state: {_config.load_state}")
            except Exception as e:
                print(f"[server] WARNING: Failed to load state '{_config.load_state}': {e}")
        else:
            print(f"[server] WARNING: Save state not found: {state_path}")

    print(f"[server] Runner: {_config.target_fps} FPS real-time background tick loop")
    print(f"[server] Ready — listening on port {_config.port}")


@app.on_event("shutdown")
async def _shutdown():
    global _runner, _emulator
    if _runner is not None:
        _runner.stop()
        _runner = None
    if _emulator is not None:
        try:
            _emulator.close()
        except Exception:
            pass
        _emulator = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    """Server info."""
    frame = _runner.get_frame_number() if _runner else 0
    return {
        "name": "pokemon-agent",
        "version": __version__,
        "game": _config.game_type if _config else None,
        "rom": _config.rom_path if _config else None,
        "uptime_seconds": round(time.time() - _start_time, 1) if _start_time else 0,
        "emulator_ready": _runner is not None,
        "frame": frame,
    }


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "emulator_ready": _runner is not None}


@app.get("/state")
async def get_state():
    """Full game state JSON."""
    _ensure_runner()
    try:
        state = await _with_emu(lambda e: _get_state_dict_sync())
        return JSONResponse(content=state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading state: {e}")


@app.get("/screenshot")
async def screenshot():
    """Current emulator frame as PNG (served from the runner's frame cache)."""
    _ensure_runner()
    png_bytes = _runner.get_frame_bytes()
    if png_bytes is None:
        raise HTTPException(status_code=503, detail="No frame available yet")
    return Response(content=png_bytes, media_type="image/png")


@app.get("/screenshot/base64")
async def screenshot_base64():
    """Current emulator frame as base64 PNG in JSON (from frame cache)."""
    _ensure_runner()
    png_bytes = _runner.get_frame_bytes()
    if png_bytes is None:
        raise HTTPException(status_code=503, detail="No frame available yet")
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return {"image": b64, "format": "png"}


@app.post("/action")
async def execute_actions(req: ActionRequest):
    """Execute a sequence of game actions."""
    _ensure_runner()
    try:
        executed = 0
        for action_str in req.actions:
            await _execute_action(action_str)
            executed += 1

        state_after = await _with_emu(lambda e: _get_state_dict_sync())

        # Grab a screenshot for the live dashboard (from cache, no re-encode)
        png_bytes = _runner.get_frame_bytes()
        screenshot_b64 = base64.b64encode(png_bytes).decode("ascii") if png_bytes else None

        # Broadcast to WebSocket clients
        await broadcast({
            "type": "action",
            "actions": req.actions,
            "actions_executed": executed,
            "state_after": state_after,
        })
        if screenshot_b64:
            await broadcast({
                "type": "screenshot",
                "data": {"image": screenshot_b64, "format": "png"},
            })

        return {
            "success": True,
            "actions_executed": executed,
            "state_after": state_after,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Action error: {e}")


@app.post("/save")
async def save_state(req: SaveRequest):
    """Save emulator state to disk."""
    _ensure_runner()
    if not _config:
        raise HTTPException(status_code=503, detail="Server not configured")
    try:
        saves_dir = Path(_config.data_dir).expanduser().resolve() / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        save_path = saves_dir / f"{req.name}.state"
        await _with_emu(lambda e: e.save_state(str(save_path)))
        return {"success": True, "path": str(save_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save error: {e}")


@app.post("/load")
async def load_state(req: SaveRequest):
    """Load emulator state from disk."""
    _ensure_runner()
    if not _config:
        raise HTTPException(status_code=503, detail="Server not configured")
    try:
        saves_dir = Path(_config.data_dir).expanduser().resolve() / "saves"
        save_path = saves_dir / f"{req.name}.state"
        if not save_path.exists():
            raise HTTPException(status_code=404, detail=f"Save not found: {req.name}")
        await _with_emu(lambda e: e.load_state(str(save_path)))
        state_after = await _with_emu(lambda e: _get_state_dict_sync())

        await broadcast({"type": "state_update", "reason": "load", "state": state_after})

        return {"success": True, "name": req.name, "state_after": state_after}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Load error: {e}")


@app.get("/saves")
async def list_saves():
    """List available save-state files."""
    if not _config:
        raise HTTPException(status_code=503, detail="Server not configured")
    try:
        saves_dir = Path(_config.data_dir).expanduser().resolve() / "saves"
        if not saves_dir.exists():
            return {"saves": []}
        files = sorted(saves_dir.glob("*.state"))
        saves = [
            {
                "name": f.stem,
                "file": f.name,
                "size_bytes": f.stat().st_size,
                "modified": f.stat().st_mtime,
            }
            for f in files
        ]
        return {"saves": saves}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing saves: {e}")


@app.get("/tiles")
async def tiles():
    """Read the on-screen tile buffer with collision classification."""
    _ensure_runner()
    try:
        tile_data = await _with_emu(lambda e: _reader.read_tiles())
        return tile_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tile read error: {e}")


@app.get("/minimap")
async def minimap():
    """Simple ASCII minimap — current map name + player position."""
    _ensure_runner()
    try:
        state = await _with_emu(lambda e: _get_state_dict_sync())
        map_info = state.get("map", {})
        player = state.get("player", {})
        map_name = map_info.get("map_name", "Unknown")
        pos = player.get("position", {})
        x = pos.get("x", "?")
        y = pos.get("y", "?")

        lines = [
            f"=== {map_name} ===",
            f"Player position: ({x}, {y})",
            "",
            "  N",
            "W + E",
            "  S",
        ]
        text = "\n".join(lines)
        return Response(content=text, media_type="text/plain")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Minimap error: {e}")


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Live event stream via WebSocket."""
    await ws.accept()
    _ws_clients.add(ws)
    try:
        await ws.send_json({
            "type": "connected",
            "version": __version__,
            "emulator_ready": _runner is not None,
        })
        while True:
            data = await ws.receive_text()
            if data.strip().lower() == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _ws_clients.discard(ws)


# ---------------------------------------------------------------------------
# Dashboard fallback — only registered if dashboard static files are missing
# ---------------------------------------------------------------------------

def _register_dashboard_fallback():
    """Register a fallback route for /dashboard if static files aren't available."""
    try:
        import pokemon_agent.dashboard as _dm
        static_dir = Path(_dm.__file__).parent / "static"
        if static_dir.is_dir() and (static_dir / "index.html").exists():
            return  # Dashboard exists — don't register fallback
    except ImportError:
        pass

    @app.get("/dashboard")
    @app.get("/dashboard/{path:path}")
    async def dashboard_fallback(path: str = ""):
        raise HTTPException(
            status_code=404,
            detail="Dashboard not installed. Install with: pip install pokemon-agent[dashboard]",
        )

_register_dashboard_fallback()
