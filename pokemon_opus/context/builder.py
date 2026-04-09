"""
Context Builder — assembles the prompt for each game mode.
Pulls from game state, memories, objectives, map, and type data
to give the agent everything it needs to make good decisions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..state import GameMode, GameState
from ..data.type_chart import best_type_against, describe_matchup
from ..data.map_data import GYM_ORDER, HM_DATA

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds contextualized prompts for each game mode."""

    def __init__(self, memory_manager=None, map_manager=None):
        self.memory = memory_manager
        self.map_mgr = map_manager

    def build(self, gs: GameState, raw_state: Dict[str, Any]) -> str:
        """Build the full context string for the current game mode."""
        match gs.game_mode:
            case GameMode.BATTLE:
                return self._build_battle_context(gs, raw_state)
            case GameMode.EXPLORE:
                return self._build_explore_context(gs, raw_state)
            case GameMode.DIALOG:
                return self._build_dialog_context(gs)
            case GameMode.MENU:
                return self._build_menu_context(gs)
        return self._build_explore_context(gs, raw_state)

    # ── Exploration Context ────────────────────────────────────────────

    def _build_explore_context(self, gs: GameState, raw_state: Dict[str, Any]) -> str:
        parts: List[str] = []

        # Header
        parts.append(f"=== TURN {gs.turn_count} | {gs.map_name} ===")
        parts.append(f"Position: ({gs.position[0]}, {gs.position[1]}) facing {gs.facing}")
        parts.append(f"Badges: {gs.badge_count}/8 — {', '.join(gs.badges) if gs.badges else 'none'}")
        parts.append(f"Money: ¥{gs.money}")

        # Party summary (compact)
        if gs.party:
            parts.append("\n-- TEAM --")
            for i, p in enumerate(gs.party):
                hp_pct = round(p.hp / p.max_hp * 100) if p.max_hp > 0 else 0
                status = f" [{p.status}]" if p.status != "OK" else ""
                moves = ", ".join(m.name for m in p.moves if m.name)
                parts.append(
                    f"  {i+1}. {p.species} Lv{p.level} [{'/'.join(p.types)}] "
                    f"HP:{hp_pct}%{status} — {moves}"
                )

        # Healing check
        if gs.party:
            avg_hp = sum(p.hp / p.max_hp if p.max_hp > 0 else 0 for p in gs.party) / len(gs.party)
            if avg_hp < 0.3:
                parts.append("\n⚠️ TEAM LOW HP — consider healing at Pokemon Center")

        # Objectives
        active = gs.active_objectives
        if active:
            parts.append("\n-- OBJECTIVES --")
            for obj in active:
                marker = "●" if obj.status == "in_progress" else "○"
                parts.append(f"  {marker} [{obj.id}] {obj.name}: {obj.text}")

        # Next gym target
        next_gym = self._get_next_gym(gs)
        if next_gym:
            parts.append(f"\n-- NEXT GYM --")
            parts.append(
                f"  {next_gym['leader']} ({next_gym['badge']} Badge) in {next_gym['city']}"
            )
            parts.append(f"  Type: {next_gym['type']} — Weak to: {', '.join(next_gym['weakness'])}")
            parts.append(f"  Recommended level: {next_gym['recommended_level']}")

        # Location memories
        if self.memory:
            mem_text = self.memory.get_location_memory_text(gs.map_id, gs.map_name)
            if mem_text:
                parts.append(f"\n{mem_text}")

        # Recent actions (last 3)
        if gs.action_history:
            parts.append("\n-- RECENT ACTIONS --")
            for entry in gs.action_history[-3:]:
                parts.append(
                    f"  T{entry.turn} @ {entry.map_name}: {entry.actions[:3]}... — "
                    f"{entry.reasoning[:60]}"
                )

        # Oscillation warning
        if len(gs.action_history) >= 6:
            recent_maps = [e.map_name for e in gs.action_history[-6:]]
            if len(set(recent_maps)) <= 2:
                parts.append("\n⚠️ OSCILLATION DETECTED — you've been going back and forth. Try something different.")

        # Stuck warning
        turns_since_meaningful = gs.turn_count - gs.last_meaningful_turn
        if turns_since_meaningful > 30:
            parts.append(
                f"\n⚠️ NO PROGRESS in {turns_since_meaningful} turns — "
                "consider exploring a new area or changing strategy."
            )

        return "\n".join(parts)

    # ── Battle Context ─────────────────────────────────────────────────

    def _build_battle_context(self, gs: GameState, raw_state: Dict[str, Any]) -> str:
        parts: List[str] = []

        parts.append(f"=== BATTLE — Turn {gs.turn_count} ===")
        parts.append(f"Type: {gs.battle_type}")

        # Enemy info
        if gs.enemy:
            parts.append(f"\n-- ENEMY --")
            parts.append(f"  {gs.enemy.species} Lv{gs.enemy.level} [{'/'.join(gs.enemy.types)}]")
            hp_pct = round(gs.enemy.hp / gs.enemy.max_hp * 100) if gs.enemy.max_hp > 0 else 0
            parts.append(f"  HP: {gs.enemy.hp}/{gs.enemy.max_hp} ({hp_pct}%) Status: {gs.enemy.status}")

            # Type analysis
            best = best_type_against(gs.enemy.types)
            if best:
                parts.append(f"  Super effective types: {', '.join(f'{t} ({m}x)' for t, m in best[:4])}")

        # Our lead
        if gs.party:
            lead = gs.party[0]
            parts.append(f"\n-- YOUR POKEMON --")
            parts.append(f"  {lead.species} Lv{lead.level} [{'/'.join(lead.types)}]")
            hp_pct = round(lead.hp / lead.max_hp * 100) if lead.max_hp > 0 else 0
            parts.append(f"  HP: {lead.hp}/{lead.max_hp} ({hp_pct}%) Status: {lead.status}")

            # Move analysis
            if lead.moves and gs.enemy:
                parts.append("  Moves:")
                for i, m in enumerate(lead.moves):
                    if m.name and m.pp > 0:
                        move_type = self._guess_move_type_simple(m.name, lead.types)
                        if move_type and gs.enemy.types:
                            eff_desc = describe_matchup(move_type, gs.enemy.types)
                        else:
                            eff_desc = "neutral"
                        is_stab = move_type in lead.types if move_type else False
                        stab_note = " (STAB)" if is_stab else ""
                        parts.append(f"    {i}. {m.name} PP:{m.pp} — {eff_desc}{stab_note}")

        # Backup Pokemon
        if len(gs.party) > 1:
            parts.append("\n-- BACKUP --")
            for i, p in enumerate(gs.party[1:], 1):
                if p.hp > 0:
                    parts.append(f"  {i}. {p.species} Lv{p.level} HP:{p.hp}/{p.max_hp}")

        # Bag items (healing)
        healing_items = [b for b in gs.bag if any(
            h in b.get("item", "").lower()
            for h in ["potion", "heal", "revive", "elixir", "berry"]
        )]
        if healing_items:
            parts.append("\n-- HEALING ITEMS --")
            for item in healing_items:
                parts.append(f"  {item.get('item')} x{item.get('quantity')}")

        return "\n".join(parts)

    # ── Dialog Context ─────────────────────────────────────────────────

    def _build_dialog_context(self, gs: GameState) -> str:
        return f"Dialog active at {gs.map_name}. Advance with A button."

    # ── Menu Context ───────────────────────────────────────────────────

    def _build_menu_context(self, gs: GameState) -> str:
        return f"Menu open at {gs.map_name}. Close with B or navigate."

    # ── Helpers ─────────────────────────────────────────────────────────

    def _get_next_gym(self, gs: GameState) -> Optional[Dict[str, Any]]:
        """Find the next undefeated gym."""
        for gym in GYM_ORDER:
            if gym["badge"] not in gs.badges:
                return gym
        return None

    def _guess_move_type_simple(self, move_name: str, pokemon_types: List[str]) -> Optional[str]:
        """Quick move type guess from name keywords."""
        name = move_name.lower()
        hints = {
            "Water": ["water", "surf", "hydro", "bubble", "aqua"],
            "Fire": ["fire", "flame", "ember", "flamethrower"],
            "Grass": ["vine", "leaf", "razor leaf", "solar", "absorb", "mega drain"],
            "Electric": ["thunder", "spark", "shock", "bolt"],
            "Ice": ["ice", "blizzard", "aurora", "frost"],
            "Psychic": ["psychic", "psybeam", "confusion"],
            "Fighting": ["karate", "submission", "seismic"],
            "Poison": ["poison", "toxic", "sludge", "acid"],
            "Ground": ["earthquake", "dig", "sand", "mud", "bone"],
            "Flying": ["gust", "wing", "fly", "peck", "drill peck"],
            "Rock": ["rock", "stone"],
            "Normal": ["tackle", "scratch", "pound", "slam", "body slam", "headbutt",
                       "hyper beam", "swift", "strength", "cut"],
        }
        for type_name, keywords in hints.items():
            for kw in keywords:
                if kw in name:
                    return type_name
        return pokemon_types[0] if pokemon_types else None
