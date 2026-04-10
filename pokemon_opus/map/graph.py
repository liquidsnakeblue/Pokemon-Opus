"""
Map Graph — room-level connectivity graph for high-level navigation.
Tracks which maps connect to which, discovered through gameplay.
Adapted from Zork-Opus map_graph.py.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MapNode:
    """A discovered map location."""
    map_id: int
    name: str
    visits: int = 0
    first_visit_turn: int = 0
    last_visit_turn: int = 0
    has_pokecenter: bool = False
    has_pokemart: bool = False
    has_gym: bool = False
    positions_visited: Set[Tuple[int, int]] = field(default_factory=set)
    # Door labels: (y, x) of a warp tile in this map → human-readable
    # destination name (e.g. "Oak's Lab" or "map 40" before we know).
    # Populated from RAM warp tables on every turn so labels appear as
    # soon as the destination map's name is learned.
    door_labels: Dict[Tuple[int, int], str] = field(default_factory=dict)


@dataclass
class MapEdge:
    """A discovered connection between two maps."""
    from_id: int
    to_id: int
    actions: List[str] = field(default_factory=list)  # Actions that caused the transition
    bidirectional: bool = True  # Assume bidirectional unless proven otherwise
    times_traversed: int = 0


class MapGraph:
    """Graph of discovered map connections with BFS pathfinding."""

    def __init__(self):
        self.nodes: Dict[int, MapNode] = {}
        self.edges: List[MapEdge] = []
        self._adjacency: Dict[int, Set[int]] = {}  # map_id -> set of connected map_ids

    # Game Boy screen is 160x144 pixels, tiles are 16x16
    # Visible area is 10 wide x 9 tall, player roughly centered
    VIEWPORT_HALF_W = 5  # tiles left/right of player
    VIEWPORT_HALF_H = 4  # tiles above/below player

    def record_visit(self, map_id: int, name: str, turn: int, position: Tuple[int, int]) -> None:
        """Record a visit — marks the entire visible viewport as discovered."""
        if map_id not in self.nodes:
            self.nodes[map_id] = MapNode(
                map_id=map_id,
                name=name,
                first_visit_turn=turn,
            )
            logger.info(f"New location discovered: {name} (map_id={map_id})")

        node = self.nodes[map_id]
        node.visits += 1
        node.last_visit_turn = turn

        # Mark all tiles visible on the Game Boy screen as discovered
        py, px = position
        for dy in range(-self.VIEWPORT_HALF_H, self.VIEWPORT_HALF_H + 1):
            for dx in range(-self.VIEWPORT_HALF_W, self.VIEWPORT_HALF_W + 1):
                node.positions_visited.add((py + dy, px + dx))

    def record_transition(
        self,
        from_id: int,
        to_id: int,
        from_name: str,
        to_name: str,
        actions: List[str],
    ) -> None:
        """Record a transition between two maps."""
        # Ensure both nodes exist
        if from_id not in self.nodes:
            self.nodes[from_id] = MapNode(map_id=from_id, name=from_name)
        if to_id not in self.nodes:
            self.nodes[to_id] = MapNode(map_id=to_id, name=to_name)

        # Check if edge already exists
        existing = self._find_edge(from_id, to_id)
        if existing:
            existing.times_traversed += 1
            return

        # Add new edge
        edge = MapEdge(from_id=from_id, to_id=to_id, actions=actions, times_traversed=1)
        self.edges.append(edge)

        # Update adjacency
        self._adjacency.setdefault(from_id, set()).add(to_id)
        self._adjacency.setdefault(to_id, set()).add(from_id)  # Assume bidirectional

        logger.info(f"New connection: {from_name} → {to_name}")

    def find_path(self, from_id: int, to_id: int) -> Optional[List[int]]:
        """BFS pathfinding between two map locations.

        Returns: List of map_ids forming the path, or None if unreachable.
        """
        if from_id == to_id:
            return [from_id]

        if from_id not in self._adjacency or to_id not in self.nodes:
            return None

        visited: Set[int] = {from_id}
        queue: deque[List[int]] = deque([[from_id]])

        while queue:
            path = queue.popleft()
            current = path[-1]

            for neighbor in self._adjacency.get(current, set()):
                if neighbor == to_id:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return None  # Unreachable

    def record_door_labels(
        self,
        parent_map_id: int,
        warps: List[Dict[str, Any]],
        parent_name: str = "",
    ) -> None:
        """For each warp in the parent map, record the destination map's
        name (if known) at the warp's coordinates. Updates progressively
        as we discover more child maps — a door labeled "map 40" today
        becomes "Oak's Lab" the moment we walk through it for the first
        time."""
        if parent_map_id not in self.nodes:
            # Lazy-create the parent so labels can be recorded on the
            # very first turn we see a map (record_visit runs later in
            # the same turn cycle).
            self.nodes[parent_map_id] = MapNode(
                map_id=parent_map_id, name=parent_name
            )
        parent = self.nodes[parent_map_id]
        for w in warps:
            try:
                y = int(w["y"])
                x = int(w["x"])
                dest_id = int(w["dest_map"])
            except (KeyError, ValueError, TypeError):
                continue
            dest_node = self.nodes.get(dest_id)
            if dest_node and dest_node.name and dest_node.name != "Unknown":
                parent.door_labels[(y, x)] = dest_node.name
            else:
                # Don't overwrite a known label with a placeholder.
                if (y, x) not in parent.door_labels:
                    parent.door_labels[(y, x)] = f"map {dest_id}"

    def get_door_label(self, map_id: int, y: int, x: int) -> Optional[str]:
        """Look up the destination label for a door at (y, x) of map_id."""
        n = self.nodes.get(map_id)
        if n is None:
            return None
        return n.door_labels.get((y, x))

    def get_neighbors(self, map_id: int) -> List[MapNode]:
        """Get all directly connected map locations."""
        neighbor_ids = self._adjacency.get(map_id, set())
        return [self.nodes[nid] for nid in neighbor_ids if nid in self.nodes]

    def get_exploration_frontier(self) -> List[MapNode]:
        """Get locations that have been visited only once (potential for more exploration)."""
        return [
            node for node in self.nodes.values()
            if node.visits <= 1 and len(node.positions_visited) <= 3
        ]

    def get_unvisited_neighbors(self, map_id: int) -> List[int]:
        """Get neighbor map_ids that have never been visited."""
        neighbors = self._adjacency.get(map_id, set())
        return [nid for nid in neighbors if nid not in self.nodes or self.nodes[nid].visits == 0]

    def render_text(self) -> str:
        """Render a text summary of the discovered map."""
        if not self.nodes:
            return "No locations discovered yet."

        lines = [f"=== DISCOVERED MAP ({len(self.nodes)} locations, {len(self.edges)} connections) ==="]
        for node in sorted(self.nodes.values(), key=lambda n: n.first_visit_turn):
            neighbors = self._adjacency.get(node.map_id, set())
            neighbor_names = [self.nodes[nid].name for nid in neighbors if nid in self.nodes]
            connections = ", ".join(neighbor_names) if neighbor_names else "no connections"
            markers = []
            if node.has_pokecenter:
                markers.append("PC")
            if node.has_pokemart:
                markers.append("Mart")
            if node.has_gym:
                markers.append("Gym")
            marker_str = f" [{', '.join(markers)}]" if markers else ""
            lines.append(
                f"  {node.name} (visits: {node.visits}){marker_str} → {connections}"
            )
        return "\n".join(lines)

    def _find_edge(self, from_id: int, to_id: int) -> Optional[MapEdge]:
        """Find an existing edge between two maps (checks both directions)."""
        for edge in self.edges:
            if (edge.from_id == from_id and edge.to_id == to_id) or \
               (edge.bidirectional and edge.from_id == to_id and edge.to_id == from_id):
                return edge
        return None

    # ── Persistence ────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Save map graph to JSON file."""
        data = {
            "nodes": {
                str(nid): {
                    "map_id": n.map_id,
                    "name": n.name,
                    "visits": n.visits,
                    "first_visit_turn": n.first_visit_turn,
                    "last_visit_turn": n.last_visit_turn,
                    "has_pokecenter": n.has_pokecenter,
                    "has_pokemart": n.has_pokemart,
                    "has_gym": n.has_gym,
                    "positions_visited": [list(p) for p in n.positions_visited],
                    "door_labels": [
                        [y, x, label] for (y, x), label in n.door_labels.items()
                    ],
                }
                for nid, n in self.nodes.items()
            },
            "edges": [
                {
                    "from_id": e.from_id,
                    "to_id": e.to_id,
                    "actions": e.actions,
                    "bidirectional": e.bidirectional,
                    "times_traversed": e.times_traversed,
                }
                for e in self.edges
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2))
        logger.info(f"Map saved: {len(self.nodes)} nodes, {len(self.edges)} edges → {path}")

    def load(self, path: str | Path) -> bool:
        """Load map graph from JSON file. Returns True if loaded."""
        p = Path(path)
        if not p.exists():
            return False

        try:
            data = json.loads(p.read_text())
            for nid_str, ndata in data.get("nodes", {}).items():
                nid = int(nid_str)
                self.nodes[nid] = MapNode(
                    map_id=ndata["map_id"],
                    name=ndata["name"],
                    visits=ndata.get("visits", 0),
                    first_visit_turn=ndata.get("first_visit_turn", 0),
                    last_visit_turn=ndata.get("last_visit_turn", 0),
                    has_pokecenter=ndata.get("has_pokecenter", False),
                    has_pokemart=ndata.get("has_pokemart", False),
                    has_gym=ndata.get("has_gym", False),
                    positions_visited={tuple(p) for p in ndata.get("positions_visited", [])},
                    door_labels={
                        (int(y), int(x)): str(label)
                        for y, x, label in ndata.get("door_labels", [])
                    },
                )

            for edata in data.get("edges", []):
                edge = MapEdge(
                    from_id=edata["from_id"],
                    to_id=edata["to_id"],
                    actions=edata.get("actions", []),
                    bidirectional=edata.get("bidirectional", True),
                    times_traversed=edata.get("times_traversed", 0),
                )
                self.edges.append(edge)
                self._adjacency.setdefault(edge.from_id, set()).add(edge.to_id)
                if edge.bidirectional:
                    self._adjacency.setdefault(edge.to_id, set()).add(edge.from_id)

            logger.info(f"Map loaded: {len(self.nodes)} nodes, {len(self.edges)} edges from {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load map from {path}: {e}")
            return False
