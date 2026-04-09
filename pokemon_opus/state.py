"""
Central game state — single dataclass holding all mutable state.
All managers read/write fields directly. Adapted from Zork-Opus state.py.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class GameMode(str, Enum):
    EXPLORE = "explore"
    BATTLE = "battle"
    DIALOG = "dialog"
    MENU = "menu"


# ---------------------------------------------------------------------------
# Data Models (Pydantic for serialization)
# ---------------------------------------------------------------------------

class Pokemon(BaseModel):
    """A Pokemon in the party or encountered in battle."""
    species_id: int = 0
    species: str = "MissingNo."
    nickname: str = ""
    level: int = 1
    hp: int = 0
    max_hp: int = 0
    status: str = "OK"  # OK, SLP, PSN, BRN, FRZ, PAR
    types: List[str] = Field(default_factory=list)  # e.g. ["Water"], ["Grass", "Poison"]
    moves: List[Move] = Field(default_factory=list)
    attack: int = 0
    defense: int = 0
    speed: int = 0
    special: int = 0
    experience: int = 0


class Move(BaseModel):
    """A Pokemon move."""
    id: int = 0
    name: str = ""
    pp: int = 0


class ActionEntry(BaseModel):
    """Single entry in action history."""
    actions: List[str]  # Button presses sent to emulator
    reasoning: str = ""
    mode: str = "explore"
    map_id: int = 0
    map_name: str = ""
    position: Tuple[int, int] = (0, 0)
    turn: int = 0


class Objective(BaseModel):
    """Structured objective with lifecycle tracking."""
    id: str
    category: Literal["exploration", "battle", "collection", "progression"] = "exploration"
    name: str
    text: str
    completion_condition: str
    status: Literal["pending", "in_progress", "completed", "abandoned"] = "pending"
    created_turn: int = 0
    completed_turn: Optional[int] = None
    target_map_id: Optional[int] = None
    progress: Optional[str] = None


class Milestone(BaseModel):
    """A notable achievement."""
    name: str
    turn: int
    details: str = ""
    category: str = "general"  # badge, catch, item, progression


class StateDelta(BaseModel):
    """What changed between pre-action and post-action state."""
    location_changed: bool = False
    old_map_id: int = 0
    new_map_id: int = 0
    old_map_name: str = ""
    new_map_name: str = ""
    old_position: Tuple[int, int] = (0, 0)
    new_position: Tuple[int, int] = (0, 0)
    hp_changed: bool = False
    party_changed: bool = False
    badge_gained: Optional[str] = None
    pokemon_caught: Optional[str] = None
    item_gained: Optional[str] = None
    item_lost: Optional[str] = None
    money_delta: int = 0
    battle_started: bool = False
    battle_ended: bool = False
    pokemon_fainted: Optional[str] = None
    pokemon_leveled: Optional[str] = None
    new_level: Optional[int] = None

    def is_meaningful(self) -> bool:
        """True if anything noteworthy happened."""
        return (
            self.location_changed
            or self.hp_changed
            or self.party_changed
            or self.badge_gained is not None
            or self.pokemon_caught is not None
            or self.item_gained is not None
            or self.battle_started
            or self.battle_ended
            or self.pokemon_leveled is not None
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True, exclude_defaults=True)


# ---------------------------------------------------------------------------
# Central Mutable Game State
# ---------------------------------------------------------------------------

@dataclass
class GameState:
    """All mutable state for one episode. Managers access fields directly."""

    # Core
    episode_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    turn_count: int = 0
    game_mode: GameMode = GameMode.EXPLORE
    game_over: bool = False

    # Player (synced from RAM each turn)
    player_name: str = ""
    rival_name: str = ""
    money: int = 0
    badges: List[str] = field(default_factory=list)
    badge_count: int = 0
    position: Tuple[int, int] = (0, 0)
    facing: str = "down"
    map_id: int = 0
    map_name: str = ""
    play_time: str = ""

    # Party
    party: List[Pokemon] = field(default_factory=list)

    # Bag
    bag: List[Dict[str, Any]] = field(default_factory=list)

    # Battle
    in_battle: bool = False
    battle_type: str = "none"  # none, wild, trainer
    enemy: Optional[Pokemon] = None

    # Dialog
    dialog_active: bool = False

    # Flags
    has_pokedex: bool = False
    pokedex_owned: int = 0
    pokedex_seen: int = 0

    # Tracking
    action_history: List[ActionEntry] = field(default_factory=list)
    visited_maps: Set[int] = field(default_factory=set)
    milestones: List[Milestone] = field(default_factory=list)

    # Objectives
    objectives: List[Objective] = field(default_factory=list)
    objective_id_counter: int = 0

    # Navigation
    prev_map_id: int = 0
    prev_map_name: str = ""
    prev_position: Tuple[int, int] = (0, 0)

    # Reasoning (last turn's AI output)
    last_reasoning: str = ""
    last_actions: List[str] = field(default_factory=list)

    # Stuck detection
    last_badge_turn: int = 0
    last_meaningful_turn: int = 0

    # Performance
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    start_time: float = field(default_factory=time.time)

    # Episode summary
    final_badges: int = 0
    final_pokedex: int = 0

    def reset_episode(self) -> None:
        """Reset for a new episode, preserving cross-episode data."""
        self.episode_id = str(uuid.uuid4())[:8]
        self.turn_count = 0
        self.game_mode = GameMode.EXPLORE
        self.game_over = False
        self.action_history.clear()
        self.milestones.clear()
        self.objectives.clear()
        self.objective_id_counter = 0
        self.last_reasoning = ""
        self.last_actions.clear()
        self.last_badge_turn = 0
        self.last_meaningful_turn = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.start_time = time.time()

    def next_objective_id(self) -> str:
        """Generate the next objective ID."""
        self.objective_id_counter += 1
        return f"OBJ-{self.objective_id_counter:03d}"

    @property
    def active_objectives(self) -> List[Objective]:
        return [o for o in self.objectives if o.status in ("pending", "in_progress")]

    @property
    def completed_objectives(self) -> List[Objective]:
        return [o for o in self.objectives if o.status == "completed"]

    @property
    def runtime_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def runtime_display(self) -> str:
        s = int(self.runtime_seconds)
        h, remainder = divmod(s, 3600)
        m, sec = divmod(remainder, 60)
        return f"{h}:{m:02d}:{sec:02d}"

    def serialize(self) -> Dict[str, Any]:
        """Serialize for WebSocket broadcast / JSON export."""
        return {
            "episode_id": self.episode_id,
            "turn": self.turn_count,
            "mode": self.game_mode.value,
            "player": {
                "name": self.player_name,
                "rival": self.rival_name,
                "money": self.money,
                "badges": self.badges,
                "badge_count": self.badge_count,
                "position": list(self.position),
                "facing": self.facing,
                "map_id": self.map_id,
                "map_name": self.map_name,
                "play_time": self.play_time,
            },
            "party": [p.model_dump() for p in self.party],
            "bag": self.bag,
            "battle": {
                "in_battle": self.in_battle,
                "type": self.battle_type,
                "enemy": self.enemy.model_dump() if self.enemy else None,
            },
            "dialog_active": self.dialog_active,
            "flags": {
                "has_pokedex": self.has_pokedex,
                "pokedex_owned": self.pokedex_owned,
                "pokedex_seen": self.pokedex_seen,
            },
            "objectives": [o.model_dump() for o in self.active_objectives],
            "milestones": [m.model_dump() for m in self.milestones],
            "performance": {
                "total_tokens": self.total_tokens,
                "total_cost_usd": round(self.total_cost_usd, 4),
                "runtime": self.runtime_display,
                "runtime_seconds": round(self.runtime_seconds, 1),
            },
            "last_reasoning": self.last_reasoning,
            "last_actions": self.last_actions,
        }
