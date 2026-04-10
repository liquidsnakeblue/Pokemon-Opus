"""Tests for the grid accumulator and A* pathfinder."""

from pokemon_opus.map.grid import (
    GridAccumulator,
    PLAYER_COL,
    PLAYER_ROW,
    VIEWPORT_H,
    VIEWPORT_W,
)


def _blank_viewport(fill: str = ".") -> list[list[str]]:
    """Build a 9x10 viewport filled with `fill`, with the player at center."""
    grid = [[fill for _ in range(VIEWPORT_W)] for _ in range(VIEWPORT_H)]
    grid[PLAYER_ROW][PLAYER_COL] = "P"
    return grid


def test_set_full_map_replaces_snapshot():
    """set_full_map wholesale-replaces the stored grid with the new snapshot."""
    acc = GridAccumulator()
    # 5x5 map with walls around the edge and floor inside
    full = [
        list("#####"),
        list("#...#"),
        list("#.P.#"),
        list("#.D.#"),
        list("#####"),
    ]
    n = acc.set_full_map(map_id=42, map_name="Test Room", full_grid=full, turn=1)

    mg = acc.get_map(42)
    assert mg is not None
    assert mg.name == "Test Room"
    # All 25 cells stored
    assert n == 25
    assert len(mg.cells) == 25
    # Walls preserved
    assert acc.get_tile(42, 0, 0) == "#"
    assert acc.get_tile(42, 4, 4) == "#"
    # Floor preserved
    assert acc.get_tile(42, 1, 1) == "."
    # Player cell normalized to terrain (not stored as 'P')
    assert acc.get_tile(42, 2, 2) == "."
    # Door preserved — so the pathfinder can path to it
    assert acc.get_tile(42, 3, 2) == "D"


def test_set_full_map_is_wholesale_replace():
    """A second set_full_map call replaces the first entirely."""
    acc = GridAccumulator()
    acc.set_full_map(1, "A", [["#", "#"], ["#", "."]], turn=1)
    assert acc.get_tile(1, 0, 0) == "#"
    assert acc.get_tile(1, 1, 1) == "."

    # Now replace with a different grid — larger, different content
    acc.set_full_map(1, "A", [list(".....")] * 3, turn=2)
    # Old (1, 1) is still present but now a floor (no out-of-bounds stale data)
    assert acc.get_tile(1, 1, 1) == "."
    # Cells beyond the old grid's bounds now exist
    assert acc.get_tile(1, 2, 4) == "."
    # Total cell count matches the new grid exactly
    mg = acc.get_map(1)
    assert len(mg.cells) == 15


def test_set_full_map_enables_pathfinding_without_prior_visits():
    """With set_full_map, A* can path to any known cell on turn one —
    no need to walk the viewport over the destination first."""
    acc = GridAccumulator()
    # 5-wide corridor with walls on both sides
    full = [
        list("#####"),
        list("#...#"),
        list("#####"),
    ]
    acc.set_full_map(map_id=1, map_name="Corridor", full_grid=full, turn=1)
    # Path from left end (1,1) to right end (1,3) — should succeed
    path = acc.find_path(1, start=(1, 1), goal=(1, 3))
    assert path is not None
    assert path[0] == (1, 1)
    assert path[-1] == (1, 3)


def test_observe_creates_map_and_fills_viewport():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    new = acc.observe(map_id=1, map_name="Oak's Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    mg = acc.get_map(1)
    assert mg is not None
    assert mg.name == "Oak's Lab"
    # 9x10 viewport minus the one player cell which resolves to "." terrain
    # All 90 cells should be recorded
    assert new == VIEWPORT_H * VIEWPORT_W
    # Player's absolute position should be present and walkable
    assert acc.get_tile(1, 5, 5) == "."
    # A corner cell
    assert acc.get_tile(1, 5 - PLAYER_ROW, 5 - PLAYER_COL) == "."


def test_observe_places_tiles_at_absolute_coords():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    # Drop a wall 2 tiles north of the player
    vp[PLAYER_ROW - 2][PLAYER_COL] = "#"
    acc.observe(1, "Lab", player_y=10, player_x=10, tile_grid=vp, turn=1)

    assert acc.get_tile(1, 10 - 2, 10) == "#"
    assert acc.get_tile(1, 10, 10) == "."


def test_observe_merges_across_steps():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)
    first = len(acc.get_map(1).cells)

    # Player moved east 1 tile
    acc.observe(1, "Lab", player_y=5, player_x=6, tile_grid=vp, turn=2)
    second = len(acc.get_map(1).cells)

    # 1 new column revealed on the east side
    assert second == first + VIEWPORT_H


def test_observe_skips_dialog_overlay():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    # Bottom 3 rows are dialog overlay
    for r in range(VIEWPORT_H - 3, VIEWPORT_H):
        for c in range(VIEWPORT_W):
            vp[r][c] = "?"
    acc.observe(1, "Lab", player_y=10, player_x=10, tile_grid=vp, turn=1)

    mg = acc.get_map(1)
    # Only the top 6 rows × 10 cols should be stored
    assert len(mg.cells) == 6 * VIEWPORT_W
    # Nothing was stored in the dialog region
    assert acc.get_tile(1, 10 + (VIEWPORT_H - 3 - PLAYER_ROW), 10) is None


def test_observe_normalizes_dynamic_sprites():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    # NPC one tile west of the player
    vp[PLAYER_ROW][PLAYER_COL - 1] = "N"
    vp[PLAYER_ROW][PLAYER_COL + 1] = "I"  # item
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    # Dynamic entities shouldn't be stored as N/I in the terrain grid
    assert acc.get_tile(1, 5, 4) == "."
    assert acc.get_tile(1, 5, 6) == "."
    # Player tile stored as terrain (walkable)
    assert acc.get_tile(1, 5, 5) == "."


def test_pathfind_straight_line():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    path = acc.find_path(1, start=(5, 5), goal=(5, 8))
    assert path is not None
    assert path[0] == (5, 5)
    assert path[-1] == (5, 8)
    assert len(path) == 4


def test_pathfind_actions():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    path = acc.find_path(1, start=(5, 5), goal=(6, 6))
    assert path is not None
    actions = acc.path_to_actions(path)
    # Manhattan 2 — down + right, in some order
    assert len(actions) == 2
    assert set(actions) <= {"down", "right"}


def test_pathfind_around_wall():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    # Vertical wall at column PLAYER_COL + 1, rows 3-5 inclusive
    for r in range(3, 6):
        vp[r][PLAYER_COL + 1] = "#"
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    path = acc.find_path(1, start=(5, 5), goal=(5, 7))
    assert path is not None
    # Must route around — so length > 3
    assert len(path) > 3
    # No cell in the path should be on the wall column at rows 3-5
    wall_cells = {(y, 6) for y in range(4, 7)}  # absolute coords
    assert not any(cell in wall_cells for cell in path)


def test_pathfind_blocked_by_npc():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    # NPC blocks the direct east path at (5, 6)
    path = acc.find_path(1, start=(5, 5), goal=(5, 7), blocked={(5, 6)})
    assert path is not None
    # Path should detour — can't include (5, 6)
    assert (5, 6) not in path


def test_pathfind_unreachable():
    acc = GridAccumulator()
    vp = _blank_viewport("#")  # all walls
    vp[PLAYER_ROW][PLAYER_COL] = "P"  # only player's tile walkable
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    path = acc.find_path(1, start=(5, 5), goal=(5, 7))
    assert path is None


def test_pathfind_respects_unknown_cells():
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    # Goal is outside the observed viewport → unknown
    goal = (5, 100)
    assert acc.find_path(1, start=(5, 5), goal=goal, allow_unknown=False) is None
    # With allow_unknown=True, A* can traverse unseen cells
    path = acc.find_path(1, start=(5, 5), goal=goal, allow_unknown=True)
    assert path is not None
    assert path[-1] == goal


def test_save_and_load(tmp_path):
    acc = GridAccumulator()
    vp = _blank_viewport(".")
    vp[0][0] = "#"
    acc.observe(1, "Lab", player_y=5, player_x=5, tile_grid=vp, turn=1)

    p = tmp_path / "grid.json"
    acc.save(p)

    acc2 = GridAccumulator()
    assert acc2.load(p) is True
    assert acc2.get_map(1) is not None
    assert acc2.get_map(1).name == "Lab"
    # The wall we placed should survive the round-trip
    abs_y = 5 + (0 - PLAYER_ROW)
    abs_x = 5 + (0 - PLAYER_COL)
    assert acc2.get_tile(1, abs_y, abs_x) == "#"
