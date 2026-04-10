"""Tests for the exploration agent's grid-based pathfinding integration.

These tests focus on the deterministic plumbing — how the agent expands
a `target` cell into walk_* actions via A* — and intentionally stub the
LLM so they don't need a live proxy.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pokemon_opus.agents.explore import ExploreAgent
from pokemon_opus.map.grid import (
    GridAccumulator,
    PLAYER_COL,
    PLAYER_ROW,
    VIEWPORT_H,
    VIEWPORT_W,
)


def _seed_grid(acc: GridAccumulator, py: int, px: int, obstacles=None):
    """Populate the accumulator with one viewport observation around (py, px)."""
    grid = [["." for _ in range(VIEWPORT_W)] for _ in range(VIEWPORT_H)]
    grid[PLAYER_ROW][PLAYER_COL] = "P"
    if obstacles:
        for (r, c) in obstacles:
            grid[r][c] = "#"
    acc.observe(map_id=1, map_name="Lab", player_y=py, player_x=px, tile_grid=grid, turn=1)


def _fake_gs(py: int, px: int, map_id: int = 1) -> SimpleNamespace:
    """Minimal GameState stand-in for the explore agent."""
    return SimpleNamespace(
        turn_count=1,
        map_id=map_id,
        map_name="Lab",
        position=(py, px),
        facing="down",
        badge_count=0,
        badges=[],
        party=[],
        active_objectives=[],
        action_history=[],
        total_tokens=0,
    )


@pytest.mark.asyncio
async def test_target_expands_to_walk_actions():
    acc = GridAccumulator()
    _seed_grid(acc, py=5, px=5)

    agent = ExploreAgent(config=None, llm_client=None, game_client=None, grid=acc)

    # Stub the LLM response: agent picks a target 2 cells east
    agent.llm = SimpleNamespace(
        chat_json=AsyncMock(return_value={
            "parsed": {"reasoning": "heading east", "target": [5, 7]},
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })
    )

    actions, reasoning = await agent.decide(_fake_gs(5, 5), raw_state={})

    assert "heading east" in reasoning
    # 2 east steps
    assert actions == ["walk_right", "walk_right"]


@pytest.mark.asyncio
async def test_target_routes_around_wall():
    acc = GridAccumulator()
    # Put a wall block at viewport cell (PLAYER_ROW, PLAYER_COL+1)
    # i.e. the tile directly east of the player at abs (5, 6)
    # and also (PLAYER_ROW-1, PLAYER_COL+1) and (PLAYER_ROW+1, PLAYER_COL+1)
    _seed_grid(acc, py=5, px=5, obstacles=[
        (PLAYER_ROW - 1, PLAYER_COL + 1),
        (PLAYER_ROW,     PLAYER_COL + 1),
        (PLAYER_ROW + 1, PLAYER_COL + 1),
    ])

    agent = ExploreAgent(config=None, llm_client=None, game_client=None, grid=acc)
    agent.llm = SimpleNamespace(
        chat_json=AsyncMock(return_value={
            "parsed": {"reasoning": "routing around wall", "target": [5, 7]},
            "usage": {},
        })
    )

    actions, _ = await agent.decide(_fake_gs(5, 5), raw_state={})

    # Must be non-empty, must take more than 2 steps, and must not directly
    # go right-right (that'd walk into the wall at (5,6))
    assert len(actions) >= 3
    assert actions != ["walk_right", "walk_right"]


@pytest.mark.asyncio
async def test_target_fallback_to_actions_when_unreachable():
    acc = GridAccumulator()
    _seed_grid(acc, py=5, px=5)

    agent = ExploreAgent(config=None, llm_client=None, game_client=None, grid=acc)
    # Agent supplies unreachable target AND a raw actions fallback
    agent.llm = SimpleNamespace(
        chat_json=AsyncMock(return_value={
            "parsed": {
                "reasoning": "try goal but have backup",
                "target": [999, 999],        # way outside known grid
                "actions": ["press_a"],       # fallback
            },
            "usage": {},
        })
    )

    actions, _ = await agent.decide(_fake_gs(5, 5), raw_state={})
    # Pathfind fails → falls back to raw actions
    assert actions == ["press_a"]


@pytest.mark.asyncio
async def test_raw_actions_still_work_without_target():
    acc = GridAccumulator()
    _seed_grid(acc, py=5, px=5)

    agent = ExploreAgent(config=None, llm_client=None, game_client=None, grid=acc)
    agent.llm = SimpleNamespace(
        chat_json=AsyncMock(return_value={
            "parsed": {"reasoning": "talking to NPC", "actions": ["press_a"]},
            "usage": {},
        })
    )

    actions, reasoning = await agent.decide(_fake_gs(5, 5), raw_state={})
    assert actions == ["press_a"]
    assert "NPC" in reasoning


@pytest.mark.asyncio
async def test_context_includes_tile_map():
    """The agent's prompt context should render the accumulated grid."""
    acc = GridAccumulator()
    _seed_grid(acc, py=5, px=5, obstacles=[(PLAYER_ROW, PLAYER_COL + 1)])

    agent = ExploreAgent(config=None, llm_client=None, game_client=None, grid=acc)
    gs = _fake_gs(5, 5)

    ctx = agent._build_context(gs, raw_state={})
    assert "Tile map" in ctx
    # Player marker should be in the rendered map
    assert " P " in ctx
    # Wall we placed east of the player should be in the rendered map
    assert "#" in ctx


def test_pathfind_to_with_dict_target():
    """Targets can be specified as {'y': ..., 'x': ...} dicts too."""
    acc = GridAccumulator()
    _seed_grid(acc, py=5, px=5)

    agent = ExploreAgent(config=None, llm_client=None, game_client=None, grid=acc)
    gs = _fake_gs(5, 5)

    actions = agent._pathfind_to(gs, {"y": 5, "x": 7})
    assert actions == ["walk_right", "walk_right"]


def test_pathfind_to_no_grid_returns_empty():
    agent = ExploreAgent(config=None, llm_client=None, game_client=None, grid=None)
    gs = _fake_gs(5, 5)
    assert agent._pathfind_to(gs, [5, 7]) == []
