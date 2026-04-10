"""
Battle Agent — decides fight/run/switch/item during Pokemon battles.
Uses type chart for informed decisions, LLM for complex situations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ..data.type_chart import matchup, best_type_against, describe_matchup

logger = logging.getLogger(__name__)

BATTLE_SYSTEM_PROMPT = """You are an AI playing Pokemon Blue. You are currently in a battle.

Your job: decide what battle action to take based on your party, the enemy, and the type matchup analysis provided.

## Response Format
```json
{
    "reasoning": "Brief tactical analysis (2-3 sentences)",
    "decision": "fight|run|switch|item",
    "move_index": 0,
    "switch_index": 0,
    "item_name": ""
}
```

## Decision Guidelines
- **fight**: Choose the most effective move. move_index is 0-3 (move slot).
- **run**: Only from wild battles. Use when enemy is low-threat and grinding isn't needed.
- **switch**: When current Pokemon is at type disadvantage or low HP. switch_index is party slot 0-5.
- **item**: Use healing items when lead Pokemon is below 30% HP in important battles.

## ⚠️ CRITICAL RULE: Switching with only one Pokemon

You can ONLY choose **switch** if your party has 2 or more Pokemon. If
you have only 1 Pokemon and you try to switch to it, the game shows
the message **"<Pokemon> is already out!"** and you accomplish
nothing — the turn is wasted dismissing the message. The agent has
gotten stuck in this loop before.

**If you have only 1 Pokemon and you see "<X> is already out!" in a
dialog box, press `press_b` to dismiss the message and return to the
main battle menu, then choose `fight` on the next turn.**

Rule: with `len(party) < 2`, NEVER pick `decision: "switch"`. Pick
`fight` (or `run`/`item` as appropriate) instead.

## Gen 1 Battle Tips
- Psychic type is overpowered (no real counters — Ghost is bugged, Bug moves are weak)
- Speed determines critical hit rate — fast Pokemon crit more often
- Special stat handles both Sp.Atk and Sp.Def
- Wrap/Bind prevent the opponent from acting
- STAB (Same Type Attack Bonus) is 1.5x — always prefer STAB moves
"""


class BattleAgent:
    """Battle decision agent with type-aware heuristics and LLM fallback."""

    def __init__(self, config, llm_client):
        self.config = config
        self.llm = llm_client

    async def decide(self, gs, raw_state: Dict[str, Any]) -> Tuple[List[str], str]:
        """Decide battle action and return button sequence + reasoning."""
        if not gs.enemy:
            # No enemy data — mash A to get through battle setup
            return ["press_a", "press_a"], "Waiting for battle to start..."

        # Build type analysis
        type_analysis = self._analyze_matchup(gs)

        # For simple wild encounters with clear type advantage, use heuristics
        if gs.battle_type == "wild" and self._is_simple_decision(gs, type_analysis):
            return self._heuristic_decide(gs, type_analysis)

        # Complex situation — use LLM
        return await self._llm_decide(gs, raw_state, type_analysis)

    def _analyze_matchup(self, gs) -> Dict[str, Any]:
        """Analyze type matchups for the current battle."""
        analysis: Dict[str, Any] = {"move_effectiveness": []}
        if not gs.enemy or not gs.party:
            return analysis

        lead = gs.party[0]
        enemy_types = gs.enemy.types

        # Analyze each move
        for i, move in enumerate(lead.moves):
            if not move.name or move.pp <= 0:
                continue
            # Determine move type (simplified — use move name heuristics)
            # In a real implementation, we'd have a move type database
            move_type = self._guess_move_type(move.name, lead.types)
            eff = matchup(move_type, enemy_types) if move_type else 1.0
            is_stab = move_type in lead.types if move_type else False
            analysis["move_effectiveness"].append({
                "index": i,
                "name": move.name,
                "pp": move.pp,
                "guessed_type": move_type,
                "effectiveness": eff,
                "stab": is_stab,
                "score": eff * (1.5 if is_stab else 1.0),
            })

        # Best types to use
        analysis["best_types"] = best_type_against(enemy_types)
        analysis["enemy_types"] = enemy_types
        analysis["lead_types"] = lead.types
        analysis["lead_hp_pct"] = lead.hp / lead.max_hp if lead.max_hp > 0 else 0

        return analysis

    def _is_simple_decision(self, gs, analysis: Dict[str, Any]) -> bool:
        """Check if this is a simple battle that doesn't need LLM reasoning."""
        if not analysis.get("move_effectiveness"):
            return False

        lead = gs.party[0]
        # Simple if: wild battle + lead is healthy + has a clear best move
        best_move = max(analysis["move_effectiveness"], key=lambda m: m["score"])
        return (
            gs.battle_type == "wild"
            and analysis.get("lead_hp_pct", 0) > 0.5
            and best_move["score"] >= 1.5
            and lead.level >= (gs.enemy.level if gs.enemy else 0)
        )

    def _heuristic_decide(
        self, gs, analysis: Dict[str, Any]
    ) -> Tuple[List[str], str]:
        """Fast heuristic decision for simple battles."""
        moves = analysis.get("move_effectiveness", [])
        if not moves:
            return self._fight_move(0), "No move data, using first move"

        # Pick highest scoring move
        best = max(moves, key=lambda m: m["score"])
        reasoning = (
            f"Using {best['name']} ({best['guessed_type'] or '?'} type, "
            f"{best['effectiveness']}x effective"
            f"{', STAB' if best['stab'] else ''}) against "
            f"{'/'.join(analysis.get('enemy_types', []))} {gs.enemy.species}"
        )
        return self._fight_move(best["index"]), reasoning

    async def _llm_decide(
        self, gs, raw_state: Dict[str, Any], analysis: Dict[str, Any]
    ) -> Tuple[List[str], str]:
        """LLM-powered decision for complex battles."""
        context = self._build_context(gs, analysis)
        messages = [{"role": "user", "content": context}]

        try:
            result = await self.llm.chat_json(
                role="battle",
                messages=messages,
                system=BATTLE_SYSTEM_PROMPT,
            )
            parsed = result["parsed"]
            reasoning = parsed.get("reasoning", "")
            decision = parsed.get("decision", "fight")

            # Track tokens
            usage = result.get("usage", {})
            gs.total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            # Hard guard: switching with <2 Pokemon is impossible — the
            # menu only shows your current Pokemon and selecting it opens
            # its summary, trapping the agent in the menu. Force a fight
            # instead, regardless of what the LLM picked. Also prepend
            # B presses to back out of any sub-menu we may already be
            # stuck in (e.g. if the previous turn opened the Pokemon
            # menu before this guard existed).
            cancel_prefix: List[str] = []
            if decision == "switch" and len(gs.party) < 2:
                logger.info(
                    f"Battle: LLM picked switch with {len(gs.party)} Pokemon — "
                    f"overriding to fight (cannot switch with one Pokemon)"
                )
                decision = "fight"
                cancel_prefix = ["press_b", "press_b", "press_b"]
                reasoning = (
                    f"[override] Cannot switch with only {len(gs.party)} Pokemon. "
                    f"Backing out of any open menu and attacking. " + reasoning
                )

            match decision:
                case "fight":
                    move_idx = parsed.get("move_index", 0)
                    return cancel_prefix + self._fight_move(move_idx), reasoning
                case "run":
                    return self._run_action(), reasoning
                case "switch":
                    switch_idx = parsed.get("switch_index", 1)
                    return self._switch_pokemon(switch_idx), reasoning
                case "item":
                    return self._use_item(), reasoning
                case _:
                    return self._fight_move(0), f"Unknown decision '{decision}', using first move"

        except Exception as e:
            logger.error(f"Battle LLM error: {e}")
            # Fallback: use best heuristic move
            moves = analysis.get("move_effectiveness", [])
            if moves:
                best = max(moves, key=lambda m: m["score"])
                return self._fight_move(best["index"]), f"LLM error, using {best['name']}"
            return self._fight_move(0), f"LLM error: {e}"

    def _build_context(self, gs, analysis: Dict[str, Any]) -> str:
        """Build battle context for LLM."""
        parts = []
        parts.append(f"Battle type: {gs.battle_type}")

        if gs.enemy:
            parts.append(f"\nEnemy: {gs.enemy.species} Lv{gs.enemy.level} [{'/'.join(gs.enemy.types)}]")
            parts.append(f"  HP: {gs.enemy.hp}/{gs.enemy.max_hp} Status: {gs.enemy.status}")

        lead = gs.party[0] if gs.party else None
        if lead:
            parts.append(f"\nYour lead: {lead.species} Lv{lead.level} [{'/'.join(lead.types)}]")
            parts.append(f"  HP: {lead.hp}/{lead.max_hp} Status: {lead.status}")
            parts.append("  Moves:")
            for i, m in enumerate(lead.moves):
                if m.name:
                    eff_info = ""
                    for me in analysis.get("move_effectiveness", []):
                        if me["index"] == i:
                            eff_info = f" ({me['effectiveness']}x, {'STAB' if me['stab'] else 'no STAB'})"
                    parts.append(f"    {i}. {m.name} (PP: {m.pp}){eff_info}")

        # Party backup options
        if len(gs.party) > 1:
            parts.append("\nBackup Pokemon:")
            for i, p in enumerate(gs.party[1:], 1):
                if p.hp > 0:
                    parts.append(f"  {i}. {p.species} Lv{p.level} HP:{p.hp}/{p.max_hp}")

        # Type analysis summary
        if analysis.get("best_types"):
            good = ", ".join(f"{t} ({m}x)" for t, m in analysis["best_types"][:3])
            parts.append(f"\nBest types vs enemy: {good}")

        return "\n".join(parts)

    # ── Button Sequences ───────────────────────────────────────────────

    def _fight_move(self, move_index: int) -> List[str]:
        """Navigate battle menu to select FIGHT and then a specific move."""
        # FIGHT is top-left (default position when battle menu opens)
        actions = ["press_a"]  # Select FIGHT

        # Navigate to move slot (0=top-left, 1=top-right, 2=bottom-left, 3=bottom-right)
        match move_index:
            case 0:
                pass  # Already at position 0
            case 1:
                actions.append("press_right")
            case 2:
                actions.append("press_down")
            case 3:
                actions.extend(["press_right", "press_down"])

        actions.append("press_a")  # Confirm move selection
        # Wait for attack animation
        actions.extend(["wait_60", "wait_60"])
        return actions

    def _run_action(self) -> List[str]:
        """Navigate to RUN (bottom-right of battle menu)."""
        return ["press_right", "press_down", "press_a", "wait_60"]

    def _switch_pokemon(self, party_index: int) -> List[str]:
        """Navigate to switch Pokemon."""
        # Open Pokemon menu (right option in battle)
        actions = ["press_right", "press_a"]  # Select POKEMON
        # Navigate down to the target slot
        for _ in range(party_index):
            actions.append("press_down")
        actions.extend(["press_a", "press_a"])  # Select Pokemon, confirm switch
        actions.append("wait_60")
        return actions

    def _use_item(self) -> List[str]:
        """Navigate to BAG and use first usable item."""
        # BAG is bottom-left of battle menu
        return ["press_down", "press_a", "press_a", "press_a", "wait_60"]

    # ── Type Guessing ──────────────────────────────────────────────────

    def _guess_move_type(self, move_name: str, pokemon_types: List[str]) -> str | None:
        """Guess move type from name. Returns None if unknown.

        This is a simplified heuristic. A full implementation would use
        a move database with type data.
        """
        name = move_name.lower()

        # Common move type indicators
        type_hints = {
            "Water": ["water", "surf", "hydro", "bubble", "rain", "aqua", "brine", "dive"],
            "Fire": ["fire", "flame", "ember", "burn", "blaze", "heat", "flamethrower"],
            "Grass": ["vine", "leaf", "razor leaf", "solar", "seed", "leech", "absorb", "mega drain"],
            "Electric": ["thunder", "spark", "shock", "volt", "electric", "bolt"],
            "Ice": ["ice", "blizzard", "freeze", "aurora", "frost"],
            "Psychic": ["psychic", "psybeam", "confusion", "hypnosis", "dream"],
            "Fighting": ["karate", "submission", "seismic", "jump kick", "hi jump"],
            "Poison": ["poison", "toxic", "sludge", "acid", "smog"],
            "Ground": ["earthquake", "dig", "sand", "mud", "fissure", "bone"],
            "Flying": ["gust", "wing", "fly", "peck", "drill peck", "sky", "aerial"],
            "Rock": ["rock", "stone"],
            "Bug": ["pin missile", "twineedle", "leech life", "string shot"],
            "Ghost": ["lick", "night shade", "confuse ray"],
            "Dragon": ["dragon rage", "dragon"],
            "Normal": [
                "tackle", "scratch", "pound", "slam", "body slam", "headbutt",
                "hyper beam", "swift", "take down", "double-edge", "mega punch",
                "strength", "cut", "stomp", "rage", "thrash",
            ],
        }

        for type_name, keywords in type_hints.items():
            for keyword in keywords:
                if keyword in name:
                    return type_name

        # Default: if move name doesn't match any type, assume same type as Pokemon (STAB guess)
        return pokemon_types[0] if pokemon_types else None
