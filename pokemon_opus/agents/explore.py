"""
Exploration Agent — decides where to go and what to interact with in the overworld.
Uses screenshot vision + RAM state + position history for spatial awareness.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

EXPLORE_SYSTEM_PROMPT = """You are an AI playing Pokemon Blue. You are currently exploring the overworld.

You can SEE the game screen in the attached image. Use it to understand:
- Where you are (what the room/area looks like)
- Where the exits, doors, and stairs are
- Where NPCs and items are
- What obstacles are blocking your path

Your job: decide what to do next based on what you SEE, your coordinates, your objectives, and your action history.

## Action Format
Respond with a JSON object:
```json
{
    "reasoning": "Describe what you SEE in the screenshot and your plan (2-4 sentences)",
    "actions": ["walk_left", "walk_down", "walk_down", "press_a"],
    "objective_progress": "Which objective this advances (if any)"
}
```

## Available Actions
- walk_up, walk_down, walk_left, walk_right — Move 1 tile in that direction
- press_a — Interact / talk / confirm
- press_b — Cancel / back
- press_start — Open menu
- wait_60 — Wait ~1 second (use after doors/warps for map transition fade)
- hold_b_120 — Hold B for 2 seconds (fast text scroll)
- a_until_dialog_end — Press A repeatedly until dialog clears

## Critical Rules
1. Send 2-6 actions per turn. Don't send too many or you'll overshoot.
2. LOOK AT THE SCREENSHOT to see where things actually are. Don't guess.
3. After walking through a door or down stairs, add TWO wait_60 actions (warp transition).
4. After exiting a building, sidestep left or right to avoid walking back in.
5. If your position hasn't changed for several turns, you're hitting a wall. Try a DIFFERENT direction.
6. Stairs in Pokemon Blue look like dark tiles, usually at the edge of a room.
7. Doors are the bright openings at the bottom of buildings.
8. Ledges only go DOWN — you cannot climb up a ledge.
9. DO NOT repeat the same action sequence if it didn't work last turn.
"""


class ExploreAgent:
    """Exploration agent with screenshot vision and position tracking."""

    def __init__(self, config, llm_client, game_client=None):
        self.config = config
        self.llm = llm_client
        self.game = game_client

    async def decide(
        self, gs, raw_state: Dict[str, Any], game_client=None
    ) -> Tuple[List[str], str]:
        """Decide exploration actions using screenshot + state.

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
            actions = parsed.get("actions", ["wait_60"])
            reasoning = parsed.get("reasoning", "")

            # Track token usage
            usage = result.get("usage", {})
            gs.total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            # Validate actions
            actions = self._validate_actions(actions)
            return actions, reasoning

        except Exception as e:
            logger.error(f"Explore agent error: {e}")
            # Fallback: try a direction we haven't tried recently
            fallback = self._fallback_action(gs)
            return fallback, f"Error: {e}. Trying {fallback[0]}."

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
