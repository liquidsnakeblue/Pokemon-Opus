"""
Memory Manager — dual-cache memory system for Pokemon-Opus.
Adapted from Zork-Opus memory.py.

Two caches:
- Persistent: survives across episodes (route connections, trainer data, gym strategies)
- Ephemeral: cleared each episode (current objectives progress, recent battle outcomes)

Memories are keyed by map_id (location). Each memory has a category, status,
and can be superseded or invalidated as the agent learns more.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TENTATIVE = "TENTATIVE"
    SUPERSEDED = "SUPERSEDED"


class MemoryCategory(str, Enum):
    ROUTE = "ROUTE"           # Route connections and layout
    TRAINER = "TRAINER"       # Trainer battles and teams
    ITEM = "ITEM"             # Item locations
    POKEMON = "POKEMON"       # Wild Pokemon encounters
    BATTLE = "BATTLE"         # Battle outcomes and strategies
    STRATEGY = "STRATEGY"     # Strategic observations
    DANGER = "DANGER"         # Hazards, roadblocks
    LANDMARK = "LANDMARK"     # Key locations (Pokemon Centers, shops, gyms)
    DISCOVERY = "DISCOVERY"   # General discoveries


class MemoryPersistence(str, Enum):
    CORE = "core"             # Never deleted (fundamental map knowledge)
    PERMANENT = "permanent"   # Survives episodes (learned strategies)
    EPHEMERAL = "ephemeral"   # Cleared each episode


@dataclass
class Memory:
    """A single memory entry."""
    category: str
    title: str
    text: str
    episode: str
    turn: int
    persistence: str = "permanent"
    status: str = MemoryStatus.ACTIVE
    superseded_by: Optional[str] = None
    superseded_at_turn: Optional[int] = None
    invalidation_reason: Optional[str] = None
    map_id: Optional[int] = None
    map_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Dual Cache
# ---------------------------------------------------------------------------

class MemoryCache:
    """Two-tier memory cache: persistent (cross-episode) + ephemeral (this episode)."""

    def __init__(self):
        self.persistent: Dict[int, List[Memory]] = {}  # map_id -> memories
        self.ephemeral: Dict[int, List[Memory]] = {}

    def add(self, map_id: int, memory: Memory) -> None:
        if memory.persistence == MemoryPersistence.EPHEMERAL:
            self.ephemeral.setdefault(map_id, []).append(memory)
        else:
            self.persistent.setdefault(map_id, []).append(memory)

    def get(
        self,
        map_id: int,
        include_superseded: bool = False,
        persistent_only: bool = False,
        ephemeral_only: bool = False,
    ) -> List[Memory]:
        """Get memories for a location, filtered by status and cache tier."""
        results: List[Memory] = []

        if not ephemeral_only:
            for m in self.persistent.get(map_id, []):
                if include_superseded or m.status == MemoryStatus.ACTIVE:
                    results.append(m)

        if not persistent_only:
            for m in self.ephemeral.get(map_id, []):
                if include_superseded or m.status == MemoryStatus.ACTIVE:
                    results.append(m)

        return results

    def get_all_active(self) -> List[Memory]:
        """Get all active memories across all locations."""
        results: List[Memory] = []
        for memories in self.persistent.values():
            results.extend(m for m in memories if m.status == MemoryStatus.ACTIVE)
        for memories in self.ephemeral.values():
            results.extend(m for m in memories if m.status == MemoryStatus.ACTIVE)
        return results

    def supersede(
        self, map_id: int, title: str, by_title: str, turn: int
    ) -> bool:
        """Mark a memory as superseded by a newer one."""
        for cache in (self.persistent, self.ephemeral):
            for m in cache.get(map_id, []):
                if m.title == title and m.status == MemoryStatus.ACTIVE:
                    m.status = MemoryStatus.SUPERSEDED
                    m.superseded_by = by_title
                    m.superseded_at_turn = turn
                    return True
        return False

    def invalidate(
        self, map_id: int, title: str, reason: str, turn: int
    ) -> bool:
        """Mark a memory as invalidated (was wrong)."""
        for cache in (self.persistent, self.ephemeral):
            for m in cache.get(map_id, []):
                if m.title == title and m.status == MemoryStatus.ACTIVE:
                    m.status = MemoryStatus.SUPERSEDED
                    m.invalidation_reason = reason
                    m.superseded_at_turn = turn
                    return True
        return False

    def clear_ephemeral(self) -> None:
        """Clear all ephemeral memories (new episode)."""
        self.ephemeral.clear()

    def count(self) -> Dict[str, int]:
        """Count memories by tier."""
        p = sum(len(v) for v in self.persistent.values())
        e = sum(len(v) for v in self.ephemeral.values())
        return {"persistent": p, "ephemeral": e, "total": p + e}


# ---------------------------------------------------------------------------
# Memory Manager
# ---------------------------------------------------------------------------

class MemoryManager:
    """Manages memory creation, retrieval, synthesis, and persistence.

    The manager can operate in two modes:
    - With LLM: synthesizes memories from game events using AI
    - Without LLM: creates memories from structured deltas (rule-based)
    """

    def __init__(
        self,
        config,
        llm_client=None,
        memory_file: str = "memories.md",
    ):
        self.config = config
        self.llm = llm_client
        self.memory_file = Path(memory_file)
        self.cache = MemoryCache()
        self._load_from_file()

    # ── Public API ─────────────────────────────────────────────────────

    async def record(self, gs, deltas) -> Optional[Memory]:
        """Record a memory from game state deltas.

        Called by the orchestrator after each turn when something meaningful happened.
        Uses LLM synthesis if available, falls back to rule-based creation.
        """
        if self.llm:
            return await self._synthesize_with_llm(gs, deltas)
        return self._synthesize_rule_based(gs, deltas)

    def get_location_memories(self, map_id: int, max_count: int = 0) -> List[Memory]:
        """Get active memories for a specific location."""
        memories = self.cache.get(map_id)
        if max_count > 0:
            return memories[:max_count]
        return memories

    def get_location_memory_text(self, map_id: int, map_name: str = "") -> str:
        """Get formatted memory text for a location (for prompt injection)."""
        memories = self.get_location_memories(map_id, self.config.max_memories_shown)
        if not memories:
            return ""

        header = f"=== MEMORIES: {map_name or f'Map {map_id}'} ==="
        lines = [header]
        for m in memories:
            status = f" [{m.status}]" if m.status != MemoryStatus.ACTIVE else ""
            lines.append(f"  [{m.category}] {m.title}{status}")
            lines.append(f"    {m.text}")
        return "\n".join(lines)

    def get_global_summary(self, max_entries: int = 20) -> str:
        """Get a summary of all important memories across locations."""
        all_memories = self.cache.get_all_active()
        # Prioritize: STRATEGY > BATTLE > LANDMARK > ROUTE > others
        priority = {
            "STRATEGY": 0, "BATTLE": 1, "LANDMARK": 2,
            "ROUTE": 3, "TRAINER": 4, "ITEM": 5,
            "POKEMON": 6, "DANGER": 7, "DISCOVERY": 8,
        }
        sorted_memories = sorted(all_memories, key=lambda m: priority.get(m.category, 9))
        top = sorted_memories[:max_entries]

        if not top:
            return ""

        lines = ["=== KEY MEMORIES ==="]
        for m in top:
            loc = f" @ {m.map_name}" if m.map_name else ""
            lines.append(f"  [{m.category}]{loc} {m.title}: {m.text}")
        return "\n".join(lines)

    def clear_episode(self) -> None:
        """Clear ephemeral memories for a new episode."""
        self.cache.clear_ephemeral()

    # ── Rule-Based Synthesis ───────────────────────────────────────────

    def _synthesize_rule_based(self, gs, deltas) -> Optional[Memory]:
        """Create memories from structured deltas without LLM."""
        memory = None

        if deltas.badge_gained:
            memory = Memory(
                category=MemoryCategory.BATTLE,
                title=f"Earned {deltas.badge_gained} Badge",
                text=f"Defeated the gym leader and earned the {deltas.badge_gained} Badge at {gs.map_name}.",
                episode=gs.episode_id,
                turn=gs.turn_count,
                persistence=MemoryPersistence.CORE,
                map_id=gs.map_id,
                map_name=gs.map_name,
            )

        elif deltas.pokemon_caught:
            memory = Memory(
                category=MemoryCategory.POKEMON,
                title=f"Caught {deltas.pokemon_caught}",
                text=f"Caught a wild {deltas.pokemon_caught} at {gs.map_name}.",
                episode=gs.episode_id,
                turn=gs.turn_count,
                persistence=MemoryPersistence.PERMANENT,
                map_id=gs.map_id,
                map_name=gs.map_name,
            )

        elif deltas.location_changed:
            memory = Memory(
                category=MemoryCategory.ROUTE,
                title=f"{deltas.old_map_name} → {deltas.new_map_name}",
                text=f"Traveled from {deltas.old_map_name} to {deltas.new_map_name}.",
                episode=gs.episode_id,
                turn=gs.turn_count,
                persistence=MemoryPersistence.CORE,
                map_id=gs.map_id,
                map_name=gs.map_name,
            )

        elif deltas.item_gained:
            memory = Memory(
                category=MemoryCategory.ITEM,
                title=f"Found {deltas.item_gained}",
                text=f"Obtained {deltas.item_gained} at {gs.map_name} ({gs.position}).",
                episode=gs.episode_id,
                turn=gs.turn_count,
                persistence=MemoryPersistence.PERMANENT,
                map_id=gs.map_id,
                map_name=gs.map_name,
            )

        elif deltas.battle_ended:
            result = "won" if not any(p.hp <= 0 for p in gs.party[:1]) else "lost"
            memory = Memory(
                category=MemoryCategory.BATTLE,
                title=f"Battle {'victory' if result == 'won' else 'defeat'} at {gs.map_name}",
                text=f"{'Won' if result == 'won' else 'Lost'} a {gs.battle_type} battle at {gs.map_name}.",
                episode=gs.episode_id,
                turn=gs.turn_count,
                persistence=MemoryPersistence.EPHEMERAL,
                map_id=gs.map_id,
                map_name=gs.map_name,
            )

        if memory:
            self.cache.add(memory.map_id or gs.map_id, memory)
            self._append_to_file(memory)
            logger.debug(f"Memory created: [{memory.category}] {memory.title}")

        return memory

    # ── LLM Synthesis ──────────────────────────────────────────────────

    async def _synthesize_with_llm(self, gs, deltas) -> Optional[Memory]:
        """Use LLM to synthesize a richer memory from game events."""
        # Build context for synthesis
        context = self._build_synthesis_context(gs, deltas)

        try:
            result = await self.llm.chat_json(
                role="memory",
                messages=[{"role": "user", "content": context}],
                system=MEMORY_SYNTHESIS_PROMPT,
            )
            parsed = result["parsed"]

            usage = result.get("usage", {})
            gs.total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            if not parsed.get("should_remember", False):
                return None

            memory = Memory(
                category=parsed.get("category", "DISCOVERY"),
                title=parsed.get("title", "Observation"),
                text=parsed.get("text", ""),
                episode=gs.episode_id,
                turn=gs.turn_count,
                persistence=parsed.get("persistence", "permanent"),
                map_id=gs.map_id,
                map_name=gs.map_name,
            )

            # Handle supersessions
            for old_title in parsed.get("supersedes", []):
                self.cache.supersede(gs.map_id, old_title, memory.title, gs.turn_count)

            # Handle invalidations
            for inv in parsed.get("invalidates", []):
                if isinstance(inv, dict):
                    self.cache.invalidate(
                        gs.map_id, inv.get("title", ""), inv.get("reason", ""), gs.turn_count
                    )

            self.cache.add(gs.map_id, memory)
            self._append_to_file(memory)
            logger.debug(f"Memory synthesized: [{memory.category}] {memory.title}")
            return memory

        except Exception as e:
            logger.warning(f"LLM memory synthesis failed, falling back to rules: {e}")
            return self._synthesize_rule_based(gs, deltas)

    def _build_synthesis_context(self, gs, deltas) -> str:
        """Build context for LLM memory synthesis."""
        parts = [
            f"Turn: {gs.turn_count}",
            f"Location: {gs.map_name} (map_id={gs.map_id})",
            f"Position: {gs.position}",
            f"Badges: {gs.badge_count}",
        ]

        # What changed
        changes = []
        if deltas.location_changed:
            changes.append(f"Moved from {deltas.old_map_name} to {deltas.new_map_name}")
        if deltas.badge_gained:
            changes.append(f"Earned {deltas.badge_gained} Badge!")
        if deltas.pokemon_caught:
            changes.append(f"Caught {deltas.pokemon_caught}")
        if deltas.item_gained:
            changes.append(f"Found {deltas.item_gained}")
        if deltas.item_lost:
            changes.append(f"Lost/used {deltas.item_lost}")
        if deltas.battle_started:
            changes.append(f"Battle started ({gs.battle_type})")
        if deltas.battle_ended:
            changes.append("Battle ended")
        if deltas.pokemon_leveled:
            changes.append(f"{deltas.pokemon_leveled} leveled up to {deltas.new_level}")

        parts.append(f"\nChanges this turn:\n  " + "\n  ".join(changes) if changes else "\nNo major changes")

        # Existing memories for this location
        existing = self.get_location_memory_text(gs.map_id, gs.map_name)
        if existing:
            parts.append(f"\n{existing}")

        # Last action context
        if gs.last_reasoning:
            parts.append(f"\nAgent reasoning: {gs.last_reasoning[:300]}")

        return "\n".join(parts)

    # ── File Persistence ───────────────────────────────────────────────

    def _load_from_file(self) -> None:
        """Load persistent memories from the markdown file."""
        if not self.memory_file.exists():
            return

        try:
            content = self.memory_file.read_text()
            current_map_id: Optional[int] = None
            current_map_name = ""

            for line in content.split("\n"):
                # Parse location headers: ## Map 38: Red's House 2F
                header_match = re.match(r"^## Map (\d+): (.+)$", line)
                if header_match:
                    current_map_id = int(header_match.group(1))
                    current_map_name = header_match.group(2)
                    continue

                # Parse memory entries: **[ROUTE - CORE - ACTIVE] Title** *(Ep abc, T42)*
                mem_match = re.match(
                    r"^\*\*\[(\w+)\s*-\s*(\w+)\s*-\s*(\w+)\]\s+(.+?)\*\*\s*\*\(Ep\s*(\w+),\s*T(\d+)\)\*$",
                    line,
                )
                if mem_match and current_map_id is not None:
                    category, persistence, status, title, episode, turn = mem_match.groups()
                    # Only load active persistent memories
                    if status == "ACTIVE" and persistence != "ephemeral":
                        memory = Memory(
                            category=category,
                            title=title,
                            text="",  # Text is on next line
                            episode=episode,
                            turn=int(turn),
                            persistence=persistence.lower(),
                            status=status,
                            map_id=current_map_id,
                            map_name=current_map_name,
                        )
                        self.cache.add(current_map_id, memory)

            counts = self.cache.count()
            if counts["total"] > 0:
                logger.info(f"Loaded {counts['total']} memories from {self.memory_file}")

        except Exception as e:
            logger.warning(f"Failed to load memories from {self.memory_file}: {e}")

    def _append_to_file(self, memory: Memory) -> None:
        """Append a memory to the markdown file."""
        try:
            map_id = memory.map_id or 0
            map_name = memory.map_name or "Unknown"

            entry = (
                f"\n## Map {map_id}: {map_name}\n\n"
                f"**[{memory.category} - {memory.persistence.upper()} - {memory.status}] "
                f"{memory.title}** *(Ep {memory.episode}, T{memory.turn})*\n"
                f"{memory.text}\n"
            )

            with open(self.memory_file, "a") as f:
                f.write(entry)

        except Exception as e:
            logger.warning(f"Failed to write memory to file: {e}")

    def save(self) -> None:
        """Rewrite the full memory file from cache (called at episode end)."""
        try:
            lines: List[str] = ["# Pokemon-Opus Memories\n\n"]

            # Group by map_id
            all_map_ids: Set[int] = set()
            for cache in (self.cache.persistent, self.cache.ephemeral):
                all_map_ids.update(cache.keys())

            for map_id in sorted(all_map_ids):
                memories = self.cache.get(map_id, include_superseded=True)
                if not memories:
                    continue

                map_name = memories[0].map_name or "Unknown"
                lines.append(f"## Map {map_id}: {map_name}\n\n")

                for m in memories:
                    status_marker = ""
                    if m.status == MemoryStatus.SUPERSEDED:
                        if m.invalidation_reason:
                            status_marker = f"\n[Invalidated at T{m.superseded_at_turn}: \"{m.invalidation_reason}\"]"
                        elif m.superseded_by:
                            status_marker = f"\n[Superseded by \"{m.superseded_by}\" at T{m.superseded_at_turn}]"

                    lines.append(
                        f"**[{m.category} - {m.persistence.upper()} - {m.status}] "
                        f"{m.title}** *(Ep {m.episode}, T{m.turn})*\n"
                        f"{m.text}{status_marker}\n\n"
                    )

                lines.append("---\n\n")

            self.memory_file.write_text("".join(lines))
            logger.info(f"Memories saved to {self.memory_file}")

        except Exception as e:
            logger.error(f"Failed to save memories: {e}")


# ---------------------------------------------------------------------------
# LLM Prompt
# ---------------------------------------------------------------------------

MEMORY_SYNTHESIS_PROMPT = """You are the memory system for an AI playing Pokemon Blue.
Your job: decide whether this turn's events are worth remembering, and if so, create a structured memory.

## Response Format
```json
{
    "should_remember": true,
    "category": "ROUTE|TRAINER|ITEM|POKEMON|BATTLE|STRATEGY|DANGER|LANDMARK|DISCOVERY",
    "title": "Short descriptive title",
    "text": "Detailed memory text (1-2 sentences)",
    "persistence": "core|permanent|ephemeral",
    "supersedes": ["Old Memory Title"],
    "invalidates": [{"title": "Wrong Memory", "reason": "Why it was wrong"}]
}
```

## When to Remember
- New route connection discovered → ROUTE (core)
- Trainer defeated or encountered → TRAINER (permanent)
- Item found at specific location → ITEM (permanent)
- Wild Pokemon species spotted → POKEMON (permanent)
- Gym battle strategy that worked/failed → BATTLE/STRATEGY (permanent)
- Pokemon Center / Mart location → LANDMARK (core)
- Roadblock or hazard → DANGER (permanent)

## When NOT to Remember
- Routine wild encounters (already known species in known area)
- Walking between known locations (unless new shortcut found)
- Dialog that doesn't contain useful information
- Repeated trainer battles (already recorded)

## Persistence Levels
- core: Map structure, key locations — never deleted
- permanent: Learned strategies, item locations — survives episodes
- ephemeral: Current battle status, healing needs — cleared each episode

Be selective. Only create memories that will help future decision-making.
"""
