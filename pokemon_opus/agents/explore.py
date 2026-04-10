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
  ~  tall grass — WALKABLE         W  water (need Surf)
  T  tree                          L  ledge (one-way, downhill only)
  D  door or warp                  f  fence
  B  building                      F  flower
  S  sign                          I  item (pick-up)
  O  object (machine, bookshelf)   N  NPC
  P  YOU (the player)

**Tall grass `~` is walkable terrain.** It may trigger random wild
Pokemon encounters when you step on it, but it is the SAME walkability
as plain floor `.` for the pathfinder. You target grass cells with
`target` exactly like floor cells.

## ⚠️ Town exits and route entrances are usually GRASS PATHS

In Pokemon Blue, the way OUT of a town to a connecting route is
almost always a 1-2 tile wide gap in the surrounding wall, and that
gap is filled with TALL GRASS `~`. When you look at the tile map and
see a row of walls `#` at the edge of a town with one or two `~`
tiles in it, **THAT is the exit**. Target those grass cells.

Example: Pallet Town has its north exit at columns 10-11, where a
solid wall row is broken by `~ ~`. To leave Pallet Town to the north
you target `[0, 10]` or `[0, 11]`, NOT a `.` floor tile that looks
like it might be open — those are blocked by the wall row.

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

## Game Boy Controls
- **A** — Confirm / talk to / interact with the thing in front of you.
- **B** — Cancel / back out. Also advances dialog. Does NOTHING on an empty tile.
- **START** — Opens the menu.
- **D-pad** — Moves the player.

## ⚠️ CRITICAL RULE: Don't spam A to exit dialog

Spamming A creates infinite loops. When the last dialog box closes, the
NEXT A press TALKS to whatever is still in front of you (NPC, sign,
SNES, PC, bookshelf) and RE-OPENS the same dialog. Agents have burned
hundreds of turns stuck on the SNES in Red's bedroom doing exactly this.

**Advance overworld dialog with B, not A.** Inside a dialog box, B does
the same thing as A (next line / close). When the box closes and you're
standing in the overworld, B on an empty tile is harmless — no loop.

Only use A when you deliberately want to:
- Talk to an NPC for the first time
- Confirm a YES/NO menu choice
- Pick up an item directly in front of you
- Select a menu option

For everything else in the overworld, B is the safer choice.

## ⚠️ CRITICAL RULE: Doors are DOORMATS — you must STEP THROUGH them

Tiles marked `D` are doors, stairs, ladders, holes, and other warps.

**Mental model:** A `D` tile is a doormat directly in front of the door.
Walking onto the doormat just puts you ON the doormat — it does NOT
transition you. To actually use the door, you must take ONE MORE STEP
in the same direction, *through* the door.

- Door on the SOUTH wall of a room → walk DOWN onto the D, then DOWN again.
- Door on the NORTH wall of a room → walk UP onto the D, then UP again.
- Door on the WEST wall of a room → walk LEFT onto the D, then LEFT again.
- Door on the EAST wall of a room → walk RIGHT onto the D, then RIGHT again.

The direction you step *through* a door has to match the wall the
door is set into. Going down onto a south-wall door and then up off
of it does NOT warp — you have to keep going in the wall direction.

You do NOT press A on doors. A does nothing on a door.

**If the `You are standing on:` line says you're already on a door**,
look at the tile map to see which wall the door is in (the wall row
or column adjacent to your D tile) and walk one more step in that
direction to pass through.

After triggering a warp, send TWO `wait_60` actions to let the fade
transition complete before your next move.

Common failure mode: agent oscillates between the D tile and the
walkable tile next to it, never stepping *through* the door. If you
catch yourself doing this, the fix is: take TWO steps in the wall
direction, not one.

## Rules
1. Prefer `target` for movement. The pathfinder knows the walls.
2. Only use `actions` when you need non-movement inputs or a very short hop.
3. If your position hasn't changed for several turns you are hitting a wall —
   check the TILE MAP to see which cells are actually walkable.
4. Ledges are one-way (down only). You cannot climb back up.
5. **Doors (`D`) are used by WALKING onto them. Never press A on a door.**
6. **If you see a dialog box and you're in the overworld, use `press_b` to
   close it. Never spam `press_a` — you will loop.**
7. If your last 3 turns all sent the same A presses and nothing changed,
   STOP. Try `press_b` or walk in a different direction instead.
"""


class ExploreAgent:
    """Exploration agent with screenshot vision and position tracking."""

    def __init__(self, config, llm_client, game_client=None, grid=None, map_graph=None):
        self.config = config
        self.llm = llm_client
        self.game = game_client
        self.grid = grid  # GridAccumulator — optional, enables pathfinding
        self.map_graph = map_graph  # MapGraph — optional, enables door labels

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

            # Prefer pathfinder target if the agent supplied one — UNLESS
            # the agent is stuck. After 5 consecutive turns at the same
            # position the pathfinder has clearly failed (it can't see
            # whatever is blocking us); ignore any target field and force
            # the agent's raw actions through instead.
            stuck_run = 0
            current_pos = (gs.position[0], gs.position[1])
            for entry in reversed(gs.action_history):
                if entry.position == current_pos:
                    stuck_run += 1
                else:
                    break
            pathfinder_locked = stuck_run >= 5

            target = parsed.get("target")
            if target and self.grid is not None and not pathfinder_locked:
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
        """Run A* from the player's current absolute position to `target`
        and return the resulting walk_* actions.

        The pathfinder operates in ABSOLUTE map coordinates (the same
        space as `gs.position` and the labels in the rendered tile map).
        This function enforces that contract with a bounds check against
        the stored map before calling A*, and logs a clear diagnostic
        when something is off so failures aren't silent.
        """
        if self.grid is None:
            return []

        # Normalize target to (y, x)
        try:
            if isinstance(target, dict):
                ty, tx = int(target.get("y", 0)), int(target.get("x", 0))
            else:
                ty, tx = int(target[0]), int(target[1])
        except Exception:
            logger.warning(f"Pathfind: invalid target format: {target!r}")
            return []

        start = (int(gs.position[0]), int(gs.position[1]))
        goal = (ty, tx)
        map_id = gs.map_id

        mg = self.grid.get_map(map_id)
        if mg is None or not mg.cells:
            logger.info(
                f"Pathfind aborted: accumulator has no data for map_id={map_id}"
            )
            return []

        # Bounds check: the target must be within the stored map's
        # extent. If the LLM hallucinates a coordinate (e.g. 'col 8' on
        # an 8-wide map), fail loudly rather than silently falling back.
        bounds = mg.bounds()
        if bounds is not None:
            b_min_y, b_min_x, b_max_y, b_max_x = bounds
            if not (b_min_y <= ty <= b_max_y and b_min_x <= tx <= b_max_x):
                logger.info(
                    f"Pathfind: target {goal} is OUTSIDE map bounds "
                    f"y∈[{b_min_y},{b_max_y}] x∈[{b_min_x},{b_max_x}] "
                    f"(player at {start}, map_id={map_id})"
                )
                return []

        # Also sanity-check: the target cell must exist in the grid at
        # all. If it doesn't, the pathfinder can't reason about it.
        if mg.cells.get(goal) is None:
            logger.info(
                f"Pathfind: target {goal} has no known terrain in map_id={map_id} "
                f"(player at {start}); falling back"
            )
            return []

        # Build the blocked set from live sprites for THIS turn. The
        # accumulator's stored grid normalizes dynamic entities to floor,
        # so it has no idea Oak is standing in front of you. Without
        # this, A* happily routes through NPCs and the agent oscillates
        # against an invisible wall every turn.
        #
        # Rules:
        #   - All NPCs and static objects (sprites) → blocked.
        #   - Items → blocked too, UNLESS the goal IS the item (e.g.
        #     walking onto a Potion to pick it up). Items sitting on
        #     furniture aren't truly walkable, and items the agent isn't
        #     targeting shouldn't be in the path.
        blocked: set[Tuple[int, int]] = set()
        for sp in getattr(gs, "current_sprites", None) or []:
            try:
                sy, sx = int(sp["y"]), int(sp["x"])
            except Exception:
                continue
            cell = (sy, sx)
            if cell == start:
                continue  # never block where the player currently is
            stype = sp.get("type", "npc")
            if stype == "item" and cell == goal:
                continue  # allow walking onto a targeted item
            blocked.add(cell)

        path = self.grid.find_path(
            map_id=map_id,
            start=start,
            goal=goal,
            blocked=blocked,
        )
        if not path or len(path) < 2:
            logger.info(
                f"Pathfind: no route from {start} to {goal} in map_id={map_id} "
                f"(cell at goal = {mg.cells.get(goal)!r})"
            )
            return []

        from ..map.grid import GridAccumulator
        step_actions = GridAccumulator.path_to_actions(path)
        walk_actions = [f"walk_{a}" for a in step_actions]
        logger.info(
            f"Pathfind: {start} → {goal} ({len(walk_actions)} steps) "
            f"in map_id={map_id}"
        )
        return walk_actions

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
            parts.append(
                "\nYour previous turns (YOUR OWN past notes — these may be"
                " stale or wrong, especially descriptions of the screen."
                " The SCREENSHOT above is the only source of truth for"
                " what is on screen RIGHT NOW, and the TILE MAP above is"
                " the source of truth for walls/doors/positions. Use this"
                " history only to stay coherent across turns and detect"
                " when you are stuck — do NOT trust your past 'I see X'"
                " claims if the current screenshot or tile map disagrees):"
            )
            for entry in gs.action_history[-5:]:
                pos_str = f"({entry.position[0]},{entry.position[1]})"
                parts.append(
                    f"  T{entry.turn} @ {entry.map_name} {pos_str}: "
                    f"{entry.actions} → {entry.reasoning[:60]}"
                )

            # Explicit stuck warning if position hasn't changed.
            # Count the longest run of identical positions ending at the
            # current turn — this is the true "consecutively stuck" count.
            stuck_run = 0
            current_pos = (gs.position[0], gs.position[1])
            for entry in reversed(gs.action_history):
                if entry.position == current_pos:
                    stuck_run += 1
                else:
                    break

            if stuck_run >= 3:
                parts.append(
                    f"\n⚠️ STUCK: Your position has been {current_pos} for "
                    f"{stuck_run} turns straight. You are hitting a wall, an "
                    f"NPC, or some obstacle the pathfinder can't see. Look at "
                    f"the SCREENSHOT and the SPRITES list above to identify "
                    f"what's blocking you, then try a COMPLETELY DIFFERENT "
                    f"direction or route."
                )

            # Hard lockout: after 5+ stuck turns the pathfinder has clearly
            # failed for this situation. Force the agent to abandon `target`
            # and navigate manually with raw `actions` so it has to think
            # one tile at a time.
            if stuck_run >= 5:
                parts.append(
                    f"\n🚫 PATHFINDER LOCKOUT: You have been stuck at "
                    f"{current_pos} for {stuck_run} turns. The pathfinder is "
                    f"NOT working for this situation — it cannot see whatever "
                    f"is blocking you. For this turn you MUST NOT use the "
                    f"`target` field. Use `actions` ONLY, with ONE OR TWO "
                    f"button presses at a time (e.g. [\"walk_down\"], "
                    f"[\"walk_right\", \"walk_right\"]). Look at the screenshot "
                    f"and pick the single best move. After you successfully "
                    f"move off this tile, you may resume using `target` again."
                )

            # Repeated action warning
            recent_actions = [tuple(e.actions) for e in gs.action_history[-3:]]
            if len(recent_actions) >= 3 and len(set(recent_actions)) == 1:
                parts.append(
                    f"\n⚠️ REPEATING: You've sent the same actions {recent_actions[0]} "
                    f"three times in a row. This is NOT working. Try something different."
                )

        return "\n".join(parts)

    def _render_tile_map(self, gs) -> str:
        """Render the ENTIRE accumulated map for the current map_id with
        explicit absolute-coordinate labels on every row and column.

        Output format (example, 8×8 bedroom, player at (2, 5)):

            You are at (y=2, x=5) — marked 'P' below.
            Coordinates in the row/column labels are ABSOLUTE and match
            the `target` field exactly.

                   x:00 01 02 03 04 05 06 07
            y:00    #  #  #  #  #  #  #  #
            y:01    #  #  #  .  .  .  .  D
            y:02    .  .  .  .  .  P  .  .
            y:03    .  .  .  .  .  .  .  .
            y:04    .  .  .  #  .  .  .  .
            ...

        Every cell's coordinates are readable directly off the labels —
        no relative counting required.
        """
        if self.grid is None:
            return ""
        mg = self.grid.get_map(gs.map_id)
        if mg is None or not mg.cells:
            return ""

        py, px = int(gs.position[0]), int(gs.position[1])

        # Use the stored map's bounds — this gives us the actual current
        # map extent (not a camera window around the player).
        bounds = mg.bounds()
        if bounds is None:
            return ""
        min_y, min_x, max_y, max_x = bounds

        # Always include the player's position in the visible range even
        # if it's somehow outside the stored cells (shouldn't happen but
        # defensive).
        min_y = min(min_y, py)
        min_x = min(min_x, px)
        max_y = max(max_y, py)
        max_x = max(max_x, px)

        # Preamble — make the coordinate contract impossible to miss.
        # The model has previously been confused by ambiguous single-digit
        # column headers; this format uses explicit `y:NN` / `x:NN` labels
        # for every row and column so a target can be read directly off
        # the grid with no counting or arithmetic.
        height = max_y - min_y + 1
        width = max_x - min_x + 1

        # What tile is the player actually standing on? The grid cell at
        # (py, px) renders as 'P', which hides the underlying terrain.
        # Tell the agent explicitly — especially important for doors,
        # stairs, and warps, which trigger the moment you step onto them
        # so the agent might not realize it's already on one.
        under_tile = mg.cells.get((py, px), "?")
        under_desc = {
            ".": "walkable floor",
            "#": "(standing on a wall — unexpected!)",
            "~": "TALL GRASS (wild Pokemon may appear when you walk)",
            "W": "WATER (you are surfing)",
            "D": "a DOOR/STAIRS/WARP doormat — take ONE MORE STEP in the wall direction (the direction the door faces) to pass THROUGH it. Stepping off in the opposite direction will NOT warp you.",
            "S": "a sign",
            "L": "a LEDGE (one-way south — you can jump off, not back up)",
            "I": "an item tile",
            "O": "an interactive object",
            "N": "an NPC tile",
        }.get(under_tile, f"tile '{under_tile}'")

        lines: List[str] = [
            f"Current map is {height} rows × {width} cols.",
            f"YOU are at (y={py}, x={px}), marked 'P' in the grid below.",
            f"You are standing on: {under_desc}.",
            f"Valid targets MUST be in the ranges y∈[{min_y},{max_y}], x∈[{min_x},{max_x}].",
            "The y/x numbers in the row/column labels are ABSOLUTE map",
            "coordinates — use them directly in the `target` field. DO NOT",
            "count rows or columns from the edge of the grid.",
            "",
        ]

        # Build a sprite overlay from gs.current_sprites so the LLM SEES
        # NPCs/items/objects in their live positions. The accumulator
        # stores only static terrain — without this overlay the rendered
        # map shows Oak's tile as plain floor and the agent has no clue
        # there's a person standing on it.
        sprite_chars: Dict[Tuple[int, int], str] = {}
        for sp in getattr(gs, "current_sprites", None) or []:
            try:
                sy, sx = int(sp["y"]), int(sp["x"])
            except Exception:
                continue
            stype = sp.get("type", "npc")
            sprite_chars[(sy, sx)] = {
                "npc": "N", "item": "I", "object": "O"
            }.get(stype, "N")

        col_nums = " ".join(f"{x:02d}" for x in range(min_x, max_x + 1))
        lines.append(f"       x:{col_nums}")

        for y in range(min_y, max_y + 1):
            row_chars = []
            for x in range(min_x, max_x + 1):
                if y == py and x == px:
                    row_chars.append(" P")
                elif (y, x) in sprite_chars:
                    row_chars.append(f" {sprite_chars[(y, x)]}")
                else:
                    ch = mg.cells.get((y, x))
                    row_chars.append(f" {ch}" if ch else " ·")
            lines.append(f"  y:{y:02d}  {' '.join(row_chars)}")

        if sprite_chars:
            lines.append("")
            lines.append(
                "Sprites visible THIS TURN (NPCs/items/objects). They "
                "block movement — the pathfinder will route around them. "
                "To talk to or pick up a sprite, walk to a tile ADJACENT "
                "to it, face it, and press_a:"
            )
            for (sy, sx), ch in sorted(sprite_chars.items()):
                lines.append(f"  {ch} at (y={sy}, x={sx})")

        # Door labels — for every `D` cell in the rendered area, look up
        # what destination map it leads to (learned from RAM warp tables
        # + map names of previously-visited destinations). This is how
        # the agent tells Oak's Lab apart from Red's House etc.
        if self.map_graph is not None:
            door_lines: List[str] = []
            for y in range(min_y, max_y + 1):
                for x in range(min_x, max_x + 1):
                    if mg.cells.get((y, x)) != "D":
                        continue
                    label = self.map_graph.get_door_label(gs.map_id, y, x)
                    if label:
                        door_lines.append(f"  D at (y={y}, x={x}) → {label}")
            if door_lines:
                lines.append("")
                lines.append(
                    "Doors / warps visible on this map and where they "
                    "lead (from the in-game warp table). Use these "
                    "labels to pick the RIGHT door — Oak's Lab vs Red's "
                    "House etc are otherwise indistinguishable:"
                )
                lines.extend(door_lines)

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
