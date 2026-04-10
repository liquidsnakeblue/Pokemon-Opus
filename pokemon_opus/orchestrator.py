"""
Orchestrator — Game mode state machine and turn loop.
The central conductor that coordinates all components.
Adapted from Zork-Opus orchestrator.py for Pokemon Blue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .game_client import GameClient
from .map.grid import GridAccumulator
from .state import (
    ActionEntry, GameMode, GameState, Milestone, Move, Pokemon, StateDelta,
)
from .streaming.server import StreamServer

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main game loop orchestrator with mode-based agent routing."""

    def __init__(
        self,
        config: Config,
        game_client: GameClient,
        stream: StreamServer,
        llm_client=None,
        memory_manager=None,
        objective_manager=None,
        map_manager=None,
        context_builder=None,
    ):
        self.config = config
        self.game = game_client
        self.stream = stream
        self.llm = llm_client
        self.memory = memory_manager
        self.objectives = objective_manager
        self.map_mgr = map_manager
        self.context = context_builder
        self.gs = GameState()

        # Accumulates tile observations into a per-map grid for A* pathfinding
        self.grid = GridAccumulator()

        # Agents (lazily imported to avoid circular deps)
        self._intro_agent = None
        self._explore_agent = None
        self._battle_agent = None
        self._menu_agent = None
        self._strategist = None

        # Stuck detection
        self._consecutive_errors: int = 0
        self._max_consecutive_errors: int = 5

        # Tracks whether we've seen the game leave the title/intro state.
        # The first turn play_time is non-zero we wipe the accumulator
        # to discard any garbage that was observed during the intro before
        # the game-started gate was in place (e.g. older episode data).
        self._game_started_seen: bool = False

    # ── Agent Access ───────────────────────────────────────────────────

    @property
    def intro_agent(self):
        if self._intro_agent is None:
            from .agents.intro import IntroAgent
            self._intro_agent = IntroAgent(self.config, self.llm, game_client=self.game)
        return self._intro_agent

    @property
    def explore_agent(self):
        if self._explore_agent is None:
            from .agents.explore import ExploreAgent
            self._explore_agent = ExploreAgent(
                self.config, self.llm, game_client=self.game, grid=self.grid
            )
        return self._explore_agent

    @property
    def battle_agent(self):
        if self._battle_agent is None:
            from .agents.battle import BattleAgent
            self._battle_agent = BattleAgent(self.config, self.llm)
        return self._battle_agent

    @property
    def menu_agent(self):
        if self._menu_agent is None:
            from .agents.menu import MenuAgent
            self._menu_agent = MenuAgent(self.config)
        return self._menu_agent

    @property
    def strategist(self):
        if self._strategist is None:
            from .agents.strategist import Strategist
            self._strategist = Strategist(self.config, self.llm)
        return self._strategist

    # ── Episode Lifecycle ──────────────────────────────────────────────

    async def play_episode(self) -> Dict[str, Any]:
        """Run a complete episode from the current game state."""
        self.gs.reset_episode()
        logger.info(f"Episode {self.gs.episode_id} starting")
        await self.stream.broadcast_episode_start(self.gs.episode_id)

        try:
            # Read initial state
            raw = await self.game.get_state()
            self._sync_state_from_raw(raw)
            self.gs.visited_maps.add(self.gs.map_id)

            logger.info(
                f"Starting at {self.gs.map_name} ({self.gs.position}), "
                f"Party: {len(self.gs.party)} Pokemon"
            )

            # Main game loop
            while not self.gs.game_over and self.gs.turn_count < self.config.max_turns_per_episode:
                try:
                    await self._run_turn()
                    self._consecutive_errors = 0
                except Exception as e:
                    self._consecutive_errors += 1
                    logger.error(f"Turn {self.gs.turn_count} error ({self._consecutive_errors}): {e}")
                    await self.stream.broadcast_error(f"Turn error: {e}")
                    if self._consecutive_errors >= self._max_consecutive_errors:
                        logger.error("Too many consecutive errors, ending episode")
                        self.gs.game_over = True
                        break
                    await asyncio.sleep(2.0)  # Brief pause before retry

                # Periodic tasks
                await self._periodic_tasks()

                # Turn delay
                if self.config.turn_delay_seconds > 0:
                    await asyncio.sleep(self.config.turn_delay_seconds)

        except Exception as e:
            logger.error(f"Episode failed: {e}", exc_info=True)
            await self.stream.broadcast_error(f"Episode failed: {e}")

        # Finalize
        self.gs.final_badges = self.gs.badge_count
        self.gs.final_pokedex = self.gs.pokedex_owned
        await self.stream.broadcast_episode_end(
            self.gs.badge_count, self.gs.pokedex_owned, self.gs.turn_count
        )
        logger.info(
            f"Episode {self.gs.episode_id} ended: "
            f"{self.gs.badge_count} badges, {self.gs.pokedex_owned} caught, "
            f"{self.gs.turn_count} turns"
        )
        return self.gs.serialize()

    # ── Turn Execution ─────────────────────────────────────────────────

    async def _run_turn(self) -> None:
        """Execute a single logical turn."""
        self.gs.turn_count += 1

        # Phase 1: Read pre-action state
        pre_state = await self.game.get_state()
        self._sync_state_from_raw(pre_state)

        # Phase 2: Detect game mode
        new_mode = self._detect_mode(pre_state)
        if new_mode != self.gs.game_mode:
            old_mode = self.gs.game_mode
            self.gs.game_mode = new_mode
            await self.stream.broadcast_mode_change(old_mode.value, new_mode.value)
            logger.info(f"Mode: {old_mode.value} → {new_mode.value}")

            # Special mode transition events
            if new_mode == GameMode.BATTLE and not old_mode == GameMode.BATTLE:
                enemy_data = self.gs.enemy.model_dump() if self.gs.enemy else {}
                await self.stream.broadcast_battle_start(enemy_data, self.gs.battle_type)

        await self.stream.broadcast_turn_start(
            self.gs.turn_count, self.gs.game_mode.value, self.gs.map_name
        )

        # Phase 2b: Read tile grid and feed into the accumulator.
        # This runs before the agent decides, so the agent can query
        # self.grid for pathfinding in the current map.
        #
        # IMPORTANT: do NOT feed the accumulator while we're still on the
        # title screen / Oak's speech / naming sequence. During those
        # screens the player position and map_id RAM fields hold default
        # values ("Red's House 2F", random coords) and read_tiles is
        # reading title-screen graphics — observing all of that would
        # pollute the real map's grid with garbage. We use play_time as
        # the gate: it stays at "0:00:00" until the game actually begins
        # (the first frame the player has control after waking up in
        # bed), then ticks up forever after.
        tile_data: Optional[Dict[str, Any]] = None
        try:
            tile_data = await self.game.get_tiles()
            tgrid = tile_data.get("grid", [])
            game_started = self.gs.play_time and self.gs.play_time != "0:00:00"
            if tgrid and game_started:
                # First post-intro observation: discard any stale data
                # that was accumulated under RAM-default coords/map_id.
                if not self._game_started_seen:
                    self._game_started_seen = True
                    if self.grid.maps:
                        logger.info(
                            f"Game started — clearing {len(self.grid.maps)} stale "
                            f"intro-era map(s) from accumulator"
                        )
                        self.grid.maps.clear()
                self.grid.observe(
                    map_id=self.gs.map_id,
                    map_name=self.gs.map_name,
                    player_y=self.gs.position[0],
                    player_x=self.gs.position[1],
                    tile_grid=tgrid,
                    turn=self.gs.turn_count,
                )
        except Exception as e:
            logger.debug(f"Tile read failed: {e}")

        # Phase 3: Route to appropriate agent
        actions, reasoning = await self._decide(pre_state)
        self.gs.last_reasoning = reasoning
        self.gs.last_actions = actions

        # Phase 4: Execute actions
        if actions:
            try:
                await self.game.act(actions)
            except Exception as e:
                logger.error(f"Action execution failed: {e}")
                await self.stream.broadcast_error(f"Action failed: {e}")
                return

        # Phase 5: Read post-action state and compute deltas
        post_state = await self.game.get_state()
        pre_snapshot = self._snapshot(pre_state)
        self._sync_state_from_raw(post_state)
        post_snapshot = self._snapshot(post_state)
        deltas = self._compute_deltas(pre_snapshot, post_snapshot)

        # Phase 6: Record history
        self.gs.action_history.append(ActionEntry(
            actions=actions,
            reasoning=reasoning,
            mode=self.gs.game_mode.value,
            map_id=self.gs.map_id,
            map_name=self.gs.map_name,
            position=self.gs.position,
            turn=self.gs.turn_count,
        ))
        # Trim history to prevent unbounded growth
        if len(self.gs.action_history) > 200:
            self.gs.action_history = self.gs.action_history[-150:]

        # Phase 7: Track milestones and meaningful events
        await self._track_deltas(deltas)

        if deltas.is_meaningful():
            self.gs.last_meaningful_turn = self.gs.turn_count

        # Phase 8: Memory synthesis (if manager available and something happened)
        if self.memory and deltas.is_meaningful():
            try:
                await self.memory.record(self.gs, deltas)
            except Exception as e:
                logger.warning(f"Memory synthesis failed: {e}")

        # Phase 9: Map update
        if self.map_mgr:
            self.map_mgr.record_visit(
                self.gs.map_id, self.gs.map_name, self.gs.turn_count, self.gs.position
            )
            if deltas.location_changed:
                self.map_mgr.record_transition(
                    pre_snapshot["map_id"], post_snapshot["map_id"],
                    pre_snapshot["map_name"], post_snapshot["map_name"],
                    actions,
                )
            self.gs.visited_maps.add(self.gs.map_id)

        # Phase 9b: Objective completion check
        if self.objectives and self.gs.turn_count % self.config.completion_check_interval == 0:
            try:
                completed = await self.objectives.check_completions(self.gs, deltas)
                if completed:
                    await self.stream.broadcast_objective_update(
                        [o.model_dump() for o in self.gs.active_objectives]
                    )
            except Exception as e:
                logger.warning(f"Objective check failed: {e}")

        # Phase 10: Stream to viewer
        screenshot = await self.game.screenshot_base64()
        serialized = self.gs.serialize()
        # Inject map data from the map graph
        if self.map_mgr:
            serialized["map"] = self._serialize_map()
        # Inject live tile grid from emulator (fetched earlier this turn)
        if tile_data is not None:
            serialized["tile_grid"] = tile_data.get("grid", [])
            serialized["tile_sprites"] = tile_data.get("sprites", [])
        await self.stream.broadcast_turn_complete(
            turn=self.gs.turn_count,
            mode=self.gs.game_mode.value,
            actions=actions,
            state=serialized,
            screenshot=screenshot,
            reasoning=reasoning,
            deltas=deltas.to_dict(),
        )

        # Phase 11: Auto-save periodically
        if self.gs.turn_count % self.config.save_interval == 0:
            try:
                await self.game.save(f"autosave_t{self.gs.turn_count}")
                logger.debug(f"Auto-saved at turn {self.gs.turn_count}")
            except Exception as e:
                logger.warning(f"Auto-save failed: {e}")

    # ── Decision Routing ───────────────────────────────────────────────

    async def _decide(self, raw_state: Dict[str, Any]) -> tuple[List[str], str]:
        """Route to the appropriate agent and return (actions, reasoning)."""

        # Intro phase: party empty + no pokedex = still in intro/pre-starter
        # Route through the intro agent which uses vision to detect screen type.
        # If intro agent returns None, it detected overworld — fall through to explore.
        if self.intro_agent.is_intro_phase(self.gs):
            actions, reasoning = await self.intro_agent.decide(self.gs, raw_state)
            if actions is not None:
                return actions, reasoning
            # Fall through to normal explore agent

        match self.gs.game_mode:
            case GameMode.DIALOG:
                actions = self.menu_agent.handle_dialog(raw_state)
                return actions, "Advancing dialog..."

            case GameMode.BATTLE:
                return await self.battle_agent.decide(self.gs, raw_state)

            case GameMode.MENU:
                actions = self.menu_agent.handle_menu(raw_state)
                return actions, "Navigating menu..."

            case GameMode.EXPLORE:
                return await self.explore_agent.decide(self.gs, raw_state)

        return ["wait_60"], "Unknown mode, waiting..."

    # ── Mode Detection ─────────────────────────────────────────────────

    def _detect_mode(self, raw_state: Dict[str, Any]) -> GameMode:
        """Detect current game mode from RAM state."""
        dialog = raw_state.get("dialog", {})
        battle = raw_state.get("battle", {})

        if dialog.get("active", False):
            return GameMode.DIALOG
        if battle.get("in_battle", False):
            return GameMode.BATTLE
        return GameMode.EXPLORE

    # ── State Sync ─────────────────────────────────────────────────────

    def _sync_state_from_raw(self, raw: Dict[str, Any]) -> None:
        """Sync GameState fields from raw emulator state JSON."""
        player = raw.get("player", {})
        self.gs.player_name = player.get("name", "")
        self.gs.rival_name = player.get("rival_name", "")
        self.gs.money = player.get("money", 0)
        pos = player.get("position", {})
        if isinstance(pos, dict):
            self.gs.position = (pos.get("y", 0), pos.get("x", 0))
        elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
            self.gs.position = (pos[0], pos[1])
        else:
            self.gs.position = (0, 0)
        self.gs.facing = player.get("facing", "down")
        self.gs.play_time = player.get("play_time", "")

        # Badges
        badges_data = player.get("badges", [])
        if isinstance(badges_data, list):
            self.gs.badges = badges_data
            self.gs.badge_count = len(badges_data)
        elif isinstance(badges_data, int):
            self.gs.badge_count = badges_data

        # Map
        map_info = raw.get("map", {})
        self.gs.prev_map_id = self.gs.map_id
        self.gs.prev_map_name = self.gs.map_name
        self.gs.prev_position = self.gs.position
        self.gs.map_id = map_info.get("map_id", 0)
        self.gs.map_name = map_info.get("map_name", "Unknown")

        # Party
        party_raw = raw.get("party", [])
        self.gs.party = [self._parse_pokemon(p) for p in party_raw]

        # Bag
        self.gs.bag = raw.get("bag", [])

        # Battle
        battle = raw.get("battle", {})
        self.gs.in_battle = battle.get("in_battle", False)
        self.gs.battle_type = battle.get("type", "none")
        enemy_data = battle.get("enemy")
        self.gs.enemy = self._parse_pokemon(enemy_data) if enemy_data else None

        # Dialog
        dialog = raw.get("dialog", {})
        self.gs.dialog_active = dialog.get("active", False)

        # Flags
        flags = raw.get("flags", {})
        self.gs.has_pokedex = flags.get("has_pokedex", False)
        self.gs.pokedex_owned = flags.get("pokedex_owned", 0)
        self.gs.pokedex_seen = flags.get("pokedex_seen", 0)

    def _parse_pokemon(self, data: Dict[str, Any]) -> Pokemon:
        """Parse a Pokemon dict from the emulator state."""
        moves = []
        for m in data.get("moves", []):
            if isinstance(m, dict):
                moves.append(Move(
                    id=m.get("id", 0),
                    name=m.get("move", m.get("name", "")),
                    pp=m.get("pp", 0),
                ))
            elif isinstance(m, str):
                moves.append(Move(name=m))

        return Pokemon(
            species_id=data.get("species_id", data.get("id", 0)),
            species=data.get("species", data.get("name", "MissingNo.")),
            nickname=data.get("nickname", ""),
            level=data.get("level", 1),
            hp=data.get("hp", 0),
            max_hp=data.get("max_hp", 0),
            status=data.get("status", "OK"),
            types=data.get("types", []),
            moves=moves,
            attack=data.get("attack", 0),
            defense=data.get("defense", 0),
            speed=data.get("speed", 0),
            special=data.get("special", 0),
            experience=data.get("experience", 0),
        )

    def _snapshot(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Capture a snapshot of key state fields for delta computation."""
        player = raw.get("player", {})
        map_info = raw.get("map", {})
        battle = raw.get("battle", {})
        flags = raw.get("flags", {})
        pos = player.get("position", {})

        return {
            "map_id": map_info.get("map_id", 0),
            "map_name": map_info.get("map_name", "Unknown"),
            "position": (pos.get("y", 0), pos.get("x", 0)) if isinstance(pos, dict) else (0, 0),
            "badges": player.get("badges", []),
            "badge_count": flags.get("badge_count", len(player.get("badges", []))),
            "money": player.get("money", 0),
            "party": raw.get("party", []),
            "bag": raw.get("bag", []),
            "in_battle": battle.get("in_battle", False),
            "pokedex_owned": flags.get("pokedex_owned", 0),
        }

    def _compute_deltas(
        self, pre: Dict[str, Any], post: Dict[str, Any]
    ) -> StateDelta:
        """Compute what changed between pre-action and post-action state."""
        delta = StateDelta(
            old_map_id=pre["map_id"],
            new_map_id=post["map_id"],
            old_map_name=pre["map_name"],
            new_map_name=post["map_name"],
            old_position=pre["position"],
            new_position=post["position"],
            location_changed=pre["map_id"] != post["map_id"],
            money_delta=post["money"] - pre["money"],
            battle_started=not pre["in_battle"] and post["in_battle"],
            battle_ended=pre["in_battle"] and not post["in_battle"],
        )

        # Badge check
        pre_badges = set(pre["badges"]) if isinstance(pre["badges"], list) else set()
        post_badges = set(post["badges"]) if isinstance(post["badges"], list) else set()
        new_badges = post_badges - pre_badges
        if new_badges:
            delta.badge_gained = next(iter(new_badges))

        # Party HP changes
        pre_hp = sum(p.get("hp", 0) for p in pre["party"])
        post_hp = sum(p.get("hp", 0) for p in post["party"])
        delta.hp_changed = pre_hp != post_hp

        # Party size changes (caught or lost)
        if len(post["party"]) > len(pre["party"]):
            # New Pokemon caught
            pre_species = {p.get("species", "") for p in pre["party"]}
            for p in post["party"]:
                if p.get("species", "") not in pre_species:
                    delta.pokemon_caught = p.get("species", "unknown")
                    break

        # Level ups
        for i, p in enumerate(post["party"]):
            if i < len(pre["party"]):
                if p.get("level", 0) > pre["party"][i].get("level", 0):
                    delta.pokemon_leveled = p.get("species", "unknown")
                    delta.new_level = p.get("level", 0)
                    break

        # Bag changes
        pre_items = {i.get("item", ""): i.get("quantity", 0) for i in pre["bag"]}
        post_items = {i.get("item", ""): i.get("quantity", 0) for i in post["bag"]}
        for item, qty in post_items.items():
            if item not in pre_items or qty > pre_items.get(item, 0):
                delta.item_gained = item
                break
        for item, qty in pre_items.items():
            if item not in post_items or post_items.get(item, 0) < qty:
                delta.item_lost = item
                break

        delta.party_changed = (
            delta.pokemon_caught is not None
            or delta.pokemon_leveled is not None
            or delta.hp_changed
        )

        return delta

    # ── Map Serialization ──────────────────────────────────────────────

    def _serialize_map(self) -> Dict[str, Any]:
        """Serialize map graph data for the viewer."""
        locations = []
        for node in self.map_mgr.nodes.values():
            locations.append({
                "map_id": node.map_id,
                "name": node.name,
                "visits": node.visits,
                "positions": [list(p) for p in node.positions_visited],
                "has_pokecenter": node.has_pokecenter,
                "has_pokemart": node.has_pokemart,
                "has_gym": node.has_gym,
            })
        connections = []
        for edge in self.map_mgr.edges:
            from_node = self.map_mgr.nodes.get(edge.from_id)
            to_node = self.map_mgr.nodes.get(edge.to_id)
            connections.append({
                "from_id": edge.from_id,
                "from_name": from_node.name if from_node else "?",
                "to_id": edge.to_id,
                "to_name": to_node.name if to_node else "?",
                "times_traversed": edge.times_traversed,
            })
        return {
            "current_map_id": self.gs.map_id,
            "current_position": list(self.gs.position),
            "locations": locations,
            "connections": connections,
        }

    # ── Milestone Tracking ─────────────────────────────────────────────

    async def _track_deltas(self, deltas: StateDelta) -> None:
        """Track milestones from state deltas."""
        if deltas.badge_gained:
            m = Milestone(
                name=f"{deltas.badge_gained} Badge",
                turn=self.gs.turn_count,
                details=f"Earned the {deltas.badge_gained} Badge",
                category="badge",
            )
            self.gs.milestones.append(m)
            self.gs.last_badge_turn = self.gs.turn_count
            await self.stream.broadcast_milestone(m.name, m.turn, m.details)
            logger.info(f"MILESTONE: {m.name} at turn {m.turn}")

        if deltas.pokemon_caught:
            m = Milestone(
                name=f"Caught {deltas.pokemon_caught}",
                turn=self.gs.turn_count,
                details=f"Caught a {deltas.pokemon_caught}",
                category="catch",
            )
            self.gs.milestones.append(m)
            await self.stream.broadcast_milestone(m.name, m.turn, m.details)
            logger.info(f"MILESTONE: {m.name} at turn {m.turn}")

        if deltas.pokemon_leveled:
            m = Milestone(
                name=f"{deltas.pokemon_leveled} → Lv{deltas.new_level}",
                turn=self.gs.turn_count,
                category="level",
            )
            self.gs.milestones.append(m)

    # ── Periodic Tasks ─────────────────────────────────────────────────

    async def _periodic_tasks(self) -> None:
        """Run periodic checks and updates."""
        turn = self.gs.turn_count

        # Stuck detection
        if turn % self.config.stuck_check_interval == 0:
            turns_since_meaningful = turn - self.gs.last_meaningful_turn
            if turns_since_meaningful >= self.config.max_turns_stuck:
                logger.warning(
                    f"Stuck: no meaningful progress in {turns_since_meaningful} turns"
                )
                self.gs.game_over = True
                await self.stream.broadcast_error(
                    f"Episode ended: no progress in {turns_since_meaningful} turns"
                )

        # Strategic review
        if self.objectives and turn % self.config.objective_update_interval == 0:
            try:
                await self.strategist.review_objectives(self.gs)
            except Exception as e:
                logger.warning(f"Strategic review failed: {e}")

        # Save before risky situations
        if self.gs.in_battle and self.gs.battle_type == "trainer":
            # Save before trainer battles when we haven't saved recently
            last_save_turn = (turn // self.config.save_interval) * self.config.save_interval
            if turn - last_save_turn <= 1:
                try:
                    await self.game.save(f"before_trainer_t{turn}")
                except Exception:
                    pass
