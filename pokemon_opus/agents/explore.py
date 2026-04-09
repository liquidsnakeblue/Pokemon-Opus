"""
Exploration Agent — decides where to go and what to interact with in the overworld.
Uses LLM for complex navigation decisions, heuristics for simple movement.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

EXPLORE_SYSTEM_PROMPT = """You are an AI playing Pokemon Blue. You are currently exploring the overworld.

Your job: decide what to do next based on the current game state, your objectives, and your memories of this location.

## Action Format
Respond with a JSON object:
```json
{
    "reasoning": "Brief explanation of your decision (2-3 sentences)",
    "actions": ["walk_up", "walk_up", "press_a"],
    "objective_progress": "Which objective this advances (if any)"
}
```

## Available Actions
- walk_up, walk_down, walk_left, walk_right — Move 1 tile
- press_a — Interact / talk / confirm
- press_b — Cancel / back
- press_start — Open menu
- wait_60 — Wait ~1 second (use after doors/warps)
- hold_b_120 — Hold B for 2 seconds (fast text)
- a_until_dialog_end — Advance all dialog

## Rules
1. Send 2-6 actions per turn. Don't overshoot.
2. After entering a door or stairs, add wait_60 twice (warp transition fade).
3. After exiting a building, sidestep left or right to avoid re-entering.
4. Talk to NPCs by facing them and pressing A.
5. Pick up items by walking to them and pressing A.
6. Avoid ledges going up — they're one-way down only.
7. If you seem stuck, try a different direction or interaction.
"""


class ExploreAgent:
    """Exploration agent for overworld navigation."""

    def __init__(self, config, llm_client):
        self.config = config
        self.llm = llm_client

    async def decide(self, gs, raw_state: Dict[str, Any]) -> Tuple[List[str], str]:
        """Decide exploration actions based on current state.

        Returns: (actions, reasoning)
        """
        # Build context for the LLM
        context = self._build_context(gs, raw_state)

        messages = [{"role": "user", "content": context}]

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
            # Fallback: try a random direction
            return ["wait_60"], f"Error: {e}. Waiting..."

    def _build_context(self, gs, raw_state: Dict[str, Any]) -> str:
        """Build the context string for the exploration LLM call."""
        parts = []

        # Turn and location
        parts.append(f"Turn: {gs.turn_count}")
        parts.append(f"Location: {gs.map_name} (map_id={gs.map_id})")
        parts.append(f"Position: ({gs.position[0]}, {gs.position[1]}) facing {gs.facing}")

        # Badges and progress
        parts.append(f"Badges: {gs.badge_count}/8 — {', '.join(gs.badges) if gs.badges else 'none'}")
        parts.append(f"Money: ¥{gs.money}")

        # Party summary
        if gs.party:
            parts.append("\nParty:")
            for i, p in enumerate(gs.party):
                hp_pct = f"{p.hp}/{p.max_hp}" if p.max_hp > 0 else "?"
                move_names = ", ".join(m.name for m in p.moves if m.name) or "no moves"
                parts.append(f"  {i+1}. {p.species} Lv{p.level} [{'/'.join(p.types)}] HP:{hp_pct} Status:{p.status} Moves: {move_names}")

        # Recent actions (last 5 turns)
        if gs.action_history:
            parts.append("\nRecent actions:")
            for entry in gs.action_history[-5:]:
                parts.append(f"  T{entry.turn} @ {entry.map_name}: {entry.actions} — {entry.reasoning[:80]}")

        # Objectives
        active = gs.active_objectives
        if active:
            parts.append("\nObjectives:")
            for obj in active:
                marker = "●" if obj.status == "in_progress" else "○"
                parts.append(f"  {marker} [{obj.id}] {obj.name}: {obj.text}")

        # Visited maps
        if gs.visited_maps:
            parts.append(f"\nVisited maps: {len(gs.visited_maps)} locations")

        return "\n".join(parts)

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
        # Never return empty
        return validated or ["wait_60"]
