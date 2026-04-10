"""
Exploration Agent — decides where to go and what to interact with in the overworld.
Uses screenshot vision + RAM state + position history for spatial awareness.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

EXPLORE_SYSTEM_PROMPT = """You are an AI playing Pokemon Blue. You are exploring the overworld.

You have TWO sources of spatial information:
1. A GAME SCREEN IMAGE (what the player sees right now)
2. A TILE MAP of the current area, built from RAM. This is the source of truth
   for walls, doors, items, and NPCs. Coordinates in the map are absolute
   (y, x) where y grows DOWN (south) and x grows RIGHT (east).

## Tile Legend
  .  walkable floor / path         #  wall / obstacle
  ~  tall grass                    W  water
  T  tree                          L  ledge (one-way, downhill only)
  D  door or warp                  f  fence
  B  building                      F  flower
  S  sign                          I  item (pick-up)
  O  object (machine, bookshelf)   N  NPC
  P  YOU (the player)

## Preferred Navigation: `target`
Instead of hand-choosing walk actions, say WHERE you want to go and the
pathfinder will walk you there along the shortest walkable route.

```json
{
    "reasoning": "I want to reach the Poke Ball two tiles east of me.",
    "target": [5, 7],
    "objective_progress": "Exploring Oak's Lab"
}
```

`target` is an absolute (y, x) cell. The pathfinder is a proper A* over
walls. Use this for any movement more than one step away.

## Raw Actions Fallback
If you need to press buttons directly (talking to NPCs, menus, waiting
for transitions), use `actions` instead:

```json
{
    "reasoning": "I'll talk to the NPC in front of me.",
    "actions": ["press_a"]
}
```

Available actions: walk_up, walk_down, walk_left, walk_right, press_a,
press_b, press_start, wait_60, hold_b_120, a_until_dialog_end.

After going through a door/stairs, follow with TWO wait_60 actions.

## Rules
1. Prefer `target` for movement. The pathfinder knows the walls.
2. Only use `actions` when you need non-movement inputs or a very short hop.
3. If your position hasn't changed for several turns you are hitting a wall —
   check the TILE MAP to see which cells are actually walkable.
4. Ledges are one-way (down only). You cannot climb back up.
"""


class ExploreAgent:
    """Exploration agent with screenshot vision and position tracking."""

    def __init__(self, config, llm_client, game_client=None, grid=None):
        self.config = config
        self.llm = llm_client
        self.game = game_client
        self.grid = grid  # GridAccumulator — optional, enables pathfinding

    async def decide(
        self, gs, raw_state: Dict[str, Any], game_client=None
    ) -> Tuple[List[str], str]:
        """Decide exploration actions using screenshot + tile map + state.

        Returns: (actions, reasoning)
        """
        client = game_client or self.game
        context = self._build_context(gs, raw_state)

        # Build messages — include screenshot as vision if we have a game client
        screenshot_b64 = None
        if client:
            try:
                screenshot_b64 = await client.screenshot_base64()
            except Exception as e:
                logger.warning(f"Screenshot capture failed: {e}")

        messages = self._build_messages(context, screenshot_b64)

        try:
            result = await self.llm.chat_json(
                role="agent",
                messages=messages,
                system=EXPLORE_SYSTEM_PROMPT,
            )
            parsed = result["parsed"]
            reasoning = parsed.get("reasoning", "")

            # Track token usage
            usage = result.get("usage", {})
            gs.total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            # Prefer pathfinder target if the agent supplied one
            target = parsed.get("target")
            if target and self.grid is not None:
                path_actions = self._pathfind_to(gs, target)
                if path_actions:
                    # Cap to prevent overshooting — re-plan next turn
                    capped = path_actions[: max(1, min(8, len(path_actions)))]
                    return capped, reasoning or f"Pathfinding to {tuple(target)}"
                logger.info(f"Pathfind to {target} failed, falling back to actions")

            # Fallback / explicit raw actions
            actions = parsed.get("actions", ["wait_60"])
            actions = self._validate_actions(actions)
            return actions, reasoning

        except Exception as e:
            logger.error(f"Explore agent error: {e}")
            # Fallback: try a direction we haven't tried recently
            fallback = self._fallback_action(gs)
            return fallback, f"Error: {e}. Trying {fallback[0]}."

    def _pathfind_to(
        self, gs, target: Any
    ) -> List[str]:
        """Run A* from the player's current position to `target` and convert
        the resulting path into walk_* actions."""
        if self.grid is None:
            return []
        # Normalize target to (y, x)
        try:
            if isinstance(target, dict):
                ty, tx = int(target.get("y", 0)), int(target.get("x", 0))
            else:
                ty, tx = int(target[0]), int(target[1])
        except Exception:
            logger.warning(f"Invalid target format: {target!r}")
            return []

        start = (int(gs.position[0]), int(gs.position[1]))
        path = self.grid.find_path(
            map_id=gs.map_id,
            start=start,
            goal=(ty, tx),
        )
        if not path or len(path) < 2:
            return []
        # path_to_actions lives on the accumulator
        from ..map.grid import GridAccumulator
        step_actions = GridAccumulator.path_to_actions(path)
        # Convert generic "up/down/left/right" → emulator "walk_*" actions
        return [f"walk_{a}" for a in step_actions]

    def _build_messages(
        self, context: str, screenshot_b64: str | None
    ) -> List[Dict[str, Any]]:
        """Build message list, with vision content if screenshot available."""
        if screenshot_b64:
            # Multimodal message: image + text
            return [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": context,
                    },
                ],
            }]
        else:
            # Text-only fallback
            return [{"role": "user", "content": context}]

    def _build_context(self, gs, raw_state: Dict[str, Any]) -> str:
        """Build the context string with position tracking and stuck detection."""
        parts = []

        # Header
        parts.append(f"Turn: {gs.turn_count}")
        parts.append(f"Location: {gs.map_name} (map_id={gs.map_id})")
        parts.append(f"Position: (y={gs.position[0]}, x={gs.position[1]}) facing {gs.facing}")

        # Tile map — absolute coordinates, built from RAM
        tile_view = self._render_tile_map(gs)
        if tile_view:
            parts.append("")
            parts.append("Tile map (absolute coordinates — use these for `target`):")
            parts.append(tile_view)

        # Badges and progress
        parts.append(f"Badges: {gs.badge_count}/8 — {', '.join(gs.badges) if gs.badges else 'none'}")

        # Party (compact)
        if gs.party:
            parts.append("\nTeam:")
            for i, p in enumerate(gs.party):
                hp_str = f"{p.hp}/{p.max_hp}" if p.max_hp > 0 else "?"
                parts.append(f"  {i+1}. {p.species} Lv{p.level} HP:{hp_str}")

        # Objectives
        active = gs.active_objectives
        if active:
            parts.append("\nObjectives:")
            for obj in active:
                marker = "●" if obj.status == "in_progress" else "○"
                parts.append(f"  {marker} [{obj.id}] {obj.name}: {obj.text}")

        # Recent action history with positions — critical for stuck detection
        if gs.action_history:
            parts.append("\nRecent actions and results:")
            for entry in gs.action_history[-5:]:
                pos_str = f"({entry.position[0]},{entry.position[1]})"
                parts.append(
                    f"  T{entry.turn} @ {entry.map_name} {pos_str}: "
                    f"{entry.actions} → {entry.reasoning[:60]}"
                )

            # Explicit stuck warning if position hasn't changed
            recent_positions = [e.position for e in gs.action_history[-3:]]
            if len(recent_positions) >= 3 and len(set(recent_positions)) == 1:
                parts.append(
                    f"\n⚠️ STUCK: Your position has been {recent_positions[0]} for "
                    f"{len(recent_positions)} turns. You are hitting a wall or obstacle. "
                    f"Look at the screenshot carefully and try a COMPLETELY DIFFERENT direction. "
                    f"The stairs/exit may be in a direction you haven't tried."
                )

            # Repeated action warning
            recent_actions = [tuple(e.actions) for e in gs.action_history[-3:]]
            if len(recent_actions) >= 3 and len(set(recent_actions)) == 1:
                parts.append(
                    f"\n⚠️ REPEATING: You've sent the same actions {recent_actions[0]} "
                    f"three times in a row. This is NOT working. Try something different."
                )

        return "\n".join(parts)

    def _render_tile_map(self, gs, radius: int = 6) -> str:
        """Render a window of the accumulated tile grid around the player,
        labeled with absolute coordinates. Empty string if no grid yet."""
        if self.grid is None:
            return ""
        mg = self.grid.get_map(gs.map_id)
        if mg is None or not mg.cells:
            return ""

        py, px = int(gs.position[0]), int(gs.position[1])
        min_y, min_x = py - radius, px - radius
        max_y, max_x = py + radius, px + radius

        # Column header
        lines = []
        col_header = "     " + " ".join(f"{x % 10}" for x in range(min_x, max_x + 1))
        lines.append(col_header)

        for y in range(min_y, max_y + 1):
            row_chars = []
            for x in range(min_x, max_x + 1):
                if y == py and x == px:
                    row_chars.append("P")
                else:
                    ch = mg.cells.get((y, x))
                    row_chars.append(ch if ch else "·")  # unknown = middle dot
            lines.append(f"{y:>4} " + " ".join(row_chars))

        return "\n".join(lines)

    def _fallback_action(self, gs) -> List[str]:
        """Generate a fallback action that avoids repeating recent failures."""
        all_dirs = ["walk_up", "walk_down", "walk_left", "walk_right"]

        # Find directions NOT tried recently
        tried = set()
        for entry in gs.action_history[-3:]:
            for a in entry.actions:
                if a.startswith("walk_"):
                    tried.add(a)

        untried = [d for d in all_dirs if d not in tried]
        if untried:
            return [untried[0], untried[0]]

        # All directions tried — try diagonal movement
        return ["walk_left", "walk_down"]

    def _validate_actions(self, actions: List[Any]) -> List[str]:
        """Validate and sanitize action list."""
        valid_prefixes = ("walk_", "press_", "hold_", "wait_", "a_until")
        validated = []
        for a in actions:
            if not isinstance(a, str):
                continue
            a = a.strip().lower()
            if any(a.startswith(p) for p in valid_prefixes):
                validated.append(a)
        return validated or ["wait_60"]
