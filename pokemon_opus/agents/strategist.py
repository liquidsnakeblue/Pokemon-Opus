"""
Strategist — long-term planning agent for objectives, team composition, and gym preparation.
Called periodically by the orchestrator. Uses Opus-level reasoning.
Adapted from Zork-Opus reasoner/objectives system.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..data.map_data import GYM_ORDER, HM_DATA, PROGRESSION_MILESTONES

logger = logging.getLogger(__name__)

STRATEGIST_SYSTEM_PROMPT = """You are a strategic advisor for an AI playing Pokemon Blue (Gen 1).

Your job: analyze the current game state and generate/update objectives for the agent.
You see the big picture — team composition, gym readiness, progression order, HM planning.

## 🧭 TRUST HIERARCHY

1. **Game RAM data** — Bag, Party, Badges, Game flags (has_pokedex,
   has_oaks_parcel, pokedex_owned/seen), Location. This is the
   SOURCE OF TRUTH. If the bag shows Oak's Parcel, the player has it.
   If the badges list is `['Boulder']`, the player has beaten Brock.
2. **Current objective list** — what's actively being worked on.
3. **Recent action history** — context for what the agent has been
   doing. May be stale or misleading.
4. **Your own previous strategic reasoning** — lowest trust. If your
   last review set an objective that the current RAM state proves
   is already complete, abandon it.

## 🔎 INVENTORY VERIFICATION (MANDATORY)

Before creating ANY "Get X" or "Deliver X" objective involving a
key item, you MUST first check the RAM bag listing. If the item
is already in the bag, the quest is already complete or in progress
for DELIVERY — do NOT create a "Get it" objective. This is the
single most common source of wasted-turn loops: the agent spends
dozens of turns trying to obtain an item it already owns.

If the bag contradicts an existing objective (e.g. objective says
"Get Oak's Parcel" but the bag has Oak's Parcel), IMMEDIATELY add
that objective ID to `abandon_objective_ids` and replace it with
the next logical step (e.g. "Deliver Oak's Parcel to Oak in Pallet
Town"). Never leave a contradicted objective active.

## Response Format
```json
{
    "reasoning": "Strategic analysis (3-5 sentences)",
    "suggested_approach": "High-level strategy for next 50-100 turns",
    "new_objectives": [
        {
            "category": "progression|battle|exploration|collection",
            "name": "Short name",
            "text": "Detailed description of what to do",
            "completion_condition": "How to know it's done",
            "target_map_id": null
        }
    ],
    "abandon_objective_ids": ["OBJ-001"],
    "priority_order": ["OBJ-003", "OBJ-002"]
}
```

## Key Knowledge
- Gen 1 gym order: Brock (Rock) → Misty (Water) → Lt. Surge (Electric) → Erika (Grass) → Koga (Poison) → Sabrina (Psychic) → Blaine (Fire) → Giovanni (Ground)
- HM01 Cut: SS Anne after Cascade Badge. Required for Vermilion gym.
- HM03 Surf: Safari Zone after Soul Badge. Required for Cinnabar.
- Psychic types are overpowered in Gen 1 (no real counters).
- Squirtle is the recommended starter (beats Brock and Blaine easily).
- Grinding is sometimes necessary — recommend it when team is underleveled.

## 🎯 DUAL PRIMARY GOALS

This run has TWO parallel primary goals, BOTH required for completion:

1. **Beat the Elite Four** (become Champion). This is the main
   progression spine: 8 badges → Victory Road → Elite Four.

2. **Complete the Pokédex** (catch one of every obtainable species).
   The agent should be CATCHING wild Pokemon it hasn't owned yet,
   not just KOing them. The battle agent knows to preserve HP and
   throw Poké Balls when it sees a new species — but YOU decide
   where to go. That means:
   - Ensuring the agent always has Poké Balls in the bag (add
     "Buy Poké Balls" objectives when stock is low).
   - Routing through grass patches on routes where known new
     species can spawn, even if a more direct path exists, when
     Pokédex progress lags behind story progress.
   - Creating "Catch X" objectives for specific species when the
     agent is near a known habitat for a missing one.
   - Reminding the agent of version-exclusive obstacles: some
     species are Blue-exclusive, some require fishing, some need
     Safari Zone, some need trade evolution (Machoke, Haunter,
     Kadabra, Graveler), and Mew is not legitimately obtainable.

The RAM section below lists exactly which species the player has
seen and owned. Use this to decide when Pokédex work should
become a priority objective. A good heuristic: if `owned` is
more than ~15 species behind what's obtainable in the current
region, the next objective should involve catching, not just
story progression.

## Constraints
- Max 8 active objectives at a time
- Objectives should be specific and actionable, not vague
- Always have at least one progression objective (next gym, next story beat)
- Include healing objectives when party HP is low
- Include at least one Pokédex-related objective when the player
  has the Pokédex and owned count lags behind story progress
"""


class Strategist:
    """Long-term strategic planner. Generates and manages objectives."""

    def __init__(self, config, llm_client):
        self.config = config
        self.llm = llm_client

    async def review_objectives(self, gs) -> None:
        """Review and update objectives based on current game state."""
        context = self._build_context(gs)
        messages = [{"role": "user", "content": context}]

        try:
            result = await self.llm.chat_json(
                role="strategist",
                messages=messages,
                system=STRATEGIST_SYSTEM_PROMPT,
            )
            parsed = result["parsed"]

            # Track tokens
            usage = result.get("usage", {})
            gs.total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            # Abandon objectives
            abandon_ids = set(parsed.get("abandon_objective_ids", []))
            for obj in gs.objectives:
                if obj.id in abandon_ids and obj.status in ("pending", "in_progress"):
                    obj.status = "abandoned"
                    logger.info(f"Objective abandoned: {obj.id} — {obj.name}")

            # Add new objectives
            for new_obj in parsed.get("new_objectives", []):
                obj_id = gs.next_objective_id()
                from ..state import Objective
                obj = Objective(
                    id=obj_id,
                    category=new_obj.get("category", "exploration"),
                    name=new_obj.get("name", ""),
                    text=new_obj.get("text", ""),
                    completion_condition=new_obj.get("completion_condition", ""),
                    status="pending",
                    created_turn=gs.turn_count,
                    target_map_id=new_obj.get("target_map_id"),
                )
                gs.objectives.append(obj)
                logger.info(f"New objective: {obj.id} — {obj.name}")

            # Trim to max objectives
            active = [o for o in gs.objectives if o.status in ("pending", "in_progress")]
            if len(active) > self.config.max_objectives:
                # Keep the most recent ones
                to_abandon = active[: len(active) - self.config.max_objectives]
                for obj in to_abandon:
                    obj.status = "abandoned"
                    logger.info(f"Objective auto-trimmed: {obj.id}")

            logger.info(
                f"Strategic review complete: "
                f"{len(gs.active_objectives)} active objectives, "
                f"approach: {parsed.get('suggested_approach', 'none')[:80]}"
            )

        except Exception as e:
            logger.error(f"Strategist error: {e}")

    async def generate_initial_objectives(self, gs) -> None:
        """Generate starting objectives for a new episode."""
        # Seed basic objectives based on game progress
        from ..state import Objective

        if gs.badge_count == 0:
            gs.objectives.append(Objective(
                id=gs.next_objective_id(),
                category="progression",
                name="Choose starter Pokemon",
                text="Go downstairs, leave the house, walk to the tall grass. Professor Oak will stop you and bring you to his lab. Choose a starter Pokemon (Squirtle recommended).",
                completion_condition="Party has 1 Pokemon",
                status="in_progress",
                created_turn=0,
                target_map_id=0,  # Pallet Town
            ))
            gs.objectives.append(Objective(
                id=gs.next_objective_id(),
                category="progression",
                name="Deliver Oak's Parcel",
                text="After getting a Pokemon, go north through Route 1 to Viridian City. Visit the Poke Mart — the clerk will give you Oak's Parcel. Return it to Professor Oak in Pallet Town.",
                completion_condition="Oak's Parcel delivered, Pokedex received",
                status="pending",
                created_turn=0,
            ))
            gs.objectives.append(Objective(
                id=gs.next_objective_id(),
                category="battle",
                name="Defeat Brock",
                text="Train to at least Lv12, then challenge Brock in Pewter City Gym. His Onix is Lv14 Rock/Ground — use Water or Grass moves.",
                completion_condition="Boulder Badge earned",
                status="pending",
                created_turn=0,
                target_map_id=2,  # Pewter City
            ))

    def _build_context(self, gs) -> str:
        """Build strategic context for the LLM."""
        parts = []

        parts.append(f"=== STRATEGIC REVIEW — Turn {gs.turn_count} ===")
        parts.append(f"Runtime: {gs.runtime_display}")
        parts.append(f"Badges: {gs.badge_count}/8 — {', '.join(gs.badges) if gs.badges else 'none'}")
        parts.append(f"Location: {gs.map_name}")
        parts.append(f"Money: ¥{gs.money}")
        parts.append(f"Pokedex: {gs.pokedex_owned} owned, {gs.pokedex_seen} seen")

        # Team overview
        parts.append("\n== TEAM ==")
        for i, p in enumerate(gs.party):
            hp_pct = round(p.hp / p.max_hp * 100) if p.max_hp > 0 else 0
            moves = ", ".join(m.name for m in p.moves if m.name)
            parts.append(
                f"  {i+1}. {p.species} Lv{p.level} [{'/'.join(p.types)}] "
                f"HP:{hp_pct}% Moves: {moves}"
            )

        # Bag (RAM truth) — the most important signal for objective
        # planning. If a "Get X" or "Deliver X" objective contradicts
        # the bag (e.g. objective says "get parcel" but parcel is
        # already in the bag) you MUST mark it complete or abandon it.
        # Don't create new objectives that ignore the bag.
        bag = getattr(gs, "bag", None) or []
        parts.append("\n== BAG (RAM truth — what is ACTUALLY owned) ==")
        if bag:
            for item in bag:
                if isinstance(item, dict):
                    name = item.get("item", "?")
                    qty = item.get("quantity", 1)
                    parts.append(f"  • {name} ×{qty}")
                else:
                    parts.append(f"  • {item}")
        else:
            parts.append("  (empty)")

        # Key game flags from RAM
        flags_bits: List[str] = []
        if getattr(gs, "has_pokedex", False):
            flags_bits.append("has_pokedex=True")
        if getattr(gs, "has_oaks_parcel", False):
            flags_bits.append("has_oaks_parcel=True")
        if flags_bits:
            parts.append("Game flags: " + ", ".join(flags_bits))

        # Pokédex progress (RAM truth) — critical for objective
        # planning. The agent's job is to catch one of each species,
        # so knowing exactly what's owned vs seen vs unseen drives
        # catching objectives.
        owned_list = getattr(gs, "pokedex_owned_species", None) or []
        seen_list = getattr(gs, "pokedex_seen_species", None) or []
        parts.append(
            f"\n== POKÉDEX PROGRESS — {len(owned_list)}/151 owned, "
            f"{len(seen_list)}/151 seen =="
        )
        if owned_list:
            parts.append("  Owned: " + ", ".join(owned_list))
        else:
            parts.append("  Owned: (none)")
        # Show species that are seen but not yet owned — these are
        # the closest targets for catching objectives.
        seen_but_unowned = [s for s in seen_list if s not in owned_list]
        if seen_but_unowned:
            parts.append(
                "  Seen but NOT owned (good catch targets — you've "
                "already encountered these): "
                + ", ".join(seen_but_unowned)
            )

        # Next gym target
        next_gym = None
        for gym in GYM_ORDER:
            if gym["badge"] not in gs.badges:
                next_gym = gym
                break
        if next_gym:
            parts.append(f"\n== NEXT GYM ==")
            parts.append(
                f"  {next_gym['leader']} ({next_gym['badge']} Badge) in {next_gym['city']}"
            )
            parts.append(f"  Type: {next_gym['type']} — Weak to: {', '.join(next_gym['weakness'])}")
            parts.append(f"  Recommended level: {next_gym['recommended_level']}")

        # Current objectives
        active = gs.active_objectives
        if active:
            parts.append("\n== CURRENT OBJECTIVES ==")
            for obj in active:
                age = gs.turn_count - obj.created_turn
                parts.append(f"  [{obj.id}] {obj.name} (age: {age} turns)")
                parts.append(f"      {obj.text}")
                parts.append(f"      Complete when: {obj.completion_condition}")

        # Progress stagnation warning
        turns_since_meaningful = gs.turn_count - gs.last_meaningful_turn
        if turns_since_meaningful > 50:
            parts.append(
                f"\n⚠️ STAGNATION: No meaningful progress in {turns_since_meaningful} turns. "
                "Consider changing strategy."
            )

        # Milestones so far
        if gs.milestones:
            parts.append("\n== MILESTONES ==")
            for m in gs.milestones[-10:]:
                parts.append(f"  Turn {m.turn}: {m.name}")

        # Visited locations count
        parts.append(f"\nLocations visited: {len(gs.visited_maps)}")

        return "\n".join(parts)
