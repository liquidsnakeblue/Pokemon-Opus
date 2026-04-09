"""Test the game client talks to the emulator correctly."""

import pytest


@pytest.mark.asyncio
async def test_health_check(game_client):
    """Emulator is running and responsive."""
    healthy = await game_client.health()
    assert healthy is True


@pytest.mark.asyncio
async def test_get_state_structure(game_client):
    """State JSON has all required top-level keys."""
    state = await game_client.get_state()
    required_keys = {"player", "party", "bag", "battle", "dialog", "map", "flags"}
    assert required_keys.issubset(state.keys()), f"Missing keys: {required_keys - state.keys()}"


@pytest.mark.asyncio
async def test_state_player_fields(game_client):
    """Player object has position, name, money, badges."""
    state = await game_client.get_state()
    player = state["player"]
    assert "position" in player
    assert "name" in player
    assert "money" in player
    assert "badges" in player
    pos = player["position"]
    assert isinstance(pos, dict) and "x" in pos and "y" in pos


@pytest.mark.asyncio
async def test_state_map_fields(game_client):
    """Map object has map_id and map_name."""
    state = await game_client.get_state()
    m = state["map"]
    assert "map_id" in m
    assert "map_name" in m
    assert isinstance(m["map_id"], int)


@pytest.mark.asyncio
async def test_screenshot_returns_png(game_client):
    """Screenshot endpoint returns valid PNG bytes."""
    data = await game_client.screenshot()
    assert isinstance(data, bytes)
    assert len(data) > 100
    assert data[:4] == b'\x89PNG'


@pytest.mark.asyncio
async def test_screenshot_base64(game_client):
    """Base64 screenshot endpoint returns a non-empty string."""
    b64 = await game_client.screenshot_base64()
    assert isinstance(b64, str)
    assert len(b64) > 100


@pytest.mark.asyncio
async def test_action_execution(game_client):
    """Can send actions to the emulator without errors."""
    result = await game_client.act(["wait_60"])
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_get_state_and_screenshot_parallel(game_client):
    """Parallel state+screenshot fetch works."""
    state, screenshot = await game_client.get_state_and_screenshot()
    assert "player" in state
    assert len(screenshot) > 100
