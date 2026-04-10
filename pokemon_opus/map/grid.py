"""
Grid Accumulator — stitches per-viewport tile observations into a persistent
per-map grid, and provides A* pathfinding over it.

The emulator exposes a 10x9 game-grid viewport centered on the player at
(4, 4). Each cell carries a classification character:

    "." walkable     "#" wall         "~" tall grass      "W" water
    "D" door/warp    "P" player       "N" NPC             "I" item
    "O" object       "F" flower       "f" fence           "B" building
    "T" tree         "L" ledge        "S" sign            "?" dialog overlay
    "X" out-of-bounds/border

Player absolute map coordinates come from RAM (wYCoord / wXCoord), so the
viewport can be placed directly into an absolute-coordinate grid.
"""

from __future__ import annotations

import heapq
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Viewport layout from red.py/read_tiles
VIEWPORT_H = 9
VIEWPORT_W = 10
PLAYER_ROW = 4
PLAYER_COL = 4

# Characters a pathfinder is allowed to walk onto.
# Dynamic entities (P/N/I/O) are allowed because they resolve at plan time:
# P is the start, N/I/O tiles are *under* walkable terrain and only blocked
# if currently occupied — the caller filters those via `blocked` set.
WALKABLE_CHARS = {".", "P", "N", "I", "O", "D", "~"}

# Characters we never overwrite with something "less known".
# "?" (dialog overlay) and "X" (oob) are low-confidence and should not
# clobber a real observation.
LOW_CONFIDENCE = {"?", "X"}


@dataclass
class MapGrid:
    """Accumulated tile grid for a single map_id, keyed by absolute (y, x)."""
    map_id: int
    name: str = ""
    cells: Dict[Tuple[int, int], str] = field(default_factory=dict)
    last_seen_turn: int = 0

    def bounds(self) -> Optional[Tuple[int, int, int, int]]:
        """Return (min_y, min_x, max_y, max_x) or None if empty."""
        if not self.cells:
            return None
        ys = [p[0] for p in self.cells]
        xs = [p[1] for p in self.cells]
        return min(ys), min(xs), max(ys), max(xs)

    def get(self, y: int, x: int) -> Optional[str]:
        return self.cells.get((y, x))


class GridAccumulator:
    """Stitches viewport observations into per-map grids.

    Usage:
        acc = GridAccumulator()
        acc.observe(map_id, map_name, player_y, player_x, tile_grid, turn)
        tile = acc.get_tile(map_id, y, x)
    """

    def __init__(self) -> None:
        self.maps: Dict[int, MapGrid] = {}

    # ── Observation ────────────────────────────────────────────────────

    def observe(
        self,
        map_id: int,
        map_name: str,
        player_y: int,
        player_x: int,
        tile_grid: List[List[str]],
        turn: int,
    ) -> int:
        """Merge a viewport observation into the map grid.

        Returns the number of cells newly discovered (not previously seen).
        """
        if map_id not in self.maps:
            self.maps[map_id] = MapGrid(map_id=map_id, name=map_name)
        mg = self.maps[map_id]
        if map_name and not mg.name:
            mg.name = map_name
        mg.last_seen_turn = turn

        new_cells = 0
        rows = min(len(tile_grid), VIEWPORT_H)
        for grow in range(rows):
            row = tile_grid[grow]
            cols = min(len(row), VIEWPORT_W)
            for gcol in range(cols):
                ch = row[gcol]
                # Skip low-confidence tiles — don't overwrite real data
                if ch in LOW_CONFIDENCE:
                    continue

                # Absolute map coordinate for this cell
                abs_y = player_y + (grow - PLAYER_ROW)
                abs_x = player_x + (gcol - PLAYER_COL)
                key = (abs_y, abs_x)

                prev = mg.cells.get(key)
                # Normalize dynamic sprites so repeated visits don't leave
                # ghost NPCs in the stored grid. The live viewport drives
                # current occupancy; the stored grid holds terrain only.
                stored = self._terrain_of(ch)
                if stored is None:
                    # Dynamic entity (N/I/O/P) on an unknown tile — treat as
                    # walkable terrain until we can see under it.
                    if prev is None:
                        mg.cells[key] = "."
                        new_cells += 1
                    continue

                if prev is None:
                    mg.cells[key] = stored
                    new_cells += 1
                elif prev != stored and prev not in ("D",):
                    # Upgrade terrain if a later observation disagrees
                    # (except preserve known doors — they're rare signals).
                    mg.cells[key] = stored

        return new_cells

    @staticmethod
    def _terrain_of(ch: str) -> Optional[str]:
        """Map a classified cell char to its terrain char, or None for dynamic."""
        if ch in ("P", "N", "I", "O"):
            return None  # dynamic — can't infer terrain from a single frame
        return ch

    # ── Lookup ────────────────────────────────────────────────────────

    def get_map(self, map_id: int) -> Optional[MapGrid]:
        return self.maps.get(map_id)

    def get_tile(self, map_id: int, y: int, x: int) -> Optional[str]:
        mg = self.maps.get(map_id)
        return mg.get(y, x) if mg else None

    # ── Pathfinding ───────────────────────────────────────────────────

    def find_path(
        self,
        map_id: int,
        start: Tuple[int, int],
        goal: Tuple[int, int],
        blocked: Optional[Iterable[Tuple[int, int]]] = None,
        allow_unknown: bool = False,
    ) -> Optional[List[Tuple[int, int]]]:
        """A* over the accumulated grid for `map_id`.

        Args:
            start: (y, x) current player position
            goal:  (y, x) target cell
            blocked: cells to treat as impassable this turn (e.g. NPC sprites)
            allow_unknown: if True, unseen cells are walkable (useful for
                           frontier-seeking). If False, only known walkable
                           terrain is traversed.

        Returns:
            List of (y, x) cells from start to goal inclusive, or None.
        """
        mg = self.maps.get(map_id)
        if mg is None:
            return None
        if start == goal:
            return [start]

        blocked_set = set(blocked or ())

        def passable(pos: Tuple[int, int]) -> bool:
            if pos in blocked_set:
                return False
            # Always allow the start cell (player may stand on anything)
            if pos == start:
                return True
            # Goal is allowed even if currently occupied — caller picks it
            if pos == goal:
                ch = mg.cells.get(pos)
                if ch is None:
                    return allow_unknown
                return ch in WALKABLE_CHARS
            ch = mg.cells.get(pos)
            if ch is None:
                return allow_unknown
            return ch in WALKABLE_CHARS

        def h(pos: Tuple[int, int]) -> int:
            return abs(pos[0] - goal[0]) + abs(pos[1] - goal[1])

        # A* with manhattan heuristic, 4-connected grid
        open_heap: List[Tuple[int, int, Tuple[int, int]]] = []
        heapq.heappush(open_heap, (h(start), 0, start))
        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
        gscore: Dict[Tuple[int, int], int] = {start: 0}

        # Safety cap to avoid runaway searches on huge maps
        max_expansions = 10_000
        expansions = 0

        while open_heap:
            _, g, current = heapq.heappop(open_heap)
            if current == goal:
                return self._reconstruct(came_from, current)

            expansions += 1
            if expansions > max_expansions:
                logger.warning(
                    f"A* expansion cap reached on map {map_id} "
                    f"from {start} → {goal}"
                )
                return None

            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nxt = (current[0] + dy, current[1] + dx)
                if not passable(nxt):
                    continue
                tentative = g + 1
                if tentative < gscore.get(nxt, 1 << 30):
                    gscore[nxt] = tentative
                    came_from[nxt] = current
                    f = tentative + h(nxt)
                    heapq.heappush(open_heap, (f, tentative, nxt))

        return None

    @staticmethod
    def _reconstruct(
        came_from: Dict[Tuple[int, int], Tuple[int, int]],
        end: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        path = [end]
        while end in came_from:
            end = came_from[end]
            path.append(end)
        path.reverse()
        return path

    @staticmethod
    def path_to_actions(path: List[Tuple[int, int]]) -> List[str]:
        """Convert a path of cells into directional button presses."""
        actions: List[str] = []
        for i in range(1, len(path)):
            py, px = path[i - 1]
            ny, nx = path[i]
            dy, dx = ny - py, nx - px
            if dy == -1 and dx == 0:
                actions.append("up")
            elif dy == 1 and dx == 0:
                actions.append("down")
            elif dy == 0 and dx == -1:
                actions.append("left")
            elif dy == 0 and dx == 1:
                actions.append("right")
            else:
                # Non-adjacent step — bail out rather than emit garbage
                logger.warning(f"Non-adjacent path step {path[i-1]} → {path[i]}")
                break
        return actions

    # ── Persistence ────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        data = {
            str(mid): {
                "map_id": mg.map_id,
                "name": mg.name,
                "last_seen_turn": mg.last_seen_turn,
                "cells": [[y, x, ch] for (y, x), ch in mg.cells.items()],
            }
            for mid, mg in self.maps.items()
        }
        Path(path).write_text(json.dumps(data))
        logger.info(f"Grid accumulator saved: {len(self.maps)} maps → {path}")

    def load(self, path: str | Path) -> bool:
        p = Path(path)
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text())
            for mid_str, mdata in data.items():
                mid = int(mid_str)
                mg = MapGrid(
                    map_id=mdata["map_id"],
                    name=mdata.get("name", ""),
                    last_seen_turn=mdata.get("last_seen_turn", 0),
                )
                for y, x, ch in mdata.get("cells", []):
                    mg.cells[(y, x)] = ch
                self.maps[mid] = mg
            logger.info(f"Grid accumulator loaded: {len(self.maps)} maps from {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load grid accumulator from {path}: {e}")
            return False

    # ── Rendering (debug) ─────────────────────────────────────────────

    def render_map(self, map_id: int, player: Optional[Tuple[int, int]] = None) -> str:
        mg = self.maps.get(map_id)
        if mg is None or not mg.cells:
            return f"(no data for map {map_id})"
        miny, minx, maxy, maxx = mg.bounds()  # type: ignore
        lines = [f"=== {mg.name or f'map {map_id}'} "
                 f"({maxy - miny + 1}x{maxx - minx + 1}) ==="]
        for y in range(miny, maxy + 1):
            row_chars = []
            for x in range(minx, maxx + 1):
                if player and (y, x) == player:
                    row_chars.append("P")
                else:
                    row_chars.append(mg.cells.get((y, x), " "))
            lines.append("".join(row_chars))
        return "\n".join(lines)
