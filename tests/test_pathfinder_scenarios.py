"""Pathfinder scenario tests — hand-built maps that mirror real Pokemon
Blue rooms and verify the pathfinder returns the OPTIMAL path every time.

These tests exist because we burned a long debugging session on the
pathfinder routing through bookshelves and NPCs. The cases here cover:

1. Open floor — sanity check.
2. NPCs blocking direct routes (must route around).
3. Bookshelves on walls (must NOT route through them).
4. Items on tables (must not route onto them unless they're the goal).
5. Reaching an item to "pick it up" (goal IS the item).
6. Multi-NPC pinch points.
7. The exact Oak's Lab pre-starter scenario (the one that broke us).

A "correct" path is the *optimal* (shortest valid) one. We assert both
that a path exists AND that its length matches the manhattan-or-better
shortest-path on the constrained grid.
"""

from __future__ import annotations

from typing import List, Set, Tuple

import pytest

from pokemon_opus.agents.explore import ExploreAgent
from pokemon_opus.map.grid import GridAccumulator
from types import SimpleNamespace


# ── helpers ──────────────────────────────────────────────────────────


def _load_map(grid_rows: List[str], map_id: int = 1) -> GridAccumulator:
    """Build an accumulator from an ASCII map.

    Each row is a string of single-char tiles in the same alphabet
    used by the live tile reader (`.` floor, `#` wall, `D` door, etc.).
    `set_full_map` is used because that's the live ingestion path.
    """
    full_grid = [list(r) for r in grid_rows]
    acc = GridAccumulator()
    acc.set_full_map(map_id=map_id, map_name="TestRoom", full_grid=full_grid, turn=1)
    return acc


def _bfs_optimal_length(
    grid_rows: List[str],
    start: Tuple[int, int],
    goal: Tuple[int, int],
    blocked: Set[Tuple[int, int]],
    walkable_chars: Set[str],
) -> int | None:
    """Independent BFS to compute the true shortest-path length, used as
    the oracle the A* result is compared against. Goal cell is allowed
    even if its char isn't walkable (so we can target items)."""
    from collections import deque

    h = len(grid_rows)
    w = len(grid_rows[0]) if h else 0

    def passable(pos: Tuple[int, int]) -> bool:
        if pos == goal:
            return True
        if pos == start:
            return True
        if pos in blocked:
            return False
        y, x = pos
        if not (0 <= y < h and 0 <= x < w):
            return False
        return grid_rows[y][x] in walkable_chars

    if not passable(goal):
        return None

    seen = {start: 0}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            return seen[cur]
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nxt = (cur[0] + dy, cur[1] + dx)
            if nxt in seen or not passable(nxt):
                continue
            seen[nxt] = seen[cur] + 1
            q.append(nxt)
    return None


def _path_is_valid(
    path: List[Tuple[int, int]],
    grid_rows: List[str],
    blocked: Set[Tuple[int, int]],
    walkable_chars: Set[str],
) -> bool:
    """A path is valid if every step is 4-adjacent, in-bounds, walkable,
    and not in the blocked set (excluding start/goal)."""
    if not path or len(path) < 2:
        return False
    h = len(grid_rows)
    w = len(grid_rows[0])
    for i, (y, x) in enumerate(path):
        if not (0 <= y < h and 0 <= x < w):
            return False
        if i not in (0, len(path) - 1):
            if (y, x) in blocked:
                return False
            if grid_rows[y][x] not in walkable_chars:
                return False
        if i > 0:
            py, px = path[i - 1]
            if abs(py - y) + abs(px - x) != 1:
                return False
    return True


def _assert_optimal(
    grid_rows: List[str],
    start: Tuple[int, int],
    goal: Tuple[int, int],
    blocked: Set[Tuple[int, int]] | None = None,
):
    """Run A* and the BFS oracle on the same scenario and compare."""
    from pokemon_opus.map.grid import WALKABLE_CHARS

    blocked = blocked or set()
    acc = _load_map(grid_rows)
    path = acc.find_path(1, start=start, goal=goal, blocked=blocked)

    oracle = _bfs_optimal_length(grid_rows, start, goal, blocked, WALKABLE_CHARS)

    assert path is not None, (
        f"A* found no path but oracle says one exists (len={oracle}). "
        f"start={start} goal={goal}"
    )
    assert oracle is not None, (
        f"A* returned a path but oracle says no path exists. "
        f"path={path}"
    )
    assert _path_is_valid(path, grid_rows, blocked, WALKABLE_CHARS), (
        f"A* returned an invalid path: {path}"
    )
    actual_steps = len(path) - 1
    assert actual_steps == oracle, (
        f"A* path is not optimal: got {actual_steps} steps, "
        f"oracle says {oracle}. path={path}"
    )


# ── scenarios ────────────────────────────────────────────────────────


def test_open_floor_straight_line():
    """Trivial: walk east across an open room."""
    rows = [
        "##########",
        "#........#",
        "#........#",
        "##########",
    ]
    _assert_optimal(rows, start=(1, 1), goal=(1, 8))


def test_open_floor_diagonal():
    """Walk south-east across an open room."""
    rows = [
        "##########",
        "#........#",
        "#........#",
        "#........#",
        "#........#",
        "##########",
    ]
    _assert_optimal(rows, start=(1, 1), goal=(4, 8))


def test_route_around_single_wall():
    """A pillar in the middle forces a detour."""
    rows = [
        "##########",
        "#........#",
        "#...##...#",
        "#...##...#",
        "#........#",
        "##########",
    ]
    _assert_optimal(rows, start=(2, 1), goal=(2, 8))


def test_npc_blocks_direct_path():
    """An NPC sitting one tile east blocks the direct route."""
    rows = [
        "########",
        "#......#",
        "#......#",
        "#......#",
        "########",
    ]
    # NPC at (2, 3); player at (2, 2) wants (2, 5)
    _assert_optimal(rows, start=(2, 2), goal=(2, 5), blocked={(2, 3)})


def test_two_npcs_force_long_detour():
    """Two NPCs in a row force a 2-tile detour."""
    rows = [
        "##########",
        "#........#",
        "#........#",
        "#........#",
        "##########",
    ]
    # NPCs at (2, 3) and (2, 4); player at (2, 2) wants (2, 6)
    _assert_optimal(rows, start=(2, 2), goal=(2, 6), blocked={(2, 3), (2, 4)})


def test_bookshelf_north_wall_must_route_around():
    """Bookshelves on the north wall MUST be classified as walls.
    This is the bug that wrecked Oak's Lab — bookshelves were `O` and
    the accumulator normalized them to walkable floor.

    With the fix, bookshelves come in as `#` from red.py, so this test
    just hard-asserts that the pathfinder treats `#` as a wall (which
    is the contract — but it's a regression check)."""
    rows = [
        "##########",
        "##..####.#",  # bookshelves on the north wall
        "#........#",
        "#........#",
        "#........#",
        "##########",
    ]
    # Player must reach the east side without trying to walk through
    # the bookshelf cluster
    _assert_optimal(rows, start=(2, 1), goal=(2, 8))


def test_oaks_lab_real_scenario():
    """The exact Oak's Lab layout that broke us:

      y= 0:  # # # # # # # # # #
      y= 1:  # # = = . P = = = =     ← bookshelves at (1,2)(1,3) and (1,6)-(1,9)
      y= 2:  . . . . . N . . . .     ← rival NPC at (2,5)
      y= 3:  . . . . N . I I I .     ← Oak at (3,4); pokeballs at (3,6)(3,7)(3,8)
      y= 4:  . . . . . . . . . .

    Player at (1, 5) wants to reach the leftmost pokeball at (3, 6) so it
    can press A on it. The Pokeball is the goal — so it's allowed even
    though it's an item. Other items and NPCs are blocked.

    The user-described correct route is:
      left, down, left, down, down, right, right, right, right
      → 9 steps (1,5)→(1,4)→(2,4)→(2,3)→(3,3)→(4,3)→(4,4)→(4,5)→(4,6)→(3,6)

    With NPC blocking + bookshelves-as-walls, this should be exactly
    what A* returns.
    """
    rows = [
        "##########",
        "##....####",  # we'll patch (1,4) and (1,5) below
        "..........",
        "..........",
        "..........",
    ]
    # Build it precisely from the live snapshot. Bookshelves must be `#`
    # for the pathfinder; only (1,4) and (1,5) on row 1 are floor.
    rows = [
        "##########",
        "##..#.####".replace("#.####", "#####"),
        "..........",
        "..........",
        "..........",
    ]
    # Easier — just write it out cleanly:
    rows = [
        "##########",
        "###.#.####",  # bookshelves at (1,2)(1,3)(1,6)(1,7)(1,8)(1,9); floor at (1,4)(1,5)
        "..........",
        "..........",
        "..........",
    ]
    # Wait — (1,4) needs to be floor and (1,5) is the player. Verify:
    # row 1 = "###.#.####" → cols: 0=#,1=#,2=#,3=.,4=#,5=.,6=#,7=#,8=#,9=#
    # That's wrong — (1,4) is # and (1,2),(1,3) are both #.
    # Correct layout: (1,2),(1,3) = bookshelf; (1,4) = floor; (1,5) = floor (player);
    #                 (1,6),(1,7),(1,8),(1,9) = bookshelf
    # → "###.#.####" no... (1,2) and (1,3) should be bookshelf so cols 2,3 = #
    #   "###" "..." then "####" — but only 2 floor tiles between.
    #   "##" + "##" + ".." + "####" = 10 chars: ##....####? no, that's 4 floors.
    # Real layout: cols 0,1 = wall; cols 2,3 = bookshelf (#); col 4 = floor;
    #              col 5 = floor (player); cols 6,7,8,9 = bookshelf (#)
    # = "##" + "##" + "." + "." + "####" = "######..####"? that's 12 chars.
    # Hmm — the live snapshot showed row 1 as "##OO.POOOO" which is 10 chars:
    #   ##  OO  .  P  OOOO → 2+2+1+1+4 = 10. OK so:
    #   col 0,1 = wall; col 2,3 = bookshelf; col 4 = floor; col 5 = floor (player);
    #   col 6,7,8,9 = bookshelf
    # Translated to ASCII test grid: "##" + "##" + "." + "." + "####" = "####.. ####"
    # That's "##" "##" "." "." "####" = "######..####"? no that's 12.
    # 2+2+1+1+4 = 10 ✓. The string is:
    #   "##" + "##" + "." + "." + "####" → "##" "##" ".." "####"  → "####..####"
    rows = [
        "##########",
        "####..####",   # bookshelves frame two floor tiles (1,4)(1,5)
        "..........",
        "..........",
        "..........",
    ]
    # Sanity-check the layout in the test itself:
    assert rows[1][4] == "."
    assert rows[1][5] == "."
    assert rows[1][3] == "#"
    assert rows[1][6] == "#"

    start = (1, 5)
    goal = (3, 6)  # the leftmost pokeball
    blocked = {
        (3, 4),  # Oak NPC
        (2, 5),  # rival NPC
        # (3, 6) is the goal, so it's allowed
        (3, 7),  # other pokeball items — blocked because they're not the goal
        (3, 8),
    }
    _assert_optimal(rows, start=start, goal=goal, blocked=blocked)


def test_pickup_item_on_ground():
    """An item lying on plain floor can be the goal, and the agent
    walks ONTO it. Items at non-goal positions are still blocked."""
    rows = [
        "########",
        "#......#",
        "#......#",
        "########",
    ]
    # Item at (2, 5) is the target; another item at (2, 3) is not.
    _assert_optimal(
        rows,
        start=(2, 1),
        goal=(2, 5),
        blocked={(2, 3)},  # the other item
    )


def test_unreachable_goal_returns_none():
    """Goal walled off — pathfinder must return None."""
    rows = [
        "########",
        "#..#...#",
        "#..#...#",
        "#..#...#",
        "########",
    ]
    acc = _load_map(rows)
    path = acc.find_path(1, start=(2, 1), goal=(2, 5))
    assert path is None


def test_corridor_with_npc_choke():
    """A 1-tile-wide corridor with an NPC in the middle is unreachable."""
    rows = [
        "##########",
        "#........#",
        "########.#",
        "#........#",
        "#.########",
        "#........#",
        "##########",
    ]
    # NPC sits in the only opening at (2, 8)
    acc = _load_map(rows)
    path = acc.find_path(
        1, start=(1, 1), goal=(5, 8), blocked={(2, 8)}
    )
    assert path is None


def test_npc_moves_out_of_the_way_next_turn():
    """First call: NPC blocks direct route → detour. Second call (sim
    NPC moved): no block → direct route. Verifies the blocked set is
    NOT cached anywhere."""
    rows = [
        "########",
        "#......#",
        "#......#",
        "########",
    ]
    acc = _load_map(rows)

    # Turn 1: NPC at (2, 3) blocks
    p1 = acc.find_path(1, start=(2, 2), goal=(2, 5), blocked={(2, 3)})
    assert p1 is not None
    len1 = len(p1) - 1

    # Turn 2: NPC gone
    p2 = acc.find_path(1, start=(2, 2), goal=(2, 5), blocked=set())
    assert p2 is not None
    len2 = len(p2) - 1
    assert len2 == 3  # straight east
    assert len2 < len1  # the direct route is shorter than the detour
